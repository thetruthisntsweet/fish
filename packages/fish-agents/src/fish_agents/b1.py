"""B1, the exact-inference agent (T5.2).

B1 acts only on what it can prove, and where it must guess it weighs what is possible
equally. Every decision reads Layer 1's exact deduction (``fish_rules.deduce``) from what B1
remembers (``fish_agents.memory``):

- **Calling.** It calls a set, in any window or on its turn, exactly when it knows where all
  six cards are and all six are with its team (``certain_calls``). Layer 1 never rules out
  the truth, so a call B1 chooses is never wrong, at any memory setting.
- **Asking.** It makes an ask certain to succeed if there is one; otherwise the ask likeliest
  to succeed, each card's possible holders weighted equally (the floor model of RQ1). It never
  makes an ask certain to miss while another is legal.
- **The after-call choice and the vote.** The teammate with the most asks B1 can tell are
  certain to succeed, then the one with the most cards.
- **Forced calls** (run-out, R.6.2, or assigning a call it did not choose): the set with the
  most cards whose holder on the team it knows; each card it does not know is assigned as one
  deal that fits everything it has seen has it (Layer 1's example deal).

Ties are broken by the generator it is given, and only ties: with one best option nothing is
drawn. Options are always considered in ascending action-index order, so a B1 game is
reproduced from its seed (``fish_agents.play``).

This module needs only fish-rules, so the server can run B1 as its bot (T3.5).
"""

from collections.abc import Iterable, Sequence
from fractions import Fraction
from typing import Final

from fish_agents.memory import Memory
from fish_rules.action_index import (
    CALL_BASE,
    DECLARE_BASE,
    NOMINATE_BASE,
    PASS_INDEX,
    decode,
    encode,
    teammates,
)
from fish_rules.cards import SETS, Card, Seat, SetId, set_cards, team_of
from fish_rules.deduce.solve import Deduction
from fish_rules.events import Ask, Assign
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase
from fish_rules.view import PlayerView

NEVER: Final = Fraction(0)


class IllegalChoiceError(Exception):
    """B1 chose an action that is not legal: a bug in B1, never a game situation."""


def _pick[T](options: Sequence[T], rng: SplitMix64) -> T:
    """The one option, or a uniformly random one of several."""
    if not options:
        raise IllegalChoiceError("nothing to choose from")
    return options[0] if len(options) == 1 else options[rng.below(len(options))]


def _best[T, S: (Fraction, int, tuple[int, int])](scored: Iterable[tuple[T, S]]) -> list[T]:
    """The options with the highest score, in the order given."""
    options = list(scored)
    top = max(score for _, score in options)
    return [option for option, score in options if score == top]


# ---------------------------------------------------------------- what B1 knows


def certain_calls(seat: Seat, deduction: Deduction, scored_by: Sequence[object]) -> list[SetId]:
    """The sets still in play whose six cards ``seat`` knows are all with its own team."""
    team = team_of(seat)
    found: list[SetId] = []
    for set_id in SETS:
        if scored_by[set_id] is not None:
            continue
        holders = [deduction.known(card) for card in set_cards(set_id)]
        if all(h is not None and team_of(h) == team for h in holders):
            found.append(set_id)
    return found


def hit_chance(deduction: Deduction, target: Seat, card: Card) -> Fraction:
    """How likely asking ``target`` for ``card`` is to succeed, each of the card's possible
    holders weighted equally: 1 if ``target`` is known to hold it, 0 if it cannot."""
    possible = deduction.possible(card)
    return Fraction(1, len(possible)) if target in possible else NEVER


def certain_asks(seat: Seat, deduction: Deduction, hand_sizes: Sequence[int]) -> int:
    """How many asks ``seat`` could make that ``deduction`` shows are certain to succeed: a
    card known to be with an opponent who holds cards, in a set ``seat`` is known to hold a
    card of (R.3.2)."""
    team = team_of(seat)
    count = 0
    for set_id in SETS:
        holders = [deduction.known(card) for card in set_cards(set_id)]
        if seat not in holders:
            continue
        for holder in holders:
            if holder is not None and team_of(holder) != team and hand_sizes[holder] > 0:
                count += 1
    return count


