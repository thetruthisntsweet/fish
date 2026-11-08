"""Leak tests on the wire (T3.7; docs/leaks.md). The projection's own tests (fish_rules,
``test_view_leaks.py``) show that a view depends only on what its seat may know. These show
the same for everything else the server sends a seat, over whole random games played through
``Game``, with people coming and going and bots in their seats:

- at every step, every seat's whole update (its view, actions, pressable sets, timers and
  bots) is unchanged when everything hidden from that seat is scrambled: the other hands (their
  sizes kept), the seed, other seats' window answers and votes (the projection tests' own
  scramble), and who else is connected or away;
- a rejection goes only to the seat whose input it rejects, and nothing else is sent in reply
  to an input but updates;
- a ping goes only to its own seat, numbered 1, 2, 3 for that seat.

With subtask 2's rule (``test_game.py``: an update is sent only when what it shows changes),
the first means that whether a seat is sent an update depends only on what it may know too:
its last update and its next are both functions of that.
"""

import copy
import importlib.util
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import SEATS
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase
from fish_server.game import Connected, Event, Game, Out, Release, Send
from fish_server.protocol import Ping, Rejected, Update, update
from fish_server.table import Table

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every step of whole games: a fortieth of the profile's examples (10 in dev,
25 in CI, 1,250 nightly)."""


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VIEW_LEAKS = _load(Path(__file__).parents[2] / "fish-rules/tests/test_view_leaks.py", "view_leaks")
"""For ``scramble``: everything a state hides from a seat, changed at random."""

GAME_TESTS = _load(Path(__file__).with_name("test_game.py"), "game_tests")
"""For ``play``: random inputs from the people, the clock moving on, until the game ends."""


def hidden_from(table: Table, seat: int, rng: SplitMix64) -> Table:
    """A copy of ``table`` with everything hidden from ``seat`` changed: the state, scrambled
    as the projection's leak tests do, and which other seats are connected or away."""
    other = copy.copy(table)
    other.state = VIEW_LEAKS.scramble(table.state, seat, rng)
    private: Any = other  # the table's own bookkeeping, not part of its interface
    others = [s for s in SEATS if s != seat]
    private._connected = {s for s in table._connected if s == seat} | {  # pyright: ignore[reportPrivateUsage]
        s for s in others if rng.below(2)
    }
    private._away = {s: t for s, t in table._away.items() if s == seat} | {  # pyright: ignore[reportPrivateUsage]
        s: rng.below(10**8) for s in others if rng.below(2)
    }
    return other


class Watched:
    """Wraps a game's ``handle`` and ``wake``: after each, checks every seat's update against
    a scrambled copy of the table, and checks who each message went to."""

    def __init__(self, game: Game, rng: SplitMix64) -> None:
        self.game, self.rng = game, rng
        self.handle, self.wake = game.handle, game.wake
        self.phases: set[Phase] = set()
        self.compared = 0
        self.away_seen = False
        self.nonces: dict[int, list[int]] = {}
        game.handle = self.handled  # pyright: ignore[reportAttributeAccessIssue]
        game.wake = self.woken  # pyright: ignore[reportAttributeAccessIssue]

    def handled(self, event: Event, now: int) -> list[Out]:
        outs = self.handle(event, now)
        for out in outs:
            if isinstance(out, Send):
                assert isinstance(out.message, Update | Rejected), out  # nothing else answers
                if isinstance(out.message, Rejected):
                    assert out.seat == event.seat, "a rejection reached another seat"
        self.check(now, outs)
        return outs

    def woken(self, now: int) -> list[Out]:
        outs = self.wake(now)
        for out in outs:
            if isinstance(out, Send):
                assert not isinstance(out.message, Rejected), "a rejection with no input"
                if isinstance(out.message, Ping):
                    self.nonces.setdefault(out.seat, []).append(out.message.nonce)
        self.check(now, outs)
        return outs

    def check(self, now: int, outs: list[Out]) -> None:
        table = self.game.table
        self.phases.add(table.state.phase)
        self.away_seen |= any(table.connected(s) != (s in table.people) for s in SEATS)
        for out in outs:
            if isinstance(out, Send) and isinstance(out.message, Update):
                assert out.message == update(table, out.seat, now)  # what is checked is sent
        released = {out.seat for out in outs if isinstance(out, Release)}
        for seat in SEATS:
            if seat in released or self.game.ended:
                continue
            sent = update(table, seat, now)
            assert update(hidden_from(table, seat, self.rng), seat, now) == sent, (
                f"seat {seat}'s update changed with what is hidden from it"
            )
            self.compared += 1


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_update_depends_only_on_what_its_seat_may_know(game_seed: int, rng_seed: int) -> None:
    game = Game(uuid.uuid4(), game_seed, [uuid.uuid4() for _ in SEATS])
    watched = Watched(game, SplitMix64(rng_seed ^ 0x5EED))
    for seat in SEATS:
        game.handle(Connected(seat), 0)
    GAME_TESTS.play(SplitMix64(rng_seed), game, 400)
    assert game.ended
    assert watched.compared > 0
    assert Phase.TURN in watched.phases
    for seat, nonces in watched.nonces.items():
        assert nonces == list(range(1, len(nonces) + 1)), f"seat {seat}'s pings: {nonces}"


def test_the_games_reach_every_phase_and_people_go_away() -> None:
    """The property above is only as good as the games it sees: across the seeds a run uses,
    they reach windows, assignments, choices and votes, and people away from their seats."""
    phases: set[Phase] = set()
    away = False
    for seed in range(12):
        game = Game(uuid.uuid4(), seed, [uuid.uuid4() for _ in SEATS])
        watched = Watched(game, SplitMix64(seed))
        for seat in SEATS:
            game.handle(Connected(seat), 0)
        GAME_TESTS.play(SplitMix64(seed), game, 400)
        phases |= watched.phases
        away |= watched.away_seen
    assert {Phase.TURN, Phase.WINDOW, Phase.ASSIGN, Phase.OVER} <= phases
    assert phases & {Phase.CHOOSE, Phase.VOTE}
    assert away


def test_the_check_would_catch_an_update_that_reads_a_hidden_hand() -> None:
    """The scrambled copy really changes what is hidden: an update that also said how many
    hearts another seat holds would differ on it."""
    game = Game(uuid.uuid4(), 3, [uuid.uuid4() for _ in SEATS])
    rng = SplitMix64(1)
    table = game.table
    changed = sum(
        hidden_from(table, 0, rng).state.hands[1] != table.state.hands[1] for _ in range(20)
    )
    assert changed >= 15
    assert hidden_from(table, 0, rng).state.hands[0] == table.state.hands[0]  # its own stays
