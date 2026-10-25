# fish-env

A [PettingZoo](https://pettingzoo.farama.org) AEC environment for **Fish**, a six-player team
card game of asking, deduction and calls, and the environment of the
[Fish benchmark](https://github.com/thetruthisntsweet/fish).

- Six agents, `seat_0` to `seat_5`, in two teams of three.
- Each agent observes only what its seat may know (its own hand, the public state and the
  most recent event) as 648 bits, with a mask over 913 actions.
- Declaration windows after every event, decided by a seeded priority order between teams.
- Deterministic: `reset(seed=...)` gives the same game every time, and every game can be saved
  as a record and replayed exactly.
- Passes PettingZoo's own API and seed tests.

```python
import numpy as np
from fish_env import env

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
```

Install with `pip install fish-env` (Python 3.14 or later). The rules engine is
[fish-rules](https://pypi.org/project/fish-rules/); baseline agents are in
[fish-agents](https://pypi.org/project/fish-agents/). The environment guide is in the
[repository](https://github.com/thetruthisntsweet/fish/blob/main/docs/environment.md).

Licensed under Apache-2.0.
