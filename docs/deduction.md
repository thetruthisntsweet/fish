# Layer 1: where each card can be

Layer 1 (T2.7) answers one question for any seat at any moment: given everything this seat
has seen and remembers, which seats could hold each card? It answers exactly. A seat is named
for a card if and only if some deal fits everything the seat has seen with the card there. It
lives in `fish_rules.deduce`, so the environment, the agents, the server's bots and the
analysis all use the same code (Implementation Environment §5).

Later work builds on it:

| Uses it | For |
|---|---|
| B1 (T5.2) | its policy acts on exact deduction |
| B2's sampler (T5.3) | it samples only deals Layer 1 allows, starting from Layer 1's example deal |
| B3 (T5.5) | its belief is masked by Layer 1, so it puts no weight on impossible places |
| RQ1 (T6.4) | "Layer 1 only", possible holders equally weighted, is the floor model |
| RQ2 (T6.5) | certain-miss asks are found exactly, and leakage's alternative hands come from the public view |
| T6.7 | B1 and B2 at full, last-k and no memory |

## Using it

```python
from fish_rules.deduce.solve import deduce

deduction = deduce(view, events)  # a seat's view, and the events it remembers
deduction.possible(card)  # the seats that may hold the card now, e.g. (1, 4)
deduction.known(card)  # the one seat, if only one is possible; else None
deduction.example_now()  # one full set of hands that fits everything seen
```

`events` is the unbroken run of events the seat remembers, ending at `view.last_event`: all
of them for perfect memory, the last k for a last-k memory, or none. `deduce(view, events,
use_hand=False)` gives the public view, which uses no one's hand: the deals anyone watching
could consider.

An agent passes its views to a tracker, which remembers each event once (the same event is
shown in many views), keeps only the last k if asked, and gives back the same deduction when
nothing it uses has changed:

```python
from fish_rules.deduce.tracker import Tracker

tracker = Tracker(seat, remembered=None)  # None: everything; k: the last k events
deduction = tracker.observe(view)  # after every view
```

If a view's event is not the one after the last remembered (the agent was not shown every
view), the tracker starts a new run from it.

For a recorded game (a record or a corpus game: its seed and its actions):

```python
from fish_rules.deduce.games import certain_misses, knowledge
from fish_rules.state import new_game

for deduction in knowledge(new_game(seed), actions, seat):  # seat=None for the public view
    ...  # at the deal, then after every event: where beliefs are scored (T1.1 §1)

certain_misses(new_game(seed), actions)  # asks the asker could know would miss
certain_misses(new_game(seed), actions, remembered=0)  # ... from what was on screen alone
```

`fish_rules.deduce.solve.example_deal(deduction.constraints, {card: seat})` finds a deal that
fits with chosen cards fixed to chosen seats, or returns None if there is none.

## How it works

**Cards only move in public.** A successful ask shows which card went from whom to whom, and
a call reveals the holder of each of its six cards before they leave play (R.2.3, R.3.3). So
a card that has not moved since some moment is still with whoever held it then. Every fact a
seat remembers therefore constrains a single unknown: the deal just before the first
remembered event (the *anchor*). With the whole game remembered, the anchor is the deal
itself. With a shorter memory, the anchor's hand sizes and the seat's own hand then are
worked back from the current view through the remembered events.

**The facts** (`fish_rules.deduce.history`):

| Fact | Constraint on the anchor |
|---|---|
| An ask for a card | the asker did not hold it (R.3.2) |
| An ask | the asker held another card of that set (R.3.2) |
| A successful ask | the target held the card (R.3.3) |
| A failed ask | the target did not hold it (R.3.3) |
| A call | each of its six cards was with the revealed holder (R.2.3) |
| The view now | the hand sizes, the scored sets, and the seat's own hand (R.2.1, R.2.2) |

Nothing else depends on where cards are. Windows, declarations, passes and the after-call
choice depend only on hand sizes, which are public.

The "held another card of the set" fact is about the set's cards that have not moved. Those
cards only ever leave that pool, so a later ask by the same seat in the same set gives a
subset of the earlier constraint and implies it, and only the latest is kept. If the seat
is known to hold a card of the set when it asks, the ask adds nothing.

**The solver** (`fish_rules.deduce.solve`). A deal fits when each card is with a seat it may
be with, each seat holds exactly its hand size, and each "held one of these" constraint holds.
That is a flow problem: cards flow from a source to seats, each card exactly once, each seat
exactly its hand size. A card in a "held one of these" constraint for a seat passes through a
node for that constraint, which must carry at least one card. A seat's constraints are in
different sets, so no card passes through two. The flows that meet these bounds are exactly
the deals that fit, and one is found with the standard reduction of lower bounds to a
maximum flow.

From that one flow, every other deal that fits differs by cycles in the flow's residual
graph. So a card can be with a seat if and only if the flow already puts it there, or the two
ends of that edge are in the same strongly connected component. One maximum flow and one
pass over the components give every possible holder of every card at once, with no search.

**Speed.** About 1 ms per deduction with full memory (the performance smoke reports the mean
and the 99th percentile on every CI run), so B1 can deduce at every decision.

## Why it is exact, and how that is checked

There are two ways to be wrong. Naming a seat that cannot hold the card means a fact was
read too weakly. Leaving out a seat that can means a fact was read too strongly, or one was
invented. The tests check both, for every seat, the public view and random memories:

- **Nothing possible is ruled out** (`test_deduce_history.py`, `test_deduce_solve.py`). At
  every event of random games, the true deal satisfies every constraint and every card's true
  holder is named. A fact read too strongly would, somewhere, rule out the truth.
- **Nothing impossible is named** (`test_deduce_solve.py`). Deals that put a card with a named
  seat other than its true one are played forward with the game's own actions in the engine.
  Every action is still legal, every public record is the same, and the seat's view is the
  same after every action. This check does not rely on the list of facts above, so a way of
  learning about cards that the list missed would fail it.
- **The fast answer is right** (`test_deduce_solve.py`). For sampled cards, forcing the card to
  each seat in turn finds a deal exactly when the solver named that seat.
- **On B0's play, at scale** (nightly). `scripts/soak_deduce.py` does the same at every event
  of 3,000 B0 games (`docs/testing.md`).

Before it was trusted, the exactness test was run against four deliberately broken
versions: dropping "the asker did not hold the card", dropping "a failed ask means the target
did not hold it", ignoring "held another card of the set", and skipping the component step.
It caught each one.

## Limits

- **Memory is a run of events.** Only an unbroken run of events, ending at the most recent,
  says where cards are. A seat that remembers a scattered handful of events is treated as
  remembering the run since its last gap.
- **Facts only, not behaviour.** Layer 1 uses only what the rules force. Anything a seat might
  infer from how others play (why that ask, why so slowly) is not a constraint: that
  difference is what RQ1 measures.
