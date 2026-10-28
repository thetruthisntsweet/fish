"""Messages between the game server and its clients (T2.1 subtask 8; the game's, T3.1).

These Pydantic models are the single source of truth for everything sent over the
WebSocket. ``fish_server.schema_export`` turns them into JSON Schema in ``schemas/``,
and ``scripts/gen_types.sh`` turns those into TypeScript in ``client/src/generated/``.
Never hand-write a message type on the client.

Every message has a ``type`` field naming it, so a receiver can tell messages apart, and
unknown fields are an error. Client messages are read strictly: a number must be a JSON
number, not a string or a boolean.

**Client to server.** ``client_hello`` first. Then, in the lobby, ``join_queue`` (solo
matchmaking) or ``create_room`` and ``join_room`` (a group), and ``leave``. At a table,
``press`` (a Call press naming a set, with the number of the last event seen, R.8.3, R.8.7)
and ``act`` (a seat action as its ``fish-action-index-v1`` index, read from the player's own
seat). ``pong`` answers every ``ping``. After a game, ``note_answer`` answers the
note-taking question.

**Server to client.** ``server_hello``. ``lobby``: whether this player is waiting, and for
what. ``update``: after every change at the table, the seat's view (``fish-view-v1``, D33)
with what the website lets the seat do now and the running timers. ``rejected``: an input
from this player was not applied, and why. ``ping``, for round-trip times (R.8.7).
``note_question``: once the rules end a game, the one question asked of each person still in
it (Research Plan §4; docs/corpus.md §4.2). ``error``: a message the server cannot act on.

The view's ``legal`` list is the engine's, the environment's mask (D33). On the website a call
starts with a press and nobody passes, so a client offers exactly ``update.actions`` and
``update.pressable``, which ``fish_server.table.Table`` decides.
"""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fish_rules.action_index import NUM_ACTIONS, encode
from fish_rules.cards import NUM_CARDS, NUM_SEATS, NUM_SETS, SEATS, Seat
from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_rules.view import view_to_data
from fish_server.table import Table

PROTOCOL_VERSION = 3
"""Version of the message format. Bumped whenever a message changes shape."""

ROOM_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
"""Letters and digits a room code is made of: none that look alike (no I, O, 0 or 1)."""

ROOM_CODE_LENGTH: Final = 6
ROOM_CODE_PATTERN: Final = f"^[{ROOM_CODE_ALPHABET}]{{{ROOM_CODE_LENGTH}}}$"

type SeatNumber = Annotated[int, Field(ge=0, lt=NUM_SEATS)]
type SetNumber = Annotated[int, Field(ge=0, lt=NUM_SETS)]
type CardNumber = Annotated[int, Field(ge=0, lt=NUM_CARDS)]
type TeamNumber = Annotated[int, Field(ge=0, le=1)]
type ActionIndex = Annotated[int, Field(ge=0, lt=NUM_ACTIONS)]
type Count = Annotated[int, Field(ge=0)]


class Message(BaseModel):
    """Base for every message: immutable, unknown fields an error, nothing coerced."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Data(BaseModel):
    """Base for the parts of a message: immutable, unknown fields an error."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# ---------------------------------------------------------------- client to server


class ClientHello(Message):
    """First message from a client after the WebSocket opens."""

    type: Literal["client_hello"]
    protocol_version: int = Field(ge=1, description="PROTOCOL_VERSION the client was built with.")


class JoinQueue(Message):
    """Wait for a table through solo matchmaking."""

    type: Literal["join_queue"]


class CreateRoom(Message):
    """Make a room for a group; the server replies with its code in ``lobby``."""

    type: Literal["create_room"]


class JoinRoom(Message):
    """Join the room with this code."""

    type: Literal["join_room"]
    code: str = Field(pattern=ROOM_CODE_PATTERN, description="Six letters and digits.")


class Leave(Message):
    """Stop waiting: leave the queue or the room."""

    type: Literal["leave"]


class Press(Message):
    """R.8.3: press Call, naming a set. R.8.7: ``seen`` is the number of the last event the
    player had seen (``view.last_event.number``), null before the first."""

    type: Literal["press"]
    set_id: SetNumber
    seen: Count | None


