"""A stateful property test of the engine under website mechanics (T2.5).

The other whole-game tests play environment games: a window after every event, every seat
answering it, no timers. The website differs: a window opens only when someone presses Call
and closes after a second whoever has answered (R.8.3), and the assignment and the
after-call choice can time out (R.4.3, R.5.2). This Hypothesis state machine interleaves
all of those in any order the rules allow, plus arbitrary seat actions that may or may not be
legal, and after every step checks:

- the rule-level invariants (``check_consistency``) and R.9: the turn never falls to a player
  without cards, the current player can always act, someone can act or close the window;
- that the engine accepts a seat action exactly when its index is among that seat's legal
  indices, and that the legal indices are exactly the engine's legal actions, encoded;
- for every seat, that its view does not change when everything hidden from it does (other
  hands, sizes kept; the seed; other seats' window answers and votes), and that its
  observation is the view encoded (R.2);
- at the end, that the game's log replays exactly: its record, written to JSON text and read
  back, replays to the same records and the same state after every action.
"""

import json
from dataclasses import replace

from hypothesis import event, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,  # pyright: ignore[reportUnknownVariableType]
)

from fish_rules import observation
from fish_rules.action_index import NUM_ACTIONS, decode, encode, legal_indices
from fish_rules.cards import SEATS, Hand, Seat, team_seats
from fish_rules.codec import action_from_data
from fish_rules.engine import IllegalActionError, acting_seats, apply, legal_actions, replay
from fish_rules.events import (
    Action,
    AssignTimeout,
    CallEvent,
    ChoiceTimeout,
    CloseWindow,
    Event,
    OpenWindow,
    Record,
)
from fish_rules.record import game_record, replay_record
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase, State, check_consistency, new_game, state_hash
from fish_rules.view import latest_event, project

STEPS: int = 300
"""Actions per run: long enough to reach calls, choices, votes and often the end."""

RUNS: int = max(10, int(settings().max_examples) // 20)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Runs of the machine: a twentieth of the profile's examples (10 in dev, 50 in CI, 2,500
nightly), since every step checks every seat."""


def scramble(state: State, seat: Seat, rng: SplitMix64) -> State:
    """``state`` with everything hidden from ``seat`` changed: the other seats' cards dealt
    again among them with sizes kept, a new seed, other seats' window answers and votes."""
    others = [s for s in SEATS if s != seat]
    pool = rng.shuffled(card for s in others for card in state.hands[s])
    hands: list[Hand] = list(state.hands)
    for s in others:
        size = len(state.hands[s])
        hands[s], pool = tuple(sorted(pool[:size])), pool[size:]
    scrambled = replace(state, hands=tuple(hands), seed=rng.next_u64())
    if state.window is not None:
        in_play = state.sets_in_play()
        declared = tuple(
            d if s == seat else rng.choice((None, *in_play))
            for s, d in zip(SEATS, state.window.declared, strict=True)
        )
        responded = tuple(
            r if s == seat else rng.below(2) == 1
            for s, r in zip(SEATS, state.window.responded, strict=True)
        )
        scrambled = replace(
            scrambled, window=replace(state.window, declared=declared, responded=responded)
        )
    if state.choice is not None:
        members = team_seats(state.choice.team)
        votes = tuple(
            v if s == seat else rng.choice((None, *state.choice.candidates))
            for s, v in zip(members, state.choice.votes, strict=True)
        )
        scrambled = replace(scrambled, choice=replace(state.choice, votes=votes))  # pyright: ignore[reportArgumentType]
    return scrambled


