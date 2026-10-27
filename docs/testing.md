# Testing

How the game packages (fish-rules, fish-env, fish-agents) are tested: what each kind of test
checks, where it runs, and what to do when one fails. Setup and the everyday commands are in
[setup.md](setup.md); the frozen encodings the tests hold the code to are in
[determinism.md](determinism.md).

## 1. Running the tests

| To | Run |
|---|---|
| Run every test, quickly (`dev` profile) | `uv run pytest` |
| Run them as CI does | `HYPOTHESIS_PROFILE=ci uv run pytest --cov` |
| Check a package is fully covered | `uv run coverage report --include="*/fish_rules/*" --fail-under=100` (after the line above; likewise `fish_env`, `fish_agents`) |
| Run one file, one test | `uv run pytest packages/fish-rules/tests/test_record.py -k log` |
| Run every check CI runs, in order | `scripts/check.sh` |
| Check the replay digest | `uv run python scripts/replay_digest.py --check packages/fish-agents/tests/vectors/replay_digest_v1.json` |

Coverage has a project-wide floor of 85% (`pyproject.toml`), so `--cov` on a single package's
tests fails that floor even when the package itself is fully covered. Run the whole suite with
`--cov`, then `coverage report --include` for the package. The database tests skip unless
`.env` points at a Postgres server (setup.md); `scripts/check.sh` loads `.env` itself.

## 2. Hypothesis profiles

`conftest.py` registers three profiles; `HYPOTHESIS_PROFILE` picks one (default `dev`).

| Profile | Examples | Where | Notes |
|---|---|---|---|
| `dev` | 100 | your machine | random examples; Hypothesis keeps failures in `.hypothesis/` and tries them first next run |
| `ci` | 1,000 | every pull request and push to main | derandomized: the same examples every run, so a CI failure reproduces locally with the same profile |
| `nightly` | 50,000 | scheduled, 07:17 UTC | random examples, so each night explores new ones |

Tests that play whole games take a share of the profile's examples, so the suite stays fast:

| Share | Tests | dev / ci / nightly |
|---|---|---|
| a tenth (`// 10`) | R.9 over whole games, the environment's mechanics, log-to-replay, PettingZoo conformance | 10 / 100 / 5,000 games |
| a twentieth (`// 20`) | the website state machine (up to 300 actions per run) | 10 / 50 / 2,500 runs |
| a fortieth (`// 40`) | per-seat sweeps: legal indices, views, view data, leaks, observations (every seat at every step) | 10 / 25 / 1,250 games |

Every other property test uses the profile's full count. Whole-game tests set
`deadline=None`, since a long game is not a slow example.

## 3. What is tested

**Rules, one at a time.** `test_engine_*.py`, `test_priority.py`, `test_cards.py` and
`test_state.py` test each rule of the Canonical Ruleset directly, with unit tests for the
cases the rule names and property tests over random states (asks conserve cards, any valid
call conserves cards, priority alternates teams, and so on).

**Rule traceability.** A test cites the rule it checks in its name or docstring (`R.4.3`,
`test_r8_3_…`). `scripts/check_rule_citations.py` fails unless every rule of the current
ruleset is cited by a test or listed in its `OWED` table with the task that will test it.
Five rules are owed today: R.2.5 and R.2.6 (the client, T3.4), R.8.4 and R.8.5 (the server's
timers, T3.1) and R.8.8 (website bots, T3.5). A citation of a range such as "R.8.3-R.8.7"
cites every rule in it, so name only the rules a test checks. It runs as a pre-commit hook.

**Whole games under environment mechanics.** `fish_rules.playout.random_game` plays whole
games with a window after every event and every seat answering it. `test_whole_games.py`
checks R.9 and the consistency invariants at every step, that event numbers run 0, 1, 2, …,
that every game ends, and that `legal_actions` is exactly what the engine accepts.
`test_engine_environment.py` checks the rules the engine owes the environment (R.2.4, R.8.6,
R.8.9).

