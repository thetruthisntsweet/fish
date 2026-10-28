# The Fish environment

`fish_env` is a [PettingZoo](https://pettingzoo.farama.org) environment using the Agent
Environment Cycle (AEC) API: six agents, one acting at a time. It wraps the rules engine
(`fish_rules`), so it plays Canonical Ruleset v1.1 exactly. The [README](../README.md#quick-start)
has a complete example, and [`examples/`](../examples/README.md) has four more, from a random
game to the shape of a training loop.

```text
fish_env.env()       the environment with PettingZoo's bounds and order checks
fish_env.FishEnv     the same environment without them
```

## Agents and who acts

The agents are `seat_0` to `seat_5`. Seats 0, 1 and 2 are team 0; seats 3, 4 and 5 are
team 1 (R.1.1). `agent_selection` is always the lowest seat that may act now:

| Phase | Who acts | Actions |
|---|---|---|
| Declaration window | every seat, once each, lowest first | `Pass` or `Declare` a set |
| Turn | the current player | `Ask` an opponent for a card, or `Call` a set |
| Assignment | the caller | `Assign` the set's six cards to teammates |
| After-call choice | the caller | nominate the teammate who takes the turn |
| Team vote | each member of the scoring team, lowest first | nominate a teammate |
| Run-out | the selected caller | `Call` a set |

The environment handles windows itself (R.4.2, R.8.9). It opens one at the start of the game
and after every ask, call and after-call choice, and closes it once all six seats have
answered. The declaration with the highest priority (R.8.1) goes on to the assignment. Agents
never choose to open or close a window. Seats answer a window without seeing each other's
declarations, so the order they answer in cannot change the result.

## Observations

Each observation is a dict:

- `observation`: 648 bits, the seat's view encoded as `fish-obs-v1`
  (`docs/determinism.md` §11).
- `action_mask`: 913 bits, 1 for each action the seat may take now.

Both come from the seat's view, `fish_rules.view.project`, the same projection the website
sends its players. A seat sees its own hand, every hand size, which sets are scored and by
whom, the phase and whose turn it is, the call being assigned, the choice in progress with
only its own vote, its own answer in an open window, the outcome, and only the most recent
event: an ask and its answer, a call with its assignment and the true holders of its cards,
or an after-call choice (R.2). It never sees other hands, the seed, other seats'
declarations or votes, or a window's priority order. `FishEnv.view(agent)` returns the view
itself.

Seats are written relative to the observer, in the same order as the action layout: slots
0–2 are the observer's team in ascending order (the `me` block marks which is the observer),
slots 3–5 the other team. Earlier events are not repeated; an agent that wants them must
remember them. `fish_env.memory_env(remembered)` keeps them for it: each agent's `infos`
entry holds the observations it had just after the events it remembers (`docs/memory.md`).
Seats that may not act get an all-zero mask.

## Actions

An action is an index in `range(913)`, read from the acting seat's point of view, so one
policy can play any seat. The layout is `fish-action-index-v1`, in `fish_rules.action_index`
and `docs/determinism.md` §9. `encode(action)` and `decode(seat, index, phase)` convert
between indices and engine actions.

An action the mask does not allow raises `IllegalActionError` and changes nothing. The
environment never substitutes a legal action or ends the game with a penalty.

## Rewards and the end of an episode

- **A finished game** (a team claims five sets, R.7.1): every agent is terminated. Each seat
  of the winning team gets +1 and each seat of the other team −1, at the end and nowhere
  else, so the teams' rewards sum to zero.
- **An unfinished game** (1,000 asks, R.8.2): every agent is truncated with reward 0. These
  games are excluded from all analysis.

After the end, each agent's `infos` entry is `{"outcome": "finished" | "unfinished", "winner":
0 | 1 | None}`. As usual in PettingZoo, each agent then steps once with `None` to leave.

## Seeding and records

`reset(seed=s)` starts the game that seed `s` deals, an unsigned 64-bit integer. The seed
decides the deal, the first player, every window's priority order and every tie-break, through
the project's own generator (`docs/determinism.md`), never NumPy, Python's `random` or the
clock. The same seed and the same agent actions give the same game on any machine.
`reset()` without a seed draws one from the operating system and keeps it in `game_seed`.

`record()` (on `FishEnv`, or `env().unwrapped`) returns the game as plain data: the ruleset
version, the action encoding, the seed, the outcome, the winner and every action.
`fish_rules.record.replay_record(record)` replays it and checks that it ends as recorded.
`state_hash()` gives a fingerprint of the current state: two games with the same hash are in
the same state.

## Environment and website

Corpus games are played on the website and benchmark games in this environment, under
different mechanics by design (R.8.9). Here every agent is asked in every window. On the
website a window opens only when someone presses Call, and timers apply (R.8.3–R.8.5). The
environment has no timers (R.8.6). Agent memory (full, last-k or none) is the agent's, not
the environment's (`docs/memory.md`); k counts events, so last-k means the same on both.

## How it is checked

Every run of the test suite does the following:

- runs PettingZoo's `api_test` and `seed_test`;
- plays all eight golden games through the environment, comparing the state hash after every
  agent step;
- checks the rules' invariants (R.9) at every step of random games;
- requires 100% branch coverage of `fish_env`.
- checks that every observation is its seat's view, encoded, and that a seat's view never
  changes when anything hidden from it does (`fish_rules` leak tests);

## Agents

`docs/agents.md` describes the agent interface (`fish_agents`): an agent gets its seat's view
and a generator and returns an action index, and `fish_agents.play.play_game` runs six of them
in this environment. B0, the random legal agent, is the first. An agent that wants to know
where cards can be passes its views to a Layer 1 tracker (`docs/deduction.md`).