class WebsiteGame(RuleBasedStateMachine):
    """One game under website mechanics, driven by Hypothesis."""

    def __init__(self) -> None:
        super().__init__()
        self.seed = 0
        self.state = new_game(0)
        self.last: Event | None = None
        self.actions: list[Action] = []
        self.steps: list[tuple[str, tuple[Record, ...]]] = []
        self.rng = SplitMix64(0)
        self.timed_out_calls = 0

    @initialize(seed=st.integers(min_value=0, max_value=2**64 - 1))
    def deal(self, seed: int) -> None:
        self.seed = seed
        self.state = new_game(seed)
        self.rng = SplitMix64(seed)

    def play(self, action: Action) -> None:
        self.state, records = apply(self.state, action)
        self.actions.append(action)
        self.steps.append((state_hash(self.state), records))
        self.last = latest_event(records, self.last)
        self.timed_out_calls += sum(
            isinstance(r, CallEvent) and r.assignment is None for r in records
        )

    # ------------------------------------------------------------ website control actions

    @precondition(lambda self: self.state.phase is Phase.TURN)
    @rule()
    def press_call(self) -> None:
        """R.8.3: a press opens a window; only then can anyone declare."""
        self.play(OpenWindow())

    @precondition(lambda self: self.state.phase is Phase.WINDOW)
    @rule()
    def window_ends(self) -> None:
        """R.8.3: the window closes after a second, whoever has answered."""
        self.play(CloseWindow())

    @precondition(lambda self: self.state.phase is Phase.ASSIGN)
    @rule()
    def assignment_times_out(self) -> None:
        """R.4.3: a caller who does not assign in time has made an incorrect call."""
        self.play(AssignTimeout())

    @precondition(lambda self: self.state.phase in (Phase.CHOOSE, Phase.VOTE))
    @rule()
    def choice_times_out(self) -> None:
        """R.5.2: the seed chooses if the caller does not; uncast votes are ignored."""
        self.play(ChoiceTimeout())

    # ------------------------------------------------------------ seat actions

    @precondition(lambda self: bool(acting_seats(self.state)))
    @rule(data=st.data())
    def a_seat_acts(self, data: st.DataObject) -> None:
        """A seat that may act takes one of its legal actions."""
        seat = data.draw(st.sampled_from(acting_seats(self.state)), label="seat")
        index = data.draw(st.sampled_from(legal_indices(self.state, seat)), label="index")
        self.play(decode(seat, index, self.state.phase))

    @rule(seat=st.sampled_from(SEATS), index=st.integers(min_value=0, max_value=NUM_ACTIONS - 1))
    def any_seat_tries_any_action(self, seat: Seat, index: int) -> None:
        """R.3.2, R.4.6, R.8.7: the engine accepts a seat action exactly when it is legal; an
        illegal one is rejected and changes nothing."""
        before = self.state
        action = decode(seat, index, before.phase)
        legal = index in legal_indices(before, seat)
        try:
            self.play(action)
        except IllegalActionError:
            assert not legal, f"rejected a legal action {action}"
            assert self.state is before
        else:
            assert legal, f"accepted an illegal action {action}"

    # ------------------------------------------------------------ after every step

    @invariant()
    def r9_consistency(self) -> None:
        """R.9: cards conserved, phase and pending state agree, the turn is never with a player
        without cards, the current player can always act, and the game never stalls."""
        state = self.state
        check_consistency(state)
        if state.phase in (Phase.TURN, Phase.RUNOUT):
            assert state.current is not None
            assert legal_actions(state, state.current)
        if state.phase is Phase.TURN:
            assert state.current is not None
            assert state.hands[state.current], "R.9: the turn fell to a player without cards"
        if state.phase not in (Phase.OVER, Phase.WINDOW):
            assert acting_seats(state), "someone must be able to act"

    @invariant()
    def legal_indices_are_the_legal_actions(self) -> None:
        for seat in SEATS:
            reference = tuple(sorted(encode(a) for a in legal_actions(self.state, seat)))
            assert legal_indices(self.state, seat) == reference

    @invariant()
    def r2_1_views_depend_only_on_what_a_seat_may_know(self) -> None:
        """R.2.1, R.4.3, R.5.2: no seat's view moves when what is hidden from it does; its
        observation is its view, encoded."""
        for seat in SEATS:
            view = project(self.state, seat, self.last)
            assert project(scramble(self.state, seat, self.rng), seat, self.last) == view
            assert len(observation.encode(view)) == observation.OBS_SIZE

    def teardown(self) -> None:
        """R.10.2: the game is its log. Its record, as JSON text and back, replays to the same
        records and the same state after every action, and ``replay_record`` accepts it."""
        data = json.loads(json.dumps(game_record(self.seed, self.actions, self.state)))
        actions = [action_from_data(item) for item in data["actions"]]
        replayed = [(state_hash(s), r) for s, r in replay(int(data["seed"]), actions)]
        assert replayed == self.steps
        assert state_hash(replay_record(data)) == state_hash(self.state)
        event(f"ended in phase {self.state.phase}")
        event(f"timed-out calls: {min(self.timed_out_calls, 2)}")
        event(f"events: {min(self.state.events // 10 * 10, 50)}+")


def test_r8_3_the_engine_under_website_mechanics() -> None:
    """R.4.3, R.5.2, R.8.3, R.9: random interleavings of Call presses, partial windows, seat
    actions legal and illegal, and timeouts keep every invariant."""
    run_state_machine_as_test(
        WebsiteGame, settings=settings(max_examples=RUNS, stateful_step_count=STEPS, deadline=None)
    )