def assignment(seat: Seat, set_id: SetId, deduction: Deduction) -> tuple[Seat, ...]:
    """The holders B1 assigns to the cards of ``set_id``: the known holder where there is one
    on the team; otherwise the holder in Layer 1's example deal, if a teammate; otherwise the
    first teammate who may hold it, or B1 itself if none may (the call is then lost anyway)."""
    team = team_of(seat)
    in_example = {card: s for s, hand in enumerate(deduction.example_now()) for card in hand}
    holders: list[Seat] = []
    for card in set_cards(set_id):
        known = deduction.known(card)
        guess = in_example.get(card)
        mates = [s for s in deduction.possible(card) if team_of(s) == team]
        if known is not None and team_of(known) == team:
            holders.append(known)
        elif guess is not None and team_of(guess) == team:
            holders.append(guess)
        else:
            holders.append(mates[0] if mates else seat)
    return tuple(holders)


def known_on_team(seat: Seat, set_id: SetId, deduction: Deduction) -> int:
    """How many of ``set_id``'s cards ``seat`` knows are with its own team."""
    team = team_of(seat)
    holders = (deduction.known(card) for card in set_cards(set_id))
    return sum(1 for h in holders if h is not None and team_of(h) == team)


# ---------------------------------------------------------------- deciding


def decide(view: PlayerView, deduction: Deduction, rng: SplitMix64) -> int:
    """B1's action, as an index in ``view.legal``, given the seat's deduction."""
    legal = frozenset(view.legal)
    chosen = _decision(view, deduction, rng, legal)
    if chosen not in legal:
        raise IllegalChoiceError(f"B1 chose {chosen} in {view.phase}, which is not legal")
    return chosen


def _decision(
    view: PlayerView, deduction: Deduction, rng: SplitMix64, legal: frozenset[int]
) -> int:
    seat = view.seat
    match view.phase:
        case Phase.WINDOW:
            sets = certain_calls(seat, deduction, view.scored_by)
            options = [DECLARE_BASE + s for s in sets if DECLARE_BASE + s in legal]
            return _pick(options, rng) if options else PASS_INDEX
        case Phase.TURN:
            sets = certain_calls(seat, deduction, view.scored_by)
            calls = [CALL_BASE + s for s in sets if CALL_BASE + s in legal]
            if calls:
                return _pick(calls, rng)
            asks = sorted(i for i in legal if i < CALL_BASE)
            if asks:
                return _pick(_best((i, _chance(seat, i, deduction)) for i in asks), rng)
            return _forced_call(seat, deduction, rng, legal)
        case Phase.RUNOUT:
            return _forced_call(seat, deduction, rng, legal)
        case Phase.ASSIGN:
            if view.call is None or view.call.caller != seat:
                raise IllegalChoiceError("asked to assign a call that is not this seat's")
            return encode(Assign(seat, assignment(seat, view.call.set_id, deduction)))
        case Phase.CHOOSE | Phase.VOTE:
            mates = teammates(seat)
            nominations = sorted(i for i in legal if i >= NOMINATE_BASE)
            return _pick(
                _best(
                    (i, _nominee(mates[i - NOMINATE_BASE], deduction, view)) for i in nominations
                ),
                rng,
            )
        case _:
            raise IllegalChoiceError(f"B1 has no decision to make in {view.phase}")


def _chance(seat: Seat, index: int, deduction: Deduction) -> Fraction:
    ask = decode(seat, index, Phase.TURN)
    assert isinstance(ask, Ask)
    return hit_chance(deduction, ask.target, ask.card)


def _nominee(mate: Seat, deduction: Deduction, view: PlayerView) -> tuple[int, int]:
    """A teammate's claim to the turn: certain asks first, then cards in hand."""
    return certain_asks(mate, deduction, view.hand_sizes), view.hand_sizes[mate]


def _forced_call(seat: Seat, deduction: Deduction, rng: SplitMix64, legal: frozenset[int]) -> int:
    """A call that has to be made: the set with the most cards known to be with the team."""
    calls = sorted(i for i in legal if CALL_BASE <= i < DECLARE_BASE)
    return _pick(_best((i, known_on_team(seat, i - CALL_BASE, deduction)) for i in calls), rng)


# ---------------------------------------------------------------- the agent


class B1:
    """The exact-inference agent, a ``fish_agents.memory.MemoryAgent``: give it memory with
    ``Remembering(B1(), setting)``. It holds no state of its own, so one instance can play
    every seat."""

    def act(self, view: PlayerView, memory: Memory, rng: SplitMix64) -> int:
        """B1's action, from what this seat sees and remembers."""
        return decide(view, memory.deduction, rng)