class Act(Message):
    """A seat action: its index in ``fish-action-index-v1``, from the player's own seat; one
    of ``update.actions``."""

    type: Literal["act"]
    index: ActionIndex


class NoteAnswer(Message):
    """The answer to ``note_question``: ``declined`` for preferring not to say."""

    type: Literal["note_answer"]
    answer: Literal["yes", "no", "declined"]


class Pong(Message):
    """The answer to ``ping``, sent at once with the same nonce."""

    type: Literal["pong"]
    nonce: Count


# ---------------------------------------------------------------- the view (fish-view-v1)


class AskEventData(Data):
    """R.3.3: an ask and its answer."""

    type: Literal["AskEvent"]
    number: Count
    asker: SeatNumber
    target: SeatNumber
    card: CardNumber
    success: bool


class CallEventData(Data):
    """R.4.4-R.4.5, R.2.3: a call and its result, with the true holders of its six cards.
    ``assignment`` is null if the caller ran out of time."""

    type: Literal["CallEvent"]
    number: Count
    caller: SeatNumber
    set_id: SetNumber
    source: Literal["window", "turn", "runout"]
    assignment: Annotated[list[SeatNumber], Field(min_length=6, max_length=6)] | None
    holders: Annotated[list[SeatNumber], Field(min_length=6, max_length=6)]
    correct: bool
    scored_by: TeamNumber


class ChoiceEventData(Data):
    """R.5: the after-call choice's outcome."""

    type: Literal["ChoiceEvent"]
    number: Count
    team: TeamNumber
    seat: SeatNumber


class CallInView(Data):
    """R.8.3: the call being assigned, shown to everyone."""

    caller: SeatNumber
    set_id: SetNumber


class ChoiceInView(Data):
    """R.5.2: the after-call choice in progress; ``own_vote`` is this seat's only."""

    team: TeamNumber
    candidates: list[SeatNumber]
    chooser: SeatNumber | None
    own_vote: SeatNumber | None


class WindowInView(Data):
    """R.8.3: a window is open; this seat's own declaration in it, never anyone else's."""

    own_declaration: SetNumber | None
    responded: bool


class View(Data):
    """A seat's view exactly as ``fish_rules.view.view_to_data`` writes it (``fish-view-v1``,
    docs/determinism.md §10)."""

    encoding: Literal["fish-view-v1"]
    seat: SeatNumber
    hand: list[CardNumber]
    hand_sizes: Annotated[list[Count], Field(min_length=6, max_length=6)]
    scored_by: Annotated[list[TeamNumber | None], Field(min_length=9, max_length=9)]
    phase: Literal["turn", "window", "assign", "choose", "vote", "runout", "over"]
    current: SeatNumber | None
    call: CallInView | None
    choice: ChoiceInView | None
    window: WindowInView | None
    last_event: (
        Annotated[AskEventData | CallEventData | ChoiceEventData, Field(discriminator="type")]
        | None
    )
    outcome: Literal["finished", "unfinished"] | None
    winner: TeamNumber | None
    legal: list[ActionIndex]


# ---------------------------------------------------------------- server to client


class ServerHello(Message):
    """The server's reply to ClientHello: which versions this server runs."""

    type: Literal["server_hello"]
    protocol_version: int = Field(ge=1, description="PROTOCOL_VERSION the server speaks.")
    ruleset_version: str = Field(description="Canonical Ruleset version, e.g. '1.1'.")
    rng_algorithm: str = Field(description="fish_rules.rng.RNG_ALGORITHM.")


class Lobby(Message):
    """Whether this player is waiting for a table: ``waiting`` is null when not, ``solo`` in
    the matchmaking queue, ``group`` in room ``code``. ``people`` counts those waiting with
    them, themselves included (0 when not waiting)."""

    type: Literal["lobby"]
    waiting: Literal["solo", "group"] | None
    code: Annotated[str, Field(pattern=ROOM_CODE_PATTERN)] | None
    people: Count


class Timer(Data):
    """A running timer and how long it had left when the update was sent (R.2.6, R.8.5)."""

    name: Literal["window", "assignment", "choice", "turn"]
    ms_left: Count


