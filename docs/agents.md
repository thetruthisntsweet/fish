# Agents

`fish_agents` holds the baseline agents (B0 now; B1–B3 in T5.2–T5.5) and the interface they
share. An agent plays one seat, sees only what that seat may know, and returns an action.

## The interface

```python
class Agent(Protocol):
    def act(self, view: PlayerView, rng: SplitMix64) -> int: ...
```

- `view` is the seat's view, `fish_rules.view.project`: its own hand, the public state, the
  most recent event and its legal action indices (R.2; `docs/environment.md`).
- `rng` is a generator for any random choice the agent makes.
- The return value must be one of `view.legal`, an index in the action layout
  (`docs/determinism.md` §9). Anything else raises `IllegalActionError`.

An agent never gets the game seed, because the seed would reveal the deal.
[`examples/02_your_own_agent.py`](../examples/02_your_own_agent.py) writes one, reads its view,
decodes the legal action indices, and plays it against B0.

## Randomness

`fish_agents.PolicyStreams(game_seed)` hands out the generators. A decision by seat *s* after
*e* events draws from the game's `bot_policy` stream at index *e* × 6 + *s*
(`docs/determinism.md` §2). If a seat decides twice before the next event, for example
answering a window and then assigning its own call, it keeps drawing from the same
generator, so the second decision does not repeat the first's draws. A game of seeded agents
is therefore fixed by its game seed: the same agents and seed always play the same game, here
and on the website, where the bots (T3.5) draw the same way.

`fish_agents.base` needs only fish-rules, so the server can run agents as bots without
installing the environment.

## Playing a game

```text
fish_agents.play.play_game(agents, game_seed) -> record
```

`play_game` seats `agents[s]` at seat *s* of `fish_env.FishEnv`, asks whichever agent the
environment selects until the game is over, and returns the game record
(`fish_rules.record`), which `replay_record` replays exactly. It needs fish-agents' `env`
extra; the workspace's `uv sync --all-packages` already has it.

## B0, the random legal agent (`b0-v1`)

`fish_agents.b0.B0` chooses uniformly among its legal actions at every decision, with one
exception: in a declaration window it passes, and declares (a uniformly chosen set) only one
time in 100. If B0 answered windows uniformly it would declare about nine times in ten, so
nearly every window would end in a call and no game would ever reach an ask.

B0 looks only at its legal actions and whether a window is open. Its games average about 36
asks and 7.6 calls, and they all finish. Its choices reveal its hand only through which
actions are legal, but that is still a little: a hand with fewer legal asks makes each of its
asks likelier. The H1c placebo (a belief model trained on B0 games) should therefore gain
almost nothing over the B2 sampler, but not exactly nothing.

The definition is frozen as `b0-v1`, pinned by five games in `test_b0.py`. A different B0
needs a new name (D37).

## Checks that use B0

- **Performance smoke (every CI run).** `scripts/bench_b0.py` plays 1,000 B0 games and
  reports games per second, microseconds per legal-mask computation, and the games' mean
  actions, asks and calls. The numbers are kept as the `performance` artifact. Run it locally
  with `uv run python scripts/bench_b0.py --games 1000`.
- **Nightly soak.** `scripts/soak_b0.py` plays 100,000 B0 games across the runner's cores and
  checks every state of every game: the rules' consistency checks, every R.9 invariant, event
  numbering, a proper end, and that the record replays. A failure names its seed. Rerun one
  game with `uv run python scripts/soak_b0.py --first-seed SEED --games 1`.