**Whole games under website mechanics.** `fish_rules.playout.random_website_game` plays
random games the way a corpus record records them (presses, timers, received and sent times);
the corpus tests in fish-rules and fish-server write, read and export its games.
`test_website_machine.py` is a Hypothesis state
machine. It interleaves Call presses on any turn, windows closed whoever has answered,
assignment and choice timeouts, legal seat actions and arbitrary seat actions, in any order
the rules allow. After every step it checks consistency and R.9, that a seat action is
accepted exactly when its index is legal, that the legal indices are the encoded legal
actions, and that no seat's view moves when what is hidden from it does. When a run fails,
Hypothesis shrinks it to the shortest sequence of steps that still fails and prints it as
code.

**What each seat sees.** `test_view_leaks.py` changes everything hidden from a seat (the
other hands with sizes kept, the seed, other seats' window answers and votes) at every step of
random games, and requires the seat's view to stay the same. It also requires public
information to be the same for every seat, and no view to hold an earlier event or a log-only
record. `test_view.py`, `test_view_data.py` and `test_observation.py` check the view and the
observation field by field. `test_env_observation.py` checks the environment observes
through the same projection.

**The environment.** `test_conformance.py` runs PettingZoo's `api_test` and `seed_test`,
checks the environment applies exactly the reference mechanics, and checks R.9 at every
agent step. The other `fish-env` tests cover the AEC cycle, rewards and seeding.

**Agents.** The `fish-agents` tests check that B0 plays only legal actions, chooses
uniformly, passes in a window except 1 time in 100, and replays its frozen games, and that
`play_game` gives every agent only its own view.

**Determinism.** These hold the code to frozen behaviour (§5):

- *Frozen vectors.* `packages/fish-rules/tests/vectors/` pins the random-number generator,
  the deal, call priority, the seed tie-break, the cohort draw, action indices, views and
  observations; the generator, deal, priority, tie-break and cohort vectors are also
  recomputed by an independent JavaScript implementation (`scripts/verify_rng_vectors.mjs`).
- *Golden replays.* Eight complete games in `packages/fish-rules/tests/golden/` must replay
  to the same state hash after every action.
- *Log-to-replay.* A game is its record. `test_record.py` and the website state machine
  write each game's record to JSON text, read it back and replay it, and require the same
  records and the same state after every action as playing it did.
- *Replay digest.* `scripts/replay_digest.py` hashes the replays of 300 fixed games (100 each
  under playout, B0 and website mechanics) state by state into one digest, frozen in
  `packages/fish-agents/tests/vectors/replay_digest_v1.json` (determinism.md §12).
- *Hash seeds.* The game packages' tests and the replay digest run under `PYTHONHASHSEED` 0
  and 4242, and the two digests must be identical, so nothing depends on set or dict order.

**Layer 1.** `test_deduce_history.py` checks each kind of public fact and each refused history,
and that the true deal satisfies every constraint. `test_deduce_solve.py` checks exactness:
the truth is always named, forcing a card to each seat agrees with the solver, and deals
putting a card with another named seat replay through the engine with every record and the
seat's every view unchanged. `test_deduce_uses.py` checks the tracker, `knowledge` and
`certain_misses` against deducing directly. All run for every seat, the public view and
random memories (`docs/deduction.md`).

**Installing.** `scripts/check_install.py` builds the three published packages, checks them
with `twine check`, installs the wheels into an empty environment outside the repository
(everything else from PyPI, as for a user), checks each package imports from there at its
declared version, and runs every Python block of the READMEs (the root one and the three PyPI
pages) and every script in `examples/`. A README example that stops working fails CI.
`test_packaging.py` checks the metadata itself: one version, the licence, links and bounds,
and that the changelog and citation name that version. `scripts/check_release.py` checks a
release tag against the same files before anything is published (`test_check_release.py`).

**Scale.** `scripts/bench_b0.py` plays 1,000 B0 games in CI and records games per second and
microseconds per legal mask and per Layer 1 deduction as an artifact. `scripts/soak_b0.py`
plays 100,000 B0 games every night and checks every R.9 invariant at every state, and
`scripts/soak_deduce.py` checks Layer 1 at every event of 3,000. All have tests that run them
small.

## 4. Where tests run

| Where | What |
|---|---|
| Pre-commit (every commit) | Ruff, Pyright, package boundaries, rule citations, generated types, client lint |
| CI: *Python tests + coverage + migrations* | every test at the `ci` profile with Postgres; 100% coverage of fish_rules, fish_env and fish_agents |
| CI: *Determinism* | RNG vectors in JavaScript; golden replays; fish-rules, fish-env and fish-agents tests under two hash seeds; the replay digest under both, checked and compared |
| CI: *Install from the built packages* | fish-rules, fish-env and fish-agents built, installed into an empty environment with their dependencies from PyPI, and every README code block and example run there (`scripts/check_install.py`) |
| CI: *Performance smoke* | 1,000 B0 games, timings kept as an artifact |
| Release (version tags) | the tag is on main and matches the versions, changelog and citation; the install check; then PyPI and the GitHub release ([runbook](runbooks/release.md)) |
| Nightly: *Hypothesis* | fish-rules at the `nightly` profile; fish-env and fish-agents in a second job |
| Nightly: *Soak* | 100,000 B0 games with every R.9 check |
| Nightly: *Soak, Layer 1* | Layer 1 at every event of 3,000 B0 games, checked against the truth and by replaying other deals |

## 5. When a test fails

- **A property test in CI.** The `ci` profile is derandomized, so
  `HYPOTHESIS_PROFILE=ci uv run pytest <the test>` fails the same way locally. The log also
  prints `@reproduce_failure(...)`; paste it above the test to replay exactly that example.
- **A nightly property test.** Nightly examples are random; copy the
  `@reproduce_failure(...)` line from the log. Once fixed, add the example with `@example`
  so CI keeps checking it.
- **The Layer 1 soak.** It prints the first failing seed; rerun that game with
  `uv run python scripts/soak_deduce.py --first-seed SEED --games 1`. A holder missing means
  a fact was read too strongly; "another deal changes" means one was missed or read too
  weakly.
- **The soak.** It prints the first failing seed; rerun that game with
  `uv run python scripts/soak_b0.py --first-seed SEED --games 1`.
- **A frozen vector, golden replay or the replay digest.** The code now behaves differently
  from what was frozen. If that was not intended, it is a bug. If it was (a rule changed),
  it needs a new ruleset version or a new encoding name, the files regenerated with their
  script's `--regenerate` (the digest: delete the file and write it again with `--out`), and
  a decision log entry. The scripts refuse to overwrite frozen files otherwise. The digest's
  check names which kind of game changed.
- **The two hash seeds disagree.** Something iterates a set or a dict of strings in an order
  that matters. Sort it.
- **Rule citations.** A new rule needs a test that cites it or an `OWED` entry; a rule that
  is now tested must leave `OWED`.

## 6. Adding a test

- Cite the rule the test checks, in its name (`test_r4_3_…`) or docstring.
- A test that plays whole games takes a share of the profile's examples (§2), using
  `GAMES = max(10, int(settings().max_examples) // N)`, with `deadline=None`.
- Keep fish_rules, fish_env and fish_agents at 100% branch coverage: every branch is
  tested, and none is excluded from coverage.
- Draw randomness from Hypothesis or from a seeded `SplitMix64`, never from `random` or the
  clock, so every failure reproduces.
- Freeze new behaviour other code will rely on as vectors written once by a script that
  refuses to overwrite them (`scripts/make_*_vectors.py`), and describe it in
  determinism.md.