class Update(Message):
    """This seat's view now, sent after every change at the table, the moment it happens
    (R.2.6). ``actions`` are the indices this seat may ``act`` with, ascending, and
    ``pressable`` the sets it may press Call on. ``timers``: the window, assignment or choice
    timer and the current player's turn timer, whichever are running. ``bots``: the seats a bot
    holds now, shown as bots (T3.4); a person handed over finds their own seat among them
    (R.8.4)."""

    type: Literal["update"]
    view: View
    actions: list[ActionIndex]
    pressable: list[SetNumber]
    timers: list[Timer]
    bots: list[SeatNumber]


class Rejected(Message):
    """An input from this player was not applied (R.8.3, R.8.7): ``illegal`` (not allowed
    now; ``discarded`` is true when it was a seat action sent during a window), ``stale`` (a
    press on a set that an event it had not seen changed), or ``malformed``. The next update
    shows the current state."""

    type: Literal["rejected"]
    reason: Literal["illegal", "stale", "malformed"]
    discarded: bool


class Ping(Message):
    """Answer at once with ``pong`` and the same nonce; the server times the round trip."""

    type: Literal["ping"]
    nonce: Count


NOTE_QUESTION_VERSION: Final = "v1"
NOTE_QUESTION: Final = "Did you take notes during this game?"
"""The question asked after every game (Research Plan §4, Consent Screen §1), word for word.
A change to the words needs a new version, which every answer records."""


class NoteQuestion(Message):
    """Asked of each person still in a game once the rules end it: answer with
    ``note_answer``. Unanswered if the person leaves first, or plays on without answering."""

    type: Literal["note_question"]
    version: str
    text: str


class ServerError(Message):
    """A message the server cannot act on. ``protocol_version``: the client was built for
    another version and must reload. ``bad_message``: not a message this protocol has.
    ``not_signed_in``: the connection has no session. ``not_now``: a real message that does
    not fit this moment (joining a queue while seated, pressing with no table, answering no
    question)."""

    type: Literal["error"]
    code: Literal["protocol_version", "bad_message", "not_signed_in", "not_now"]
    message: str


CLIENT_MESSAGES: tuple[type[Message], ...] = (
    ClientHello,
    JoinQueue,
    CreateRoom,
    JoinRoom,
    Leave,
    Press,
    Act,
    Pong,
    NoteAnswer,
)
"""Messages a client sends to the server."""

SERVER_MESSAGES: tuple[type[Message], ...] = (
    ServerHello,
    Lobby,
    Update,
    Rejected,
    Ping,
    NoteQuestion,
    ServerError,
)
"""Messages the server sends to a client."""

type ClientMessage = Annotated[
    ClientHello | JoinQueue | CreateRoom | JoinRoom | Leave | Press | Act | Pong | NoteAnswer,
    Field(discriminator="type"),
]

_CLIENT: Final[TypeAdapter[ClientMessage]] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str | bytes) -> ClientMessage:
    """The client message ``raw`` holds. Raises ``pydantic.ValidationError`` (a ValueError)
    if it is not exactly one."""
    return _CLIENT.validate_json(raw)


def note_question() -> NoteQuestion:
    """The question asked after every game."""
    return NoteQuestion(type="note_question", version=NOTE_QUESTION_VERSION, text=NOTE_QUESTION)


def server_hello() -> ServerHello:
    """The ServerHello this server sends, filled from the versions it actually runs."""
    return ServerHello(
        type="server_hello",
        protocol_version=PROTOCOL_VERSION,
        ruleset_version=RULESET_VERSION,
        rng_algorithm=RNG_ALGORITHM,
    )


def update(table: Table, seat: Seat, now: int) -> Update:
    """What ``seat`` is sent at ``now`` (microseconds since the game started)."""
    timers: list[dict[str, object]] = []
    running = table.phase_deadline()
    if running is not None:
        timers.append({"name": running[0], "ms_left": max(0, running[1] - now) // 1000})
    turn = table.turn_deadline()
    if turn is not None:
        timers.append({"name": "turn", "ms_left": max(0, turn - now) // 1000})
    return Update.model_validate(
        {
            "type": "update",
            "view": view_to_data(table.view(seat)),
            "actions": sorted(encode(action) for action in table.actions(seat)),
            "pressable": list(table.pressable(seat)),
            "timers": timers,
            "bots": [s for s in SEATS if s not in table.people],
        },
        strict=False,
    )
