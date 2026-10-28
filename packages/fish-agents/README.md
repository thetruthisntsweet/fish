# fish-agents

Baseline agents for **Fish**, a six-player team card game of asking, deduction and calls, and
the interface they share, from the [Fish benchmark](https://github.com/thetruthisntsweet/fish).

- `Agent`: an agent is any object with `act(view, rng) -> int`. It sees only its own seat's
  view and draws its randomness from the generator it is given, so games replay exactly.
- `B0` (`b0-v1`): plays uniformly at random among its legal actions, except that in a
  declaration window it passes all but 1 time in 100.
- `play_game(agents, seed)` plays one game with six agents and returns its record (needs the
  `env` extra).
- Memory: `Remembering(agent, setting)` gives an agent with `act(view, memory, rng)` full,
  last-k or no memory of the events it has been shown, and exactly what it can deduce from
  them.

```python
from fish_agents.b0 import B0
from fish_agents.play import play_game

record = play_game([B0()] * 6, 42)
print("winner: team", record["winner"])
```

An agent with memory: it asks for a card whenever what it remembers proves the target holds
it, and otherwise plays as B0. With full memory it beats three B0s more often than not:

```python
from fish_agents.b0 import B0
from fish_agents.memory import FULL, Memory, Remembering
from fish_agents.play import play_game
from fish_rules.action_index import decode
from fish_rules.events import Ask
from fish_rules.rng import SplitMix64
from fish_rules.view import PlayerView


class Sure:
    """Asks for a card whenever Layer 1 says the target certainly holds it; otherwise B0."""

    def act(self, view: PlayerView, memory: Memory, rng: SplitMix64) -> int:
        for index in view.legal:
            action = decode(view.seat, index, view.phase)
            if isinstance(action, Ask) and memory.deduction.known(action.card) == action.target:
                return index
        return B0().act(view, rng)


games = [play_game([Remembering(Sure(), FULL)] * 3 + [B0()] * 3, seed) for seed in range(20)]
print("Sure won", sum(game["winner"] == 0 for game in games), "of 20 games against B0")
```

Install with `pip install "fish-agents[env]"` (Python 3.14 or later), or `pip install
fish-agents` for the interface and agents alone. Stronger baselines (B1 to B3) come in later
releases. Documentation is in the
[repository](https://github.com/thetruthisntsweet/fish/blob/main/docs/agents.md).

Licensed under Apache-2.0.
