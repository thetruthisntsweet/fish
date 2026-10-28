# Changelog

Changes to the published packages, fish-rules, fish-env and fish-agents, which are released
together at one version. Versions follow [semantic versioning](https://semver.org); while the
version is 0.x, a minor release may change the interface. The rules have their own version
and changelog ([docs/rules.md](docs/rules.md), R.10), and every frozen encoding has its own
name: a change to one is never silent, and is always listed here.

## 0.2.0 (2026-10-27)

Exact deduction of where every card can be, and agent memory. No frozen encoding changed:
games recorded with 0.1.0 replay identically.

### fish-rules

- Layer 1 (`fish_rules.deduce`, [docs/deduction.md](docs/deduction.md)): exactly which seats
  may hold each card, for any seat (or the public view) from its view and the events it
  remembers, with full, last-k or no memory. `deduce`, `solve` and `example_deal`
  (`fish_rules.deduce.solve`); the constraints behind them (`fish_rules.deduce.history`);
  `Tracker` for agents (`fish_rules.deduce.tracker`); and `knowledge` and `certain_misses`
  over recorded games (`fish_rules.deduce.games`).
- The four control actions with no fields (`OpenWindow`, `CloseWindow`, `AssignTimeout`,
  `ChoiceTimeout`) refuse attribute assignment with `FrozenInstanceError` on every Python
  3.14 release; before 3.14.7 they raised `TypeError`.

### fish-env

- `memory_env(remembered)` and `MemoryWrapper` (`fish_env.memory`,
  [docs/memory.md](docs/memory.md)): each agent's `infos` entry holds, under `"memory"`, the
  observations it had just after the events it remembers (all, the latest k, or none). The
  observation and action spaces are unchanged.

### fish-agents

- Agent memory (`fish_agents.memory`, [docs/memory.md](docs/memory.md)): `MemorySetting`
  (full, last-k or none, written as the corpus writes it; k counts events), `Memory` for one
  seat, with Layer 1's deduction from what it remembers, and `Remembering`, which gives an
  agent with `act(view, memory, rng)` a memory for each seat it plays.
- `Observer` (`fish_agents.base`): `play_game` shows an agent that has `observe(view)` its
  seat's view after every action, whoever acted. B0's games are unchanged.
- The packages require each other at 0.2.

## 0.1.0 (2026-10-25)

The first public release.

### fish-rules

- The rules engine for Canonical Ruleset v1.1 (`RULESET_VERSION = "1.1"`): asks, two-step
  calls with declaration windows and seeded call priority, the after-call choice and vote,
  running out, and the end of the game, with the website's timer outcomes as engine actions.
- Immutable states and `apply(state, action)`; a game is its seed and its actions, and
  `replay` reproduces every state and record.
- `fish_rules.view.project`: what each seat may see, the only way information reaches a player.
- Frozen encodings, each pinned by test vectors: the random numbers
  (`splitmix64-sha256-v1`), actions as data (`fish-actions-v1`), the state hash
  (`fish-state-v1`), action indices (`fish-action-index-v1`, 913 actions), views as data
  (`fish-view-v1`), observations (`fish-obs-v1`, 648 bits), and the held-out cohort draw
  (`fish-cohort-v1`).
- Game records (`fish_rules.record`) and the corpus record format (`fish-corpus-v1`,
  `fish_rules.corpus`), read back and replayed exactly.
- Reference drivers for random games under environment and website mechanics
  (`fish_rules.playout`).

### fish-env

- `fish_env.env()` and `FishEnv`: a PettingZoo AEC environment with six agents, per-seat
  observations with legal action masks, declaration windows after every event, deterministic
  seeding, and game records. Passes PettingZoo's `api_test` and `seed_test`.

### fish-agents

- The `Agent` interface (`act(view, rng) -> int`) and `PolicyStreams`, so seeded agents
  replay exactly.
- B0 (`b0-v1`), the random legal baseline.
- `play_game(agents, game_seed)`, with the `env` extra.
