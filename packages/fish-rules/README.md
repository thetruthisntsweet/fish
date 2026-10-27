# fish-rules

The rules engine for **Fish**, a six-player team card game of asking, deduction and calls,
as specified by the Canonical Ruleset v1.1. It is the foundation of the
[Fish benchmark](https://github.com/thetruthisntsweet/fish).

- **Deterministic.** A game is its seed and its actions: replaying them gives the same states
  and records on any machine, with a frozen, documented random-number scheme.
- **Immutable.** `apply(state, action)` returns a new state and the records the action produced.
- **One projection.** `fish_rules.view.project` decides what each seat may see, and is the
  only way information reaches a player.
- **Standard library only**, typed, and tested to 100% branch coverage.

```python
from fish_rules.engine import apply, legal_actions
from fish_rules.state import new_game

state = new_game(42)
action = legal_actions(state, state.current)[0]
state, records = apply(state, action)
```

**Layer 1** (`fish_rules.deduce`) works out, exactly, which seats could hold each card given
everything one seat has seen and remembers. This plays part of a random game and prints the
cards seat 3 can place for certain:

```python
from fish_rules.cards import card_name
from fish_rules.deduce.tracker import Tracker
from fish_rules.engine import replay
from fish_rules.playout import random_game
from fish_rules.view import latest_event, project

tracker = Tracker(3)  # what seat 3 can work out, remembering everything it is shown
last = None
for state, records in replay(42, random_game(42, 7)[:150]):
    last = latest_event(records, last)
    deduction = tracker.observe(project(state, 3, last))

for card in range(54):
    seat = deduction.known(card)
    if seat is not None and seat != 3:
        print(card_name(card), "is with seat", seat)
```

Install with `pip install fish-rules` (Python 3.14 or later). For a multi-agent environment
built on it, see [fish-env](https://pypi.org/project/fish-env/); for baseline agents,
[fish-agents](https://pypi.org/project/fish-agents/). Documentation, including the
frozen encodings, is in the [repository](https://github.com/thetruthisntsweet/fish/tree/main/docs).

Licensed under Apache-2.0.
