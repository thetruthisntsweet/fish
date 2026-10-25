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

Install with `pip install fish-rules` (Python 3.14 or later). For a multi-agent environment
built on it, see [fish-env](https://pypi.org/project/fish-env/); for baseline agents,
[fish-agents](https://pypi.org/project/fish-agents/). Documentation, including the
frozen encodings, is in the [repository](https://github.com/thetruthisntsweet/fish/tree/main/docs).

Licensed under Apache-2.0.
