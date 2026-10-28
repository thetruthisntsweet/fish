# Agent memory

Every seat is shown every event as it happens, but a view holds only the most recent one
(R.2.2, R.2.5). What a player remembers of earlier events is up to the player. For people
that is "human memory", recorded as such in the corpus. For agents it is a setting, chosen
per agent (T2.8):

| Setting | Remembers | In the corpus |
|---|---|---|
| full | every event it has been shown | `memory: "full"`, `k: null` |
| last-k | the latest k events | `memory: "last-k"`, `k: k` |
| none | nothing beyond the current view | `memory: "none"`, `k: null` |

Memory belongs to the agent, not the game (Plan §3): the rules engine and the projection are
the same under every setting, and games replay the same whatever the agents remembered.

## What k counts

**k counts events**, not views. A seat is shown the same event in many views: the window
after it, the turn, a call's assignment. How many depends on the platform. The environment
asks every seat in every window, while the website opens a window only when someone presses
Call (R.8.9). Counted in views, last-8 would mean less memory in benchmark games than in
corpus games. Counted in events, it means the latest eight asks, calls and after-call choices
on both. This is what the corpus's `k` records (D57).

## For agents (`fish_agents.memory`)

An agent with memory is given its seat's memory as well as its view:

```python
from fish_agents.b0 import B0
from fish_agents.memory import FULL, Memory, MemorySetting, Remembering


class Mine:
    def act(self, view, memory: Memory, rng) -> int:
        memory.events  # the remembered events, oldest first
        memory.views  # for each, the view that first showed it
        memory.deduction  # Layer 1 from exactly what is remembered (docs/deduction.md)
        return B0().act(view, rng)


agent = Remembering(Mine(), MemorySetting.last_k(8))  # or FULL, or NONE
```

`Remembering` turns it into an ordinary agent for `play_game`, keeping a separate `Memory`
for each seat it plays. It is also an `Observer`: `play_game` shows it its seat's view after
every action, whoever acted, so it sees every event as a player at the table would. The
server's bots will be shown views the same way (T3.5). Being shown views draws nothing from
the game's random generators, so an agent that ignores its memory plays the same game under
every setting.

Like Layer 1, memory keeps an unbroken run of events. If a view's event is not the one after
the last remembered (the agent was not shown every view), the run starts again from it. The
deduction is worked out only when asked for, so following every view is cheap.

`MemorySetting.as_corpus()` and `MemorySetting.from_corpus(memory, k)` convert to and from
the corpus's seat fields.

## For training (`fish_env.memory`)

`memory_env(remembered)` is `fish_env.env()` with each agent's memory in its `infos` entry
under `"memory"`. For every remembered event, it holds the observation the agent had just
after it, as `fish-obs-v1` bits: an `int8` array of shape `(n, 648)`, oldest first.

```python
from fish_env import memory_env

game = memory_env(remembered=8)  # None keeps every event, 0 none
game.reset(seed=42)
for agent in game.agent_iter():
    observation, reward, terminated, truncated, info = game.last()
    past = info["memory"]  # shape (n, 648), n <= 8
    ...
```

The observation and action spaces are the plain environment's, so a policy written for
`fish_env.env()` runs unchanged. `MemoryWrapper(game, remembered)` wraps an environment you
have already wrapped yourself.

## How it is checked

- **Settings.** Every setting converts to the corpus's fields and back, and anything that is
  not a setting is refused (`test_memory.py`).
- **One seat's memory.** Over random games, `Memory` remembers exactly the events Layer 1's
  tracker does and gives the same deduction, including when views are missed
  (`test_memory.py`).
- **Agents.** At every decision of random games, each seat's memory under its own random
  setting holds exactly the latest events it may keep, with no gap. An agent that ignores its
  memory plays B0's game exactly (`test_memory_agents.py`).
- **Training.** PettingZoo's API and seed tests pass under every setting. The same random
  games, played wrapped and plain, show the same observations, and every agent's memory at
  every step is the plain environment's observations just after the events it keeps
  (`test_memory_env.py`). The wrapper and `Memory` remember the same thing
  (`test_memory_env_agrees.py`).
