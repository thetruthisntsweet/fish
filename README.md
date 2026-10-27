# Fish

A benchmark for signalling under adversarial observation, built on the card game Fish.

Fish (also known as Literature) is a six-player team card game of hidden information. Each
player sees only their own hand; on your turn you ask an opponent for a card, and to score a
set you must say exactly which teammate holds each of its six cards. Every ask therefore tells
the table something, about what you hold and what you are after, to teammates and opponents
alike. This project measures how much: how much the way people play reveals about hidden
cards beyond what the rules alone allow, how much players leak about their own hands, and
whether any of it is deliberate signalling.

**Version 0.1.0**, the first public release: the rules engine, a multi-agent environment and
a random baseline. See [what's next](#whats-next).

## Install

```bash
pip install "fish-agents[env]"    # the environment, the agents and the rules engine
```

Python 3.14 or later. `pip install fish-env` installs the environment and the rules alone,
and `pip install fish-rules` only the rules engine, which has no dependencies.

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

More in [`examples/`](examples/README.md): writing your own agent and playing it against the
baseline, inspecting a recorded game, and the shape of a training loop.

## What's in it

| Package | What it is |
|---|---|
| [fish-rules](https://pypi.org/project/fish-rules/) | The rules engine: [Canonical Ruleset v1.1](docs/rules.md), immutable states, seeded and exactly replayable games, the projection that decides what each seat sees, and [Layer 1](docs/deduction.md), which works out exactly where each card can be from what a seat has seen. Standard library only. |
| [fish-env](https://pypi.org/project/fish-env/) | The PettingZoo environment: 648-bit observations, masks over 913 actions, declaration windows after every event. Passes PettingZoo's API and seed tests. |
| [fish-agents](https://pypi.org/project/fish-agents/) | The agent interface (`act(view, rng) -> int`), B0 (random legal play), and `play_game` for six agents. |

Every game is its seed plus its actions, and every encoding a game depends on (the random
numbers, the deal, actions, states, views, observations) is frozen under a name and pinned by
test vectors, so a recorded game replays the same way on any machine, in any later release
([determinism](docs/determinism.md)).

## The game in brief

Six players, two teams of three. The 54 cards (a standard deck and two jokers) form nine sets
of six: the low and high half of each suit, and the four 8s with the jokers. On your turn you
ask an opponent for a card of a set you already hold part of; if they have it, it is yours and
you go again, and if not, the turn passes to them. At any time a player may call a set by
assigning each of its six cards to a teammate: a correct call scores the set for their team,
a wrong one gives it to the other team. The first team to five sets wins. The full rules are
in [docs/rules.md](docs/rules.md).

## What's next

Planned, in order: an agent memory wrapper (full, last-k or no memory), stronger baselines
B1 to B3, and a website where people play, whose anonymised games will be released as a
corpus under CC BY 4.0 with a datasheet ([corpus](docs/corpus.md),
[datasheet plan](docs/datasheet-plan.md)). Changes are listed in the
[changelog](CHANGELOG.md).

## Documentation

- [Rules](docs/rules.md): Canonical Ruleset v1.1, the rules the engine implements
- [Environment](docs/environment.md): the multi-agent interface, its actions, rewards and seeding
- [Agents](docs/agents.md): the agent interface, B0, and the checks that run B0 games
- [Deduction](docs/deduction.md): Layer 1, where each card can be, how it works and why it
  is exact
- [Examples](examples/README.md): four short scripts that run after `pip install`
- [Determinism](docs/determinism.md): the random-number scheme behind every recorded game,
  and the frozen encodings of actions, records, views and observations
- [Testing](docs/testing.md): what the tests check, where they run, and what to do when one
  fails
- [Corpus](docs/corpus.md): what every website game records, who is in the corpus, and what
  is released
- [Datasheet plan](docs/datasheet-plan.md): how each question of the corpus datasheet will
  be answered, and when
- [Decision log](docs/decisions.md): what was chosen, and why
- [Setup](docs/setup.md): working on the code: a working copy, everyday commands,
  troubleshooting
- [Restore drill](docs/runbooks/restore-drill.md): rehearsing a database restore on staging
- [Releasing](docs/runbooks/release.md): publishing a new version

## Citing and licence

To cite the benchmark, use [CITATION.cff](CITATION.cff) (GitHub shows it as "Cite this
repository"). The code is licensed under [Apache-2.0](LICENSE); the corpus, when released,
under CC BY 4.0.
