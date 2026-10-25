# fish-agents

Baseline agents for **Fish**, a six-player team card game of asking, deduction and calls, and
the interface they share, from the [Fish benchmark](https://github.com/thetruthisntsweet/fish).

- `Agent`: an agent is any object with `act(view, rng) -> int`. It sees only its own seat's
  view and draws its randomness from the generator it is given, so games replay exactly.
- `B0` (`b0-v1`): plays uniformly at random among its legal actions, except that in a
  declaration window it passes all but 1 time in 100.
- `play_game(agents, seed)` plays one game with six agents and returns its record (needs the
  `env` extra).

```python
from fish_agents.b0 import B0
from fish_agents.play import play_game

record = play_game([B0()] * 6, 42)
print("winner: team", record["winner"])
```

Install with `pip install "fish-agents[env]"` (Python 3.14 or later), or `pip install
fish-agents` for the interface and agents alone. Stronger baselines (B1 to B3) come in later
releases. Documentation is in the
[repository](https://github.com/thetruthisntsweet/fish/blob/main/docs/agents.md).

Licensed under Apache-2.0.
