# Fish

A benchmark for signalling under adversarial observation, built on the card game Fish.

**Status:** under construction. First public release planned for 1 November 2026.

- Rules: Canonical Ruleset v1.1
- Code licence: Apache-2.0
- Data licence (corpus): CC BY 4.0

## Quick start

The environment is a [PettingZoo](https://pettingzoo.farama.org) AEC environment with six
agents, `seat_0` to `seat_5`. Each agent observes only what its seat may know (its own hand,
the public state and the most recent event), with a mask of its legal actions. This plays one
game with random legal moves, then replays it from its record:

```python
import numpy as np

from fish_env import env
from fish_rules.record import replay_record

game = env()
game.reset(seed=42)
rng = np.random.default_rng(0)
for agent in game.agent_iter():
    observation, reward, terminated, truncated, info = game.last()
    if terminated or truncated:
        action = None
    else:
        action = int(rng.choice(np.flatnonzero(observation["action_mask"])))
    game.step(action)

record = game.unwrapped.record()
print("winner: team", record["winner"])
replay_record(record)  # the same game again, from the seed and the actions alone
```

See [the environment guide](docs/environment.md) for agents, actions, rewards and seeding.

## Documentation

- [Setup](docs/setup.md): get a working copy, everyday commands, troubleshooting
- [Environment](docs/environment.md): the multi-agent interface, its actions, rewards and seeding
- [Agents](docs/agents.md): the agent interface, B0, and the checks that run B0 games
- [Testing](docs/testing.md): what the tests check, where they run, and what to do when one
  fails
- [Corpus](docs/corpus.md): what every website game records, who is in the corpus, and what
  is released
- [Decision log](docs/decisions.md): what was chosen, and why
- [Determinism](docs/determinism.md): the random-number scheme behind every recorded game,
  and the frozen encodings of actions, records, views and observations
- [Restore drill](docs/runbooks/restore-drill.md): rehearsing a database restore on staging
