# Agents

`fish_agents` holds the baseline agents (B0 and B1 now; B2 and B3 later) and the interface they
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

An agent that is an `Observer` (it has `observe(view)`) is also shown its seat's view after
every action, whoever acted. Agents with memory are observers.

## Memory

An agent remembers everything it is shown, only the latest k events, or nothing beyond its
current view. `fish_agents.memory.Remembering(agent, setting)` gives an agent that takes
`act(view, memory, rng)` a memory for each seat it plays, with Layer 1's deduction from what
it remembers. `docs/memory.md` describes the settings, what k counts, and the environment's
memory wrapper for training.

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

## B1, the exact-inference agent (`b1-v1`)

`fish_agents.b1.b1(setting)` is B1 with full, last-k or no memory (`Remembering(B1(),
setting)`). Every decision reads Layer 1's exact deduction from what it remembers
([deduction.md](deduction.md)):

- **Calls.** B1 calls a set, in any window or on its turn, exactly when it knows where all six
  cards are and all six are with its team. Layer 1 never rules out the truth, so every call
  B1 chooses is right, at every memory setting.
- **Asks.** An ask certain to succeed if it has one; otherwise the likeliest, each card's
  possible holders weighted equally (RQ1's floor model). It never makes an ask certain to
  miss while another is legal.
- **The after-call choice and the vote.** The teammate with the most asks B1 can tell are
  certain to succeed, then the one with the most cards.
- **Calls it must make** (run-out, R.6.2): the set with the most cards it knows are with the
  team, each card it does not know assigned as a deal that fits everything it has seen has it.

The generator breaks ties and only ties, so a B1 game is fixed by its seed.

**On the website** a call starts with a press of Call (R.8.3). After every event each bot
decides whether to press (R.8.8): `would_call(view, deduction, rng)` is B1's decision, the
set of a certain call when no window, assignment, choice or run-out is in progress, and
otherwise none. It names the set B1 would call on its turn in the environment, drawn the
same way. B1 never declares in a window someone else opened.

**Memory decides whether its games end.** With little memory B1 can rarely prove a call, so
six B1s often reach 1,000 asks (R.8.2) and the game is unfinished: in 10 games at each
setting, all finished at full memory, 5 at last-8, 4 at last-2 and none with no memory.
Against three B0s it finished and won all 10 at every setting. B1 is frozen as it is (D85):
it is the agent whose every call is right.

A B1 decision takes about 1.2 ms (one Layer 1 deduction and a little arithmetic; the
performance smoke reports it). The definition is frozen as `b1-v1`, pinned by five games in
`test_b1_frozen.py`. A different B1 needs a new name.

## Checks that use B0 and B1

- **Performance smoke (every CI run).** `scripts/bench_b0.py` plays 1,000 B0 games and
  reports games per second, microseconds per legal-mask computation and per Layer 1
  deduction, and the games' mean actions, asks and calls; then 20 full-memory B1 games, with
  games per second and microseconds per B1 decision (mean and 99th percentile). The numbers are kept as the
  `performance` artifact. Run it locally with `uv run python scripts/bench_b0.py --games 1000`.
- **Nightly soak.** `scripts/soak_b0.py` plays 100,000 B0 games across the runner's cores and
  checks every state of every game: the rules' consistency checks, every R.9 invariant, event
  numbering, a proper end, and that the record replays. A failure names its seed. Rerun one
  game with `uv run python scripts/soak_b0.py --first-seed SEED --games 1`.
- **Nightly Layer 1 soak.** `scripts/soak_deduce.py` deduces at every event of 3,000 B0
  games, for every seat and the public view, and checks the answer against the truth and,
  at one point in 20, by replaying another deal through the engine (`docs/deduction.md`).
  Rerun one game with `uv run python scripts/soak_deduce.py --first-seed SEED --games 1`.
