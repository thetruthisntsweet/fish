# Decision log

Every significant choice made while setting up the project (T2.1), with the alternatives and
the reason, so that later readers — reviewers, the paper, future you — can see why things
are the way they are. Newest decisions are added at the end; a decision that is reversed
gets a new entry pointing back to the old one, rather than being edited away.

Format: **D-number · date · decision.** Then the alternatives considered and why.

---

**D1 · 2026-10-12 · The engine is written in Python 3.14.**
Alternatives: TypeScript (one language with the client), Rust (speed). Python is what
researchers who would use the benchmark already use (Plan §3). 3.14 was the newest version
supported by both PyTorch and PettingZoo. Rust remains the route for any hot path that
profiling shows is too slow (T2.1 §13).

**D2 · 2026-10-12 · One repository, a uv workspace of five packages with enforced boundaries.**
`fish-rules` (standard library only), `fish-env`, `fish-agents`, `fish-server`,
`fish-research`, plus the client. Alternatives: one package; separate repositories.
One repository keeps an engine change and the server or client change that depends on it in
one commit; import-linter in CI stops the boundaries eroding, so there is never a second
implementation of the rules (Plan §3).

**D3 · 2026-10-12 · A project-owned random-number scheme, `splitmix64-sha256-v1`, frozen.**
Alternatives: Python's `random`; NumPy's `Generator`. Neither promises identical shuffles
across versions, and a recorded game is only a seed plus an event log, so replays must match
forever. SplitMix64 per named stream, seeded from SHA-256 of (seed, name, index); 223 frozen
test vectors, independently recomputed by a JavaScript implementation in CI. Specified in
`docs/determinism.md`.

**D4 · 2026-10-12 · The multi-agent interface will be PettingZoo's AEC API.** (Built in T2.3.)
Alternatives: Gymnasium wrappers, RLlib, OpenSpiel. AEC steps one agent at a time, which
fits asks, sequential window polling and votes, and is widely known.

**D5 · 2026-10-12 · Message types are defined once, in Python, and generated for the client.**
Pydantic models → JSON Schema (`schemas/`) → TypeScript (`client/src/generated/`), with a
drift check in the hooks and CI. Alternatives: hand-written TypeScript types; Protocol
Buffers. Per-field titles are dropped from the schemas because they made the generator emit
colliding type names.

**D6 · 2026-10-12 · Client: React + TypeScript + Vite, with ESLint (type-checked rules),
Prettier and Vitest.** The current Vite template ships oxlint instead; it was swapped for
ESLint as T2.1 §3 specifies, for its type-aware rules. Node 24 LTS (or 22.22.2+) because the
test DOM library requires it.

**D7 · 2026-10-12 · PostgreSQL 17 everywhere: Docker locally, the same image in CI, pinned on
Render.** SQLAlchemy Core with Alembic migrations, numbered revisions (`0001`, `0002`, …),
a constraint naming convention set before any table exists, and Ruff run automatically on
every generated migration. Alternatives: SQLite (no concurrent writers), MongoDB.

**D8 · 2026-10-12 · Pre-commit hooks run each tool from the repository's own lock files.**
Alternative: pre-commit's usual downloaded copies of Ruff, Prettier and others, which can
silently differ from the versions CI uses.

**D9 · 2026-10-12 · CI on GitHub Actions: five parallel jobs plus a nightly run.**
Hooks; Python tests with a real PostgreSQL and the pre-deploy command; determinism (vectors,
two hash seeds); client; server image. Actions pinned to versions checked at setup;
`astral-sh/setup-uv` pinned to `v10.3.0` because it publishes no short `v10` tag.

**D10 · 2026-10-13 · Hosting on Render: Virginia region, $7/month server, $6/month database.**
Alternatives compared on current pricing pages: Fly.io (managed PostgreSQL from $38/month),
Railway (usage-based, harder to predict). Render met every T2.1 §10 requirement: no maximum
WebSocket duration, managed PostgreSQL with point-in-time recovery on the free Hobby
workspace, custom domains, a US East region. The free server plan was rejected because it
sleeps and drops WebSockets. Staging deploys from `main` only after CI passes; production
is added before launch.

**D11 · 2026-10-13 · Starlette's test client uses `httpx2`.** The current Starlette deprecates
`httpx` for its test client, and the project treats warnings as errors.

**D12 · 2026-10-13 · The server image: two stages, non-root user, migrations included.**
Only Python, the installed packages and the migrations reach the runtime image; uv pinned to
0.11.32; the user has a login shell and `~/.ssh` because Render's Shell page needs both.

**D13 · 2026-10-14 · The staging database accepts no connections from outside Render.**
`ipAllowList: []`. Alternative: allow your own IP for convenience. The data will be
participants' gameplay; admin work goes through the server's Shell instead. Disk 1 GB,
which can grow later but never shrink.

**D14 · 2026-10-14 · Backups are Render's point-in-time recovery, rehearsed.**
A restore creates a new database at a chosen moment (3-day window on Hobby). Drill on
2026-10-14: marker written, deleted, restored to the moment before deletion, found.
Restore took 7 minutes. PASS. Repeat before launch (T3.6). `docs/runbooks/restore-drill.md`.

**D15 · 2026-10-14 · Least privilege for the running server (T2.1 §11).**
The server logs in as `fish_server`, a member of `fish_app`, which may read and insert on
every table migrations create (default privileges) and nothing else. The owner (`fish`)
runs migrations and admin tools. Tables that must never change get triggers that refuse
UPDATE, DELETE and TRUNCATE even from the owner. `python -m fish_server.deploy` runs as
Render's pre-deploy command and refuses to deploy if the login has too many rights.
Render's generated password means no person ever sees it.
Depends on: Render's database owner having the CREATEROLE attribute.
Verified on staging: 2026-10-14, `PASS: fish_server can read, and cannot create tables or roles.`
Limitation: Render runs the pre-deploy step in the server's environment, so the owner URL is
present there too. This protects against bugs and SQL injection, not against a full takeover
of the server machine.

**D16 · 2026-10-14 · The test suite uses its own database login.**
Found while writing `docs/setup.md`: logins belong to the whole database server, so tests
that changed `fish_server`'s password broke the local development server after every
`check.sh`. Tests now use `fish_server_test_<random>` (via `FISH_APP_DB_USER`) and remove it
when they finish.

**D17 · 2026-10-14 · Training runs on the M5 MacBook Pro; no GPU request.**
Replaces T2.1 subtask 15. B3 trains on the Mac's GPU through PyTorch's MPS backend (PyTorch
2.14.1 ships Python 3.14 builds for Apple Silicon). GPU training is not bit-for-bit
repeatable, so final evaluation runs on the CPU and every training run records device,
library versions and seeds. Fallback: rent a cloud GPU for a single run only if it would
take more than a day.

**D18 · 2026-10-12 · Licences: Apache-2.0 for code, CC BY 4.0 for the corpus.**
Alternatives: MIT (no patent grant), CC0, CC BY-NC (blocks some research use). The consent
screen (T1.5) must state the CC BY 4.0 release.

**D19 · 2026-10-17 · Card numbering and the deal are frozen with the generator.**
Card = 6 × set + position; sets are low clubs to low spades, high clubs to high spades, then
the 8s and jokers; suits in bridge order (clubs, diamonds, hearts, spades); the red joker
before the black. The deal shuffles 0–53 with the `deal` stream and gives seat *k* positions
9*k* to 9*k* + 8; the first player is `below(6)` on `first_player`. Alternatives: dealing
round-robin (one card to each seat in turn), or numbering by suit and rank. Both are equally
good; what matters is choosing once, because the event log names cards by number. Frozen
deals for ten seeds, checked by the JavaScript implementation. Specified in
`docs/determinism.md` §6.

**D20 · 2026-10-17 · Call priority uses three fixed draws per window.**
`below(2)` for the team that goes first, then `below(3)` for team 0's starting seat, then
`below(3)` for team 1's, from the `priority` stream at the window index; all three are always
drawn, so the order of the draws never depends on an earlier result. Each of the 18 possible
orders has probability 1/18. Alternative: a single `below(18)`. Equivalent in distribution;
three draws read directly off R.8.1. Run-out callers (R.6.2) come from the same order. Frozen
orders for 53 (seed, window) pairs, checked by the JavaScript implementation. Specified in
`docs/determinism.md` §7.

**D21 · 2026-10-17 · Immutable state; a game is a seed plus its actions; events numbered by
R.4.2 only.**
The engine takes an immutable `State` and an action and returns a new state and the records
of what happened, so replay is `new_game(seed)` followed by the actions in order, and any
state can be kept, compared or hashed. Alternatives: a mutable game object (faster, but
replay and tests need copies); the server's log position as the event number (would differ
between website and environment and depend on server-only rows). Only asks, calls and
after-call choices are numbered, the R.4.2 meaning of "event"; the tie-break stream uses the
call's number. Every record is marked public or log-only, the starting point for the
projection (T2.4). Specified in `docs/determinism.md` §8.

**D22 · 2026-10-17 · Canonical Ruleset v1.1: the seed breaks a tied vote among the tied
seats.**
v1.0's R.5.2 said the seed chooses the seat on a tie without saying among which seats, so a
seat with no votes could have won. v1.1 states it: among the tied seats on a tie, among the
scoring team's players holding cards when the caller does not choose or no votes are cast.
Changed before any game was recorded, so no v1.0 games exist; `RULESET_VERSION` is "1.1".
The draw is `choice` over the seats in ascending order from the `tiebreak` stream at the
call's event number, frozen with 65 vectors checked by the JavaScript implementation
(`docs/determinism.md` §8).

**D23 · 2026-10-17 · Timer outcomes are engine actions; the server only keeps time.**
When a website timer runs out, the server applies `AssignTimeout` (R.4.3: an incorrect call)
or `ChoiceTimeout` (R.5.2: the seed chooses if the caller did not choose; votes not cast are
ignored), and asks `press_is_stale` whether a Call press that crossed a newer event must be
rejected (R.8.7). Alternative: the server decides these itself. That would be a second
implementation of rules, which Plan §3 rules out, and the outcomes would be untested by the
rules suite. A timed-out call is recorded with `assignment` None. The environment never
applies these actions (R.8.6).

**D24 · 2026-10-17 · Whole-game testing: a reference driver, golden replays, CI profile.**
`fish_rules.playout.random_game` plays complete games under environment mechanics (a window
at the start and after every event, every seat asked in every window) with a seeded, legal,
deliberately skewed policy: random calls are rare and a team that holds a whole set often
calls it, so correct calls and the caller's after-call choice occur. A uniform random policy
almost never made a correct call, which left the caller-chooses path untested. Eight golden
games (`docs/determinism.md` §8) replay on every run; the whole-game test checks the R.9
invariants at every step of a tenth of the profile's examples (100 games in CI). CI now sets
`HYPOTHESIS_PROFILE=ci`, which T2.1 §9 intended but the workflow had not set. The driver is a
test tool: the environment (T2.3) and B0 (T5.1) replace it for anything else.

**D25 · 2026-10-17 · Rule traceability is checked: every rule is cited by a test or owed.**
`scripts/check_rule_citations.py` lists the 37 rules of Canonical Ruleset v1.1 (R.9 counts as
one) and scans every package's tests for citations: "R.x.y" in a docstring or comment, a range
"R.x.y-R.x.z", or a test named `test_rx_y_...`. It fails on a rule nobody cites that is not
owed, on an owed rule that is now cited, on a citation of a rule that does not exist, and when
`RULESET_VERSION` no longer matches the version its list was written for. Five rules can only
be tested in the website or client and are owed: R.2.5 and R.2.6 by T3.4, R.8.4 and R.8.5 by
T3.1, R.8.8 by T3.5. Alternative: a hand-kept matrix in the doc. It would drift; the script
runs as a pre-commit hook (so in CI's hooks job) and in `scripts/check.sh`. A citation shows a
test exists, not that it is right; review still judges that.

**D26 · 2026-10-17 · Action indices: one flat space of 913, relative to the acting seat, in
fish-rules.**
T2.1 §16 left the discrete action encoding to T2.3. Every seat action is an index in
`range(913)` (`docs/determinism.md` §9): asks by opponent index and card, calls and
declarations by set, a pass, the 729 assignments of six cards to three teammates as one
base-3 number, and one block of three "nominate teammate" indices that is a choice or a vote
by phase. Targets are relative to the acting seat, so one policy plays any seat. It lives in
fish-rules, not fish-env, so the projection (T2.4) can put the mask in the observation and
the website can use the same mask without NumPy or PettingZoo. Alternatives: absolute seats
(a policy would have to learn six copies of each action); assignments as six one-card steps
(a smaller space, but the engine takes the call whole and a half-made assignment would be a
new state the rules do not have); separate Choose and Vote blocks (three extra indices with
the same meaning). The layout is frozen with vectors, as `fish-action-index-v1`.

**D27 · 2026-10-17 · The environment applies windows itself, selects the lowest acting seat,
and raises on an illegal action.**
`fish_env.FishEnv` is a PettingZoo AEC environment with agents `seat_0` to `seat_5`. It opens
a window at the start and after every event and closes it once all six seats have answered
(R.4.2, R.8.9); agents choose only seat actions, never `OpenWindow` or `CloseWindow`. When
several seats may act (a window, a vote), `agent_selection` is the lowest of them: the order
`fish_rules.playout` used to play the golden games. Window answers are
hidden from the other seats, so the order cannot change the result. An action the mask does
not allow raises `IllegalActionError` and changes nothing. Alternative: PettingZoo's
`TerminateIllegalWrapper`, which ends the game with a penalty; a benchmark would then score a
broken agent instead of failing. Until T2.4 the observation is the seat's own hand plus the
mask.

**D28 · 2026-10-18 · The environment's reward is the game result, once, at the end.**
When a game finishes (R.7.1), every seat of the winning team is rewarded +1 and every seat of
the other team -1, so the teams' rewards sum to zero; every earlier step rewards 0. A game
stopped at 1,000 asks (R.8.2) has no result: every agent is truncated, not terminated, and
rewarded 0, matching its exclusion from analysis. `infos` holds the outcome and the winner at
the end. Alternative: +1/-1 per set claimed. It would reward a team that claims four sets and
loses, and the research questions measure beliefs and calls, not set counts; per-set reward
is easy to rebuild from the events for anyone who wants it.

**D29 · 2026-10-18 · A game record format in fish-rules; the environment seeds only from the
game seed.**
`fish_rules.record` defines the record every component writes: the ruleset version, the
action encoding, the seed as a decimal string, the outcome, the winner and every action
(`docs/determinism.md` §8). It lives in fish-rules so the server (T3.2) writes the same
record without importing fish-env; the corpus schema (T1.6) wraps it rather than replacing
it. `replay_record` rejects a record from another ruleset version or encoding, or one whose
replay does not end as recorded. `FishEnv.reset(seed=s)` uses `s` as the game seed and
nothing else; without a seed it draws one from the operating system's secure source and
keeps it in `game_seed`, so an unseeded game is still reproducible from its record. The
environment uses no NumPy or Python random state, so PettingZoo's `np_random` plays no part.

**D30 · 2026-10-18 · Environment conformance: PettingZoo's checks, the golden games, 100%
coverage.**
The environment passes PettingZoo's `api_test` (wrapped and raw) and `seed_test` on every run,
with three of `api_test`'s advisory warnings allowed and the reasons written beside them. Every
golden game, given to the environment one seat action at a time, reproduces its actions and
its state hash after every agent step, and reference games from `fish_rules.playout` produce
identical action logs, so the environment and the reference driver apply the same mechanics
(R.4.2, R.8.9). fish-env joins fish-rules at 100% branch coverage in CI and `scripts/check.sh`.
`reset` now accepts and ignores `options`, because `api_test` passes options and expects an
environment without settings to accept them; D29's rejection of options is withdrawn.

**D31 · 2026-10-24 · One projection, in fish-rules, decides what every player sees.**
`fish_rules.view.project(state, seat, last_event)` gives a seat its own hand, every hand
size, the scored sets, the most recent event (with a call's true holders), the phase and
current player, the call being assigned, the choice in progress with only its own vote,
whether a window is open with only its own answer, the outcome, and its legal action indices
(R.2, R.4.3, R.5.2, R.8.3). The website and the environment both use it (Plan §3). It never
holds the seed, other hands, other seats' declarations or votes, or a window's priority
order: website players cannot see the priority order, and seeing it would tell a seat
whether its declaration will proceed. The most recent event is passed in, tracked with
`latest_event`, rather than stored in `State`, which would change the state hash and every
golden replay. Alternative: a projection per platform; two functions would drift, and a leak
in either would be invisible to the other's tests.

**D32 · 2026-10-24 · Leak tests change what is hidden and require the view not to move.**
A seat's view must be a function of what that seat may know. The leak tests check it
directly: at every step of random games and for every seat, they deal the other seats' cards
again among themselves with every hand size kept, replace the seed, and redraw other seats'
window answers and other members' votes, and the seat's view (legal actions included) must
not change. They also check that every seat sees the same public information, and that no
view holds an earlier event or a log-only record. Each kind of leak was introduced on
purpose once (another seat's cards, declaration or vote, the seed, others' window progress) to
confirm the tests catch it. The pre-pilot audit of what the server actually sends (T3.7)
builds on this; it does not replace it.

**D33 · 2026-10-24 · Views travel as fish-view-v1 JSON, written in fish-rules.**
The server sends each client its view as plain JSON written by `fish_rules.view.view_to_data`
(`docs/determinism.md` §10), so the website and the environment start from the same
projection and the same encoding of it. The layout is named `fish-view-v1` and frozen with
124 vectors from the golden games, covering every phase and every kind of event. The legal
action indices travel with the view, so the client disables illegal actions without any rules
logic (Plan §3). There is no `view_from_data`: nothing in Python reads views back, and the
client's TypeScript types come from the server's protocol models (T3.1), which mirror this
layout.

**D34 · 2026-10-24 · Agents observe fish-obs-v1: 648 bits, seat-relative, built from the view.**
`fish_rules.observation.encode(view)` writes everything in a seat's view as fixed blocks of
bits (`docs/determinism.md` §11): own hand, hand sizes, the state of each set, phase,
current player, the call being assigned, the choice in progress with the seat's own vote, the
seat's own window answer, the most recent event (a call's assignment and true holders card by
card), and the outcome. It encodes the view, never the state, so it cannot see more than the
projection allows. Seats are slots relative to the observer, in the same order as the action
layout, so one policy plays any seat and a nominate index points at the same teammate in the
observation and the action. Hand sizes are one-hot rather than counts, so every entry is 0 or
1. It lives in fish-rules so the baselines and the website's bots (T3.5) encode views the
same way without NumPy. Alternatives: a dict of arrays per field (policies flatten it
anyway); absolute seats (six copies of every pattern to learn). Frozen
with vectors as `fish-obs-v1`. The legal mask stays beside it, not inside it.

**D35 · 2026-10-24 · The environment observes through the projection.**
`FishEnv.observe` builds each agent's observation from `fish_rules.view.project`: the
`observation` entry is the view encoded as `fish-obs-v1` (648 bits) and the `action_mask`
marks the view's legal action indices. The environment keeps the most recent event from the
engine's records and passes it in, so agents see exactly what website players see (Plan §3),
and the leak tests on the projection cover the environment too. The hand-only placeholder
from T2.3 is gone, and with it the all-zero observation that PettingZoo's `api_test` warned
about.

**D36 · 2026-10-24 · Agents see a view and a generator, never the seed; fish-env is optional.**
An agent (`fish_agents.base.Agent`) is given its seat's view (`fish_rules.view`) and a random
generator, and returns an action index. It is never given the game seed, which would reveal
the deal. The generator for a decision comes from the game's `bot_policy` stream at index
event number × 6 + seat (`docs/determinism.md` §2); a seat deciding twice before the next
event keeps drawing from the same generator. A game played by seeded agents is therefore
reproduced from its seed alone, and the website's bots (T3.5) draw the same way. Two
games of the same agents on the same deal always play out the same way; an optional agent
seed can be added if an evaluation needs several plays of one deal. `fish_agents.play` runs
six agents in `FishEnv`; fish-env is an optional extra (`env`) of fish-agents, so the server,
which depends on fish-agents for its bots, never installs PettingZoo, Gymnasium or NumPy.
fish-agents joins the other packages at 100% branch coverage in CI.

**D37 · 2026-10-24 · B0 (b0-v1): uniform over legal actions, declaring in a window 1 time in
100.**
`fish_agents.b0.B0` chooses uniformly among its legal actions at every decision, except that
in a declaration window it passes and declares (a uniformly chosen set) only one time in 100.
Uniform play in windows declares about nine times in ten, so almost every window ends in a
call: in 200 measured games not one ask was made, which would leave the H1c placebo nothing
to learn from and the ask paths of the property tests unexercised. At 1 in 100, B0 games
average 35 asks and 7.6 calls, all finished, at about 23 games a second on one core. B0 looks
only at its legal actions and whether a window is open, so its choices reveal its hand only
through which actions are legal; a hand with fewer legal asks makes each of its asks
likelier, so the H1c placebo gain over B2 should be near zero but not exactly zero (T5.5 and
T6.4 must allow for this, for example by comparing against B0's exact action likelihood).
The definition is frozen as `b0-v1` and pinned by five frozen games.

**D38 · 2026-10-24 · The performance smoke: 1,000 B0 games per CI run, numbers kept.**
`scripts/bench_b0.py` plays B0-vs-B0 environment games and reports games per second,
microseconds per legal-mask computation, and the games' mean actions, asks and calls. CI's
performance job plays 1,000 games (about 45 seconds), shows the numbers in the run summary
and uploads them as the `performance` artifact. It fails only if the script fails: timings
vary between runner machines, so a slowdown is read from the trend rather than a fixed
threshold. The game statistics do not vary between machines, so a change in them is a change
in behaviour. First numbers, on the development container: 24 games a second, 16 µs per
mask, 418 actions, 36 asks and 7.6 calls per game.

**D39 · 2026-10-24 · The nightly soak: 100,000 B0 games, every R.9 check, in parallel.**
`scripts/soak_b0.py` plays B0-vs-B0 environment games across worker processes and checks every
state of every game: `check_consistency` (cards conserved, phase and pending state agree), the
R.9 invariants (the turn never falls to a player without cards, the current player can always
act, at most nine calls, the scoring team chooses and a correct call keeps the initiative),
event numbering, a proper end, and that the record replays to the same final state. The
nightly workflow runs 100,000 games on as many processes as the runner has cores. At about 17
checked games a second per core that is roughly 50 minutes on a 2-core runner (the repository
is private) and 25 on a 4-core one (once public), inside the 120-minute limit. It fails on the
first broken game and names its seed, so one command reproduces it. The run summary and a
`soak` artifact keep the numbers.

**D40 · 2026-10-24 · Legal indices are computed directly; per-seat sweeps get a smaller share.**
`fish_rules.action_index.legal_indices` built every legal action and encoded it, with full
input checks: 729 objects whenever a call was being assigned, for every seat at every step.
That was 85% of the cost of building a view. It now computes the indices phase by phase,
directly. Two tests prove it unchanged: at every step of random games the indices decode to
exactly the engine's legal actions, and at every state of every golden game, in every phase,
they equal the encoded legal actions; the frozen action-index, view and observation vectors
pass untouched. Views are 2.7 times faster to build, B0 games 3 times faster (77 a second
on the development container) and a legal mask 10 times faster (1.5 µs). The five test files
that check every seat at every step of whole games now run a fortieth of the profile's
examples (10 in dev, 25 in CI, 1,250 nightly) rather than a tenth; at a tenth, the nightly
profile would have asked them for 5,000 whole games each, past the job's 120-minute limit.

**D41 · 2026-10-24 · The engine is property-tested under website mechanics too.**
Every whole-game property test before T2.5 played environment games: a window after every
event, every seat answering, no timers. The website's mechanics were covered only by unit
tests. `test_website_machine.py` is a Hypothesis state machine that, from any seed,
interleaves Call presses that open windows on any turn, windows closed whoever has answered,
assignment and choice timeouts, legal seat actions, and arbitrary seat actions that may be
illegal. After every step it checks the consistency and R.9 invariants, that the engine
accepts a seat action exactly when its index is legal and that the legal indices equal the
encoded legal actions, and, for every seat, that the view ignores everything hidden from it
and encodes to an observation. At the end the actions must replay to the same final state.
Runs are up to 300 actions, a twentieth of the profile's examples (50 in CI). In 50 runs,
30 reached the end of a game, 21 had a call time out and 25 a choice time out. Letting a seat
that has already voted vote again was caught.

**D42 · 2026-10-24 · Games are checked through their logs, and a frozen digest is compared
across hash seeds.**
A game is its record (seed and actions, R.10.2), so the property tests now replay games from
the record as JSON text, not from the actions in memory: random playout games, finished or
cut short, and every website-mechanics run must replay to the same records and the same
state after every action. `scripts/replay_digest.py` hashes the replays of 300 fixed games
(100 each of playout, B0 and website mechanics: 109,224 actions) into one digest, frozen in
`packages/fish-agents/tests/vectors/replay_digest_v1.json`. CI's determinism job recomputes
it under `PYTHONHASHSEED` 0 and 4242 and compares the outputs, so a change in how any game
plays out, or a dependence on hash order anywhere from the deal to B0's choices, fails the
build. It takes about 10 seconds per run. Reversing the order of the seed tie-break changed
all three kinds' digests.

**D43 · 2026-10-24 · Every hash-seed and nightly run covers all three game packages.**
T2.1 asks for the suite to be run under two `PYTHONHASHSEED` values. CI ran only the
fish-rules tests that way, and the nightly profile only on fish-rules. The determinism job
now runs the fish-rules, fish-env and fish-agents tests under both seeds (about 10 more
seconds each), and a second nightly job runs fish-env and fish-agents at the nightly profile,
apart from the fish-rules job so neither nears its time limit. The server's tests are left
out of both: they hold no game logic yet. The first nightly-profile run of fish-env found a
wrong check in `test_conformance.py`: it required the run-out caller to hold cards, which
R.6.2 does not (R.9 makes run-out its exception). The engine was right; the check now
applies to turns only, and the failing game (seed 1759, policy seed 735) is kept as an
`@example`. `docs/testing.md` describes the whole suite.

**D44 · 2026-10-24 · The corpus design (T1.6).**
`docs/corpus.md` fixes what every website game records before the server writes one. The
log is the seed and the engine actions, each stamped on the server's monotonic clock when
its input arrived and when its update was sent, with its cause (a seat or a timer). Round
trips, rejected inputs, connections, handovers and bot delays are server log rows. Response
time is derived from the log by one function, never stored. Every play and consent table is
append-only; a withdrawal is a new consent row. The held-out cohort is drawn in blocks of 20
sign-ups, 3 per block from a frozen stream, so it is exactly 15% at every multiple of 20. A
game enters the corpus only if it was completed (finished or stopped at 1,000 asks) and
every person who held a seat in it is eligible; one ineligible person removes the whole game,
since their actions are in every other seat's history. The release keeps times relative to
the game's start and the month it was played, under per-release pseudonyms; contact data,
internal ids, wall-clock times and network identifiers never leave the server.

**D45 · 2026-10-25 · The corpus record (`fish-corpus-v1`) and the cohort draw
(`fish-cohort-v1`) live in fish-rules.**
Both are plain data and pure functions, so they sit with the rules, standard library only,
where the server, the research code and anyone reading the released corpus all use the same
definition. A corpus record is a game record plus the game's conditions, its six seats, per
action the received and sent times and the cause (a seat or a timer), and the server log
rows. `read_corpus_record` checks every field and replays the game; `corpus_record` refuses
to write a record that does not read. Response time and the record-level analysis flags are
functions of the record, never stored. Under website mechanics no call-entry freeze falls
inside a decision point (only the caller acts in one, and it ends with the call), so nothing
is subtracted for it. The format is for website games only; T5.4 will define the synthetic
set's. The cohort draw adds a seventh RNG stream, `cohort`, seeded by the cohort seed:
3 positions from a shuffle of each block of 20 sign-ups. Its vectors are checked in Python
and JavaScript.

**D46 · 2026-10-25 · The corpus tables (migration 0003).**
Ten tables and a sequence hold docs/corpus.md §2 to §5, defined once in `fish_server.db` and
created by migration 0003. A test compares the two with Alembic's autogenerate and fails on
any difference. Every table except `player_contacts` gets the append-only triggers, so a
game's ending is a row of its own (`game_endings`) rather than a column filled in later, and
contact addresses are the only rows that can be deleted. Check constraints repeat the
single-row rules of `fish-corpus-v1`; rules that need the whole game stay in
`fish_rules.corpus`. Nothing is stored twice: a note answer is keyed by seat, not person, and
whether a seat was bot-filled follows from its controller. Seeds are `numeric(20,0)`, because
a 64-bit unsigned seed does not fit `bigint`. Tests that named the head revision now read it
from the migration scripts.

**D47 · 2026-10-25 · Corpus membership and export (`fish_server.corpus_export`).**
Membership is one SQL query over the latest consent and age events, run at every export, so a
withdrawal or a new consent changes the next export with nothing edited. A game is exported
only if it ended under the rules, a person played in it, and every person in it is eligible
(and, for `--public`, consented to the release). Each record is built with `corpus_record`,
which reads it back and replays it, so the export stops on any stored game the log cannot
reproduce rather than write it. Release game ids follow start time; pseudonyms are 64 random
bits per person per export, never derived from internal ids, so two releases cannot be linked
by them. The export connects as the server's read-and-insert login. The website-mechanics
game driver moved from the fish-rules tests into `fish_rules.playout` as
`random_website_game`, so both packages' corpus tests use the same games.

**D48 · 2026-10-25 · The datasheet is planned before collection (T1.6 close-out).**
`docs/datasheet-plan.md` takes each question of *Datasheets for Datasets* (Gebru et al.,
2021) and says what answers it and when: most are fixed now by the corpus design, counts
come from the frozen export through `fish_rules.corpus` and are never counted by hand, and
the rest are written at release. Six questions need decisions outside the design (creators
and contact, funding and compensation, the ethics approval reference and impact analysis,
hosting and a DOI, whether older versions stay available after withdrawals, and how long raw
data is kept); they are listed there for T7.1. T1.6 is complete: the design
(`docs/corpus.md`), the record format and cohort draw (D44, D45), the tables (D46), the
membership and export (D47), and this plan.

**D49 · 2026-10-25 · Three packages are published, together, at one version (T2.6).**
fish-rules, fish-env and fish-agents go to PyPI, always released together at the same
version, and each requires its siblings at that minor version (`>=0.1,<0.2`). Alternatives:
independent versions (every combination would need testing, for no user benefit while the
three change together); one package (anyone wanting only the rules would install NumPy and
PettingZoo). Versions follow semantic versioning, so while at 0.x a minor release may change
the interface. fish-server and fish-research carry the `Private :: Do Not Upload` classifier,
which PyPI refuses, so they cannot be published by mistake. Each package's `__version__` is
read from its installed metadata, so there is one place to change it. The packages require
Python 3.14, as developed (D1); supporting older versions would mean CI on each of them, and
waits until someone needs it.

**D50 · 2026-10-25 · The packages are tested the way a stranger installs them.**
`scripts/check_install.py` builds the three packages, runs `twine check --strict`, installs
the wheels into an empty environment outside the repository with everything else from PyPI,
checks each imports from there at its declared version, and runs every Python block of the
READMEs PyPI shows and every example, from an empty folder with `python -I`. It runs in CI on
every pull request. Alternative: rely on the workspace's tests, which run against the
repository itself and so cannot notice a file missing from a wheel, a dependency declared
only in the workspace, or a README example that has stopped working.

**D51 · 2026-10-25 · The release documents itself, and tests hold the documents to the code.**
Four examples (`examples/`) run after `pip install` and in CI. The README is written for a
first-time reader. The Canonical Ruleset is copied into `docs/rules.md`, so the public
repository carries the rules it implements; a test requires it to number exactly the rules
the citation check traces and to carry `RULESET_VERSION`, and the planning document's copy
and this one change together. `CHANGELOG.md` and `CITATION.cff` (CFF 1.2.0) name each
release, and a test requires them to agree with the package version and with each other.

**D52 · 2026-10-25 · Releases are published from a version tag, by trusted publishing.**
Pushing `vX.Y.Z` runs `.github/workflows/release.yml`: it checks that the tagged commit is on
main and that the tag, the three versions, the changelog and the citation agree
(`scripts/check_release.py`); builds the files once, through the install check, and uploads
exactly the files that check installed and ran; publishes them to PyPI with `uv publish`;
then makes a GitHub release with the same files and the changelog entry as its text. PyPI
trusts the workflow through OIDC (trusted publishing). Each package publishes from its own
environment (`pypi-rules`, `pypi-env`, `pypi-agents`), since PyPI accepts only one pending
publisher per workflow and environment; only version tags may use them, and the first waits
for an approval, which covers the other two. Its actions are pinned to commits, since it
holds the right to publish. Alternatives: an API token in the repository's secrets (a
long-lived credential that anything able to read the secret could use); uploading by hand
(not repeatable, and the files would not be the ones CI checked). Uploads skip files already
on PyPI, so a run that fails halfway can be re-run. Running the workflow by hand rehearses a
release without publishing. With this, T2.6 is in place; the release itself is tagging v0.1.0
(`docs/runbooks/release.md`).

**D53 · 2026-10-26 · Layer 1 is exact, and works from one unknown: the deal before what is
remembered.**
Layer 1 (`fish_rules.deduce`, T2.7) names a seat for a card if and only if some deal fits
everything the seat has seen and remembers with the card there. Cards move only in public, so
every remembered fact becomes a constraint on the deal just before the first remembered event,
and full, last-k and no memory are the same computation on shorter runs. It takes a seat's
view and its remembered events, not the game state, so it can only use what the seat was
shown; the public view (no hand) is the same with the hand left out. Alternative: constraint
propagation alone (each fact applied to each card, repeated until nothing changes). That is
what the task's title suggested, but it misses deductions that need counting (three seats,
three cards, two of which can only be with two of them), and B1, RQ1's floor and RQ2's
certain-miss asks all need the exact answer.

**D54 · 2026-10-26 · The solver is one flow with lower bounds and one pass over its residual
graph's components.**
A deal that fits is a flow: each card dealt once, each seat its hand size, each "held one of
these" constraint at least one card. One maximum flow (after the standard reduction of lower
bounds) finds a deal; every other deal differs by residual cycles, so a card can be with a
seat if and only if the flow puts it there or the edge's ends share a strongly connected
component. About 1 ms per deduction, in the standard library. Alternatives: enumerating deals
(far too many); asking a flow, SAT or integer-programming solver about each card and seat
(270 questions where one suffices, and fish-rules takes no dependencies, D2).

**D55 · 2026-10-26 · Exactness is checked by replaying other deals through the engine.**
Besides checking that the truth is always named, the tests take deals that put a card with
another named seat and play the game's own actions from them in the engine, requiring every
public record and the seat's every view to be unchanged. That checks Layer 1 against the
rules themselves rather than against its own list of facts, so a fact the list missed fails
it. The tests were run against four deliberately broken versions first, and caught each. They
take a smaller share of Hypothesis examples than other whole-game tests (a hundred-and-
sixtieth, 312 games nightly) to keep the nightly fish-rules job inside its limit, and a
separate nightly job checks the same on 3,000 B0 games (`scripts/soak_deduce.py`).

**D56 · 2026-10-26 · Layer 1 is used through a tracker, and over records (T2.7 close-out).**
Agents pass their views to `Tracker`, which remembers each event once, keeps the last k when
asked (ready for T2.8's memory wrapper), and starts a new run after a gap, since only an
unbroken run says where cards are. Analysis uses `knowledge` (a seat's deduction at the deal
and after every event, where beliefs are scored) and `certain_misses` (RQ2), both for any
memory length; when a call and its after-call choice come from one action, they are one
decision point. Layer 1 is listed under Unreleased in the changelog and ships in 0.2.0, with
the memory wrapper (T2.8), rather than in a release of its own. T2.7 is complete:
`docs/deduction.md` describes it.

**D57 · 2026-10-27 · k counts events, not views.**
Last-k memory (T2.8) keeps the latest k events: asks, calls and after-call choices. A seat is
shown each event in several views (the window after it, the turn, a call's assignment), and
how many depends on the platform: the environment asks every seat in every window, the
website opens a window only when someone presses Call (R.8.9). Counted in views, the same k
would mean less memory in benchmark games than in corpus games; counted in events, it means
the same on both, and it is what Layer 1's tracker already counts (D56). The corpus's `k`
records events. Alternative: views, the unit an agent is handed; rejected for the reason
above.

**D58 · 2026-10-27 · Memory belongs to the agent, which is shown every view.**
`fish_agents.memory` gives a seat a `Memory` (its remembered events, the view that first
showed each, and Layer 1 from exactly those), and `Remembering(agent, setting)` makes an agent
with `act(view, memory, rng)` an ordinary `Agent` with one memory per seat. To remember events
others cause, an agent must see views it does not act on, so `Observer` (`observe(view)`) is
added and `play_game` shows every observer its seat's view after every action; this draws no
randomness, so an agent that ignores its memory plays B0's games exactly. Like the tracker,
memory keeps an unbroken run and starts again after a missed view. The module needs only
fish-rules, so the server's bots can use it (T3.5). Alternatives: replaying the game's records
for the agent (it would see more than it was shown if it missed views, and the server has no
such records for a bot); keeping memory in the engine (Plan §3: memory is the player's, and
the rules must be the same under every setting).

**D59 · 2026-10-27 · The environment puts memory in `infos`, not in the observation space.**
`fish_env.memory_env(remembered)` adds, to each agent's `infos` entry, the observations it had
just after each event it remembers: `int8`, shape `(n, 648)`, oldest first. The observation
and action spaces stay `fish_env.env()`'s, so policies and conformance tests written for it
run unchanged, and a learner chooses its own encoding of the past (stacked, recurrent,
attention). Alternatives: a fixed-shape stacked observation (full memory has no bound, and a
padded maximum would be most of every observation); a Gymnasium `Sequence` space (poorly
supported by PettingZoo's tests and by learning libraries).

**D60 · 2026-10-27 · 0.2.0: Layer 1 and memory (T2.8 close-out).**
T2.7's deduction and T2.8's memory are released together as 0.2.0, as D56 planned; the three
packages require each other at 0.2. No frozen encoding changed, so 0.1.0's games replay
identically. The code supports every Python 3.14 release: CI's 3.14.0 refuses the slotted,
frozen dataclass form for classes with no fields, so the four field-less control actions
declare empty `__slots__` themselves. T2.8 is complete: `docs/memory.md` describes it.

**D61 · 2026-10-28 · The table: the website's mechanics around the engine, on a passed-in clock.**
`fish_server.table` turns presses, seat actions, connections and the passing of time into
engine actions and log rows; it reads no clock and does no input or output, so every website
rule is tested at exact times (T3.1). A press names its set, so it is one input: `OpenWindow`
and the presser's `Declare` together. A timer's outcome is recorded at its deadline, not when
it was noticed, and every input first fires the timers due by its arrival, so the log holds
things in the order they happened on the server clock (R.8.5). On a turn the current player
may only ask: R.4.3 makes the website's calls start with a press. The turn timer stops for a
window, an assignment or a choice instead of pausing, because on the website each of them
ends in a new turn, which starts a fresh 60 seconds (R.8.4). Alternatives: timers as asyncio
tasks that apply their action when they wake (the recorded time would be when the loop got to
it, and tests would need real time); letting the current player send `Call` on a turn (the
engine allows it, but the website's rules route every call through a window).

**D62 · 2026-10-28 · People start out waiting to connect; handovers release their person.**
A person has the same 30 seconds to connect at the deal as to reconnect later, so a seat
whose player never arrives is handed over rather than stalling the table; when the turn timer
and the reconnection run out together, the turn timeout is the reason recorded. The table is
given the bot that replaces people (`Controller`); until T3.5 brings B1 and its delays
(R.8.8) it is a stand-in, `b0-v1`, that waits 2 seconds and chooses among the actions the
website allows. A person whose seat is handed over is told once and released to the lobby,
since R.8.4 says they do not reclaim it. Alternatives: waiting for every player before the
deal (one missing player would hold five); keeping the person attached as a spectator (they
could not play again until the game ended).

**D63 · 2026-10-28 · Protocol 2: action indices, the website's own lists, strict parsing.**
Seat actions travel as `fish-action-index-v1` indices from the player's own seat, so the
client needs no rules and the encoding is the frozen one agents use. Each `update` carries
the view exactly as `fish-view-v1` (D33; the `View` model is checked against all 124 vectors
and every view of random games) plus `actions` and `pressable`, the website's lists, because
the view's `legal` is the environment's mask, with direct calls and passes. Timers travel as
milliseconds left, since the client's clock is not the server's. Client messages are parsed
strictly: no strings for numbers, no booleans, no unknown fields. A table's start is its
first `update`, not a message of its own. Alternatives: actions as `fish-actions-v1` objects
(more to validate, and a second encoding for the client to build); changing `fish-view-v1`
to carry the website's lists (it is frozen, and the environment shares it).

**D64 · 2026-10-28 · Sign-in by emailed link, sent through Resend.**
No passwords: a link, valid once for 15 minutes, starts a 30-day session in an `HttpOnly`
cookie. The link opens a page with one button, because mail scanners open links by
themselves and would use them up. Only SHA-256 hashes of links and sessions are stored, and
since the server's login may only insert (D15), using a link and ending a session are rows of
their own, made at most once by a primary key. The first sign-in makes the player and draws
the cohort at once (corpus.md §2.1); a transaction lock on the address keeps two first
sign-ins from making two players. Sign-in tables, like contact addresses, are `PRIVATE`:
never exported, and removable. Email goes through Resend (a sending subdomain,
`mail.thedefinitivesanjeevexperience.com`; free for 3,000 a month and 100 a day), called with
the standard library, with limits of 3 links per address in 15 minutes, 10 requests per
network address an hour and 90 emails a day. Alternatives: Amazon SES (cheaper at volume, but
an AWS account and a sandbox to leave); Postmark ($15 a month); passwords (resets need email
anyway, and a password store is a liability); a link that signs in on opening (scanners).

**D65 · 2026-10-28 · Matchmaking: two solo queues, rooms by code, seats drawn at random.**
The solo queue is two queues, the held-out cohort's and everyone else's, so cohort players
meet only each other and a table from the cohort queue is a cohort table (corpus.md §2.1).
Groups use six-character room codes without look-alike characters; a group table is never a
cohort table, so mixed games stay out of the cohort test set (§6). A table forms as soon as
six wait together, from those who waited longest. Seats and seeds come from the operating
system's randomness, so nobody can choose a partner or predict a deal. Alternatives: one
queue with cohort players skipped over (the same result, harder to reason about); seating in
join order (friends who join together would be partners).

**D66 · 2026-10-28 · One process, games in memory, each game one task.**
The server runs as one process with one event loop (D10's single $7 instance). Each game is
one task that takes its inputs from a queue in the order they arrive and stamps each with the
server clock as it takes it, so R.8.7's "in the order it receives them" holds by construction,
and sleeps until the next timer, bot action or ping. Each connection sends from its own queue,
so a slow client delays nobody; an action counts as sent once its update is in every
connected seat's queue (corpus.md §5.1). Rows are written in order by one writer per game,
from a thread, so the database never blocks the loop. A restart ends games in progress; their
rows stay without an ending, for T3.2 to mark abandoned. This settles T2.1's open question of
how game state and queues are held. Alternatives: game state in the database or Redis, to
survive restarts and allow several processes (much more machinery for a pilot of a few
tables, and every action would wait on a round trip); a lock around a shared state instead of
a task per game (ordering by lock acquisition is not arrival order).

**D67 · 2026-10-28 · T3.1 close-out: a whole game, end to end, as the test of the server.**
`test_end_to_end.py` starts the real server on a real port; six scripted players sign in by
cookie, are matched by the solo queue, play a whole game over real WebSockets, answering
pings; and the corpus export reads the game back from the database as a `fish-corpus-v1`
record that replays to the same end, with response times and round trips. It takes about ten
seconds, mostly declaration windows. R.8.4 and R.8.5 are now cited by tests; R.2.5, R.2.6
(T3.4) and R.8.8 (T3.5) remain owed. `scripts/try_server.py` checks a deployed server the way
a player reaches it. T3.1 is complete: `docs/server.md` describes it.

**D68 · 2026-10-28 · Consent as the approved documents set it: per seat, with withdrawals.**
T1.6's consent design (D44 to D47) did not follow the approved Consent Screen (§3) and
Research Plan (§6): it kept each player's latest consent and age events, with fields the
screen does not ask for (`research_use`, `public_release`, `no_notes`) and none for US
residence, made a withdrawal a consent row that a later acceptance would undo, and decided
membership at export from each player's latest events, so a game could not say which text
its players had accepted. Migration 0005 replaces it before any study data exists:
`consents` holds each acceptance with the screen's version and its three confirmations;
`withdrawals` is a record of its own, with its channel; and `seat_consents` copies each
person's latest acceptance onto their seat when the game starts. A corpus game is one whose
every person's seat has flags and none of whose people has withdrawn. Everyone who plays has
agreed to the CC BY 4.0 release, so the export has no separate public mode. Alternative:
keeping T1.6's tables and rewording the approved documents to match (they were approved as
written, and the seat flags are what lets a game show the consent it was played under).

**D69 · 2026-10-28 · The corpus record carries the seat flags: `fish-corpus-v2`.**
The Research Plan (§6) lists each seat's consent, age-eligibility, residence and
outside-communication flags among what is released, so each person's seat in the record has
`consent`: the version of the text and the three confirmations, all true, as copied when the
game started (D68); a bot's seat has `null`. The reader refuses a person's seat without them.
Adding a field changes the record's shape, so the format takes a new name (D45), and
`fish-corpus-v1` is retired: no game was recorded in it, so nothing has to read it. It ships
in fish-rules' next release. Alternative: leaving the flags out and representing consent only
by membership (a released game could not show what its players had accepted).

**D70 · 2026-10-28 · The acceptance travels with the sign-in link; only those who may play wait.**
The consent screen comes before the email field (Consent Screen §2), so a new person accepts
before they are a player. The version they accepted travels with their sign-in link and
becomes a row of `consents` when the link is used: nothing about them is stored before they
press Continue, and nothing at all if they never use the link. A signed-in player accepts a
new version with `POST /consent`; the site shows one version, set by `FISH_CONSENT_VERSION`
(`v1.0`, or `v1.0-pilot` on staging), and the server refuses an acceptance of any other or
with a box unticked. Withdrawing is `POST /withdraw` with a JSON confirmation, or
`python -m fish_server.withdraw` for a request by email; it is recorded once. The lobby lets in
only a player who has accepted the current version and not withdrawn: a withdrawn player's
new games would leave the corpus and take five other people's games with them. JSON bodies
also keep other sites from submitting these forms for a signed-in player. Alternatives:
recording the acceptance on Continue before the email (it would belong to nobody, or need a
cookie before consent); letting a withdrawn player play on (the cost falls on others).

**D71 · 2026-10-28 · Games that cannot go on end `abandoned`, and a log never has a gap.**
A game in the server's memory ends early in three ways, each recorded as `abandoned`
(corpus.md §3) and told to its players. On shutdown (a deploy, a restart) the server stops
every game, writes its rows and its ending. A write that fails is retried for about a minute,
enough for a database restart or failover; if it never succeeds the game is stopped and
nothing more of it is written, because a later row after a missing one would make a log that
cannot replay. A crash leaves a game with no ending, so at start and every minute the server
marks `abandoned` each game with no ending, not running in it, that has written nothing for
five minutes: a live game writes a round trip per person every 5 seconds and its bots act
every few seconds, so during a deploy, when the old server still runs its games, none of them
is caught. Before any ending is written the stored actions are counted and their numbers
checked; a game with a gap ends `abandoned`, since the export would otherwise stop on it.
Alternatives: marking every game without an ending at start (it would abandon the old
server's live games during a zero-downtime deploy); recording which process runs each game
(a column on an append-only table for something a quiet-time rule settles); buffering rows in
memory without limit while the database is down (a crash would lose them, and the game would
go on unrecorded).

**D72 · 2026-10-28 · The note-taking question: protocol 3, asked of those still seated.**
When the rules end a game, the server asks each person who still holds their seat and is
connected "Did you take notes during this game?" (`note_question`, question `v1`), and writes
their `note_answer` (`yes`, `no` or `declined`) for that seat, once. The question waits for an
answer only while the player stays connected and does not start another game; otherwise the
seat is `unanswered`, as corpus.md §4.2 counts it. A person a bot replaced is not asked: their
seat's play was partly the bot's, and the handover already flags the game. Abandoned games ask
nothing, since they never enter the corpus. The two messages change the protocol, now
version 3. Alternatives: asking everyone who ever held a seat (the released person may be
playing another game by then); asking before the final update (the game's end would wait on
the answer).

**D73 · 2026-10-28 · T3.2 close-out: the website end to end, consent to corpus.**
`test_end_to_end.py` now reaches the real server as a browser would: six people accept the
consent screen, ask for a sign-in link over HTTP, use it, connect with the cookie, are
matched by the solo queue, play a whole game and answer the note-taking question; the export
reads the game back with every seat's consent flags and note, and leaves it out once one of
them withdraws on the website. A second test stops the server mid-game as a deploy does.
uvicorn closes every WebSocket with 1012 (service restart) before the app's shutdown runs,
so players learn of a restart from that code, which the client (T3.4) shows, not from a
message; the game then ends `abandoned`, as D71 says. T3.2 is complete: the consent
redesign (D68–D70), endings and the log (D71), and the note-taking question (D72) are in
`docs/server.md` and `docs/corpus.md`.

**D74 · 2026-11-01 · The age gate is the consent screen's first confirmation.**
T3.3 was planned as "Age gate (all participants 18+)". Under the approved Consent Screen it is
the first of the three confirmations: "I live in the United States and I am a legal adult
where I live: 18 or older (19 or older in Alabama or Nebraska; 21 or older in Mississippi)".
Nobody plays without ticking it (D70), and the server stores it with every acceptance and
copies it to every seat (D68, D69). No birth date is asked: the text promises that we never
collect age, and a date would add a record to protect without making the attestation any
truer. Alternative: a birth-date field (collects what the consent text says we do not).

**D75 · 2026-11-01 · The server serves the web client.**
The image builds the client in a Node stage and keeps only `client/dist`; `fish_server.pages`
answers `/`, `/account` and `/information` with its `index.html` (never cached) and serves
`/assets/` (cached for good: the names carry a hash of the contents). Every other path is
404, so a mistyped endpoint is never answered with a page; the client's list of pages and the
server's are checked against each other. One service and one address keep the `HttpOnly`
session cookie working with nothing to configure, and the sign-in link's redirect to `/` now
lands on the client. Locally, Vite serves the live client and forwards the server's paths.
Alternatives: a separate static site (a second service, and cross-site cookies); serving the
client for every unknown path (a typo in an endpoint would answer 200 with a page).

**D76 · 2026-11-01 · The study texts live in the client, word for word, by version.**
`client/src/study/texts.ts` holds each text as typed data, and the pilot is built from the
same sentences as v1.0 with exactly the eight parts of Consent Screen §4 swapped, so the rest
is word for word by construction; both were compared line by line with the approved doc. A
version is never edited (typo fixes aside), so anyone can reread exactly what they accepted.
`versions.json` beside the texts and `fish_server.study` list the same versions and last days,
and tests on both sides check that they agree; the server refuses to start with a
`FISH_CONSENT_VERSION` it has no text for. Alternatives: Markdown files rendered at run time
(a parser, and a second shape to keep in step); the server sending the text (an old version
would still have to be kept somewhere, and the client could not check it).

**D77 · 2026-11-01 · Withdrawing on the website closes at the end of the text's last day.**
"You can withdraw until 14 February 2027" (31 March 2027 for the pilot) is read as the end of
that day in US Eastern time, where the study runs. `GET /study` says the day and whether
withdrawing is open; after it the account page shows when it closed instead of the button,
and `POST /withdraw` answers 409. A request by email has no deadline in code: the researcher
decides, as Consent Screen §3 allows for the extra games in March. Alternative: midnight UTC
(seven hours early for every participant).

**D78 · 2026-11-01 · Returning players accept again; T3.3 close-out.**
Anyone without a session sees the consent screen, so a returning player whose session has
expired ticks the boxes again and the new acceptance rides their sign-in link: one more row of
`consents`, and no way to sign in without an acceptance. A signed-in player whose accepted
text is not the one shown accepts the new one with `POST /consent` before their next game.
The account page's withdrawal asks for confirmation in words true under both texts. The
website is tested end to end in Chromium (`test_browser.py`, marked `browser`, run by
`check.sh` and CI after the client is built): the key points fit on the first screen at phone
width in both texts and colour schemes, and one person accepts, signs in, rereads, withdraws
and signs out, with the database checked at each step. Alternative: a "Sign in" shortcut for
returning players (a new person could make an account without accepting).

**D79 · 2026-11-02 · Game nights: Sundays for everyone, alternate Wednesdays for each group.**
Tables of six fill only when people come at once, so the study has scheduled nights (Research
Plan §3; docs/recruitment.md §3): every Sunday, 8–10 pm Eastern, from 13 December to
14 February, and every other Wednesday for each of the two groups, none on 24–25 December or
31 December – 1 January. The held-out cohort is about 15% of sign-ups and plays only with
itself, so it needs nights of its own; giving the other group alternate Wednesdays too means
every player is told of "your group's game nights", and nobody learns which group is held out.
The pace is 110 corpus games a week; two full weeks short add a Friday night. Alternatives:
cohort-only nights announced as such (it would tell people their group); one weekly night
(the cohort's tables would rarely fill).

**D80 · 2026-11-02 · Each site has one address of its own, and `onrender.com` is switched off.**
Invitations link to `fish.` (the study) and `fish-pilot.` (the pilot, on staging) under the
researcher's domain, sign-in links point there (`FISH_PUBLIC_URL`), and the Render address
answers 404 (`renderSubdomainPolicy: disabled`). A second address for the same site would
split people's sessions between them, and an unfamiliar `onrender.com` link in an email reads
as a phishing attempt. `test_blueprint.py` holds each service's `FISH_PUBLIC_URL` to its one
domain. Alternative: keeping both addresses and redirecting in the server (more code for the
same result).

**D81 · 2026-11-02 · Invitations are sent word for word from the recruitment page.**
Every message is in docs/recruitment.md before it is sent, and `scripts/broadcast.py` takes
its words from there and nowhere else, so what was sent is what the datasheet can quote. It
sends only to the lists a message's heading names (or a Test list), refuses anything left
unfilled, builds each week's game nights from the schedule (whose weekdays it checks), and
makes a draft unless told to schedule. Bulk email goes through Resend Broadcasts from its own
subdomain, `news.`, with an unsubscribe link, so that complaints about invitations cannot slow
sign-in links from `mail.`. The full-access key it needs stays in the researcher's keychain.
Alternatives: pasting messages into Resend's editor (the sent words could drift from the
page); sending from a personal Gmail (about 500 a day, and the spam folder).

**D82 · 2026-11-02 · Players reach the game-night lists from the Render Shell, by group.**
Only the study database knows who has accepted, who has withdrawn and who is in the cohort,
and it is reachable only inside Render, so `python -m fish_server.audience` runs in the
production Shell before each Monday's email. It puts each player in their group's segment and
takes everyone who withdrew out of every list, invitations included, so no one is invited to
play who can no longer play. It never changes a subscription: an unsubscribed contact stays
unsubscribed. The key is typed at a prompt and never stored on the server, and it prints
counts, never addresses. The pilot site refuses it. Alternatives: a full-access key in the
server's settings (a leaked server would expose the contact lists); exporting a CSV of
addresses to the researcher's computer (another copy of the email list to delete).

**D83 · 2026-11-02 · Progress is counted as the export counts; T4.1 close-out.**
`python -m fish_server.stats` counts corpus games with the export's own membership rule
(`corpus_export.membership`, now shared), so a withdrawal lowers past weeks as it lowers the
corpus, and reports each Eastern week's pace against 110, bot handovers (T4.4) and, on the
pilot site, how long games take (M3's `{N}`). T4.1's tools are complete: the schedule and
messages (D79, D81), the sites' addresses (D80), the lists (D82) and the counts; recruitment
itself runs from 16 November to 9 February as docs/recruitment.md §2 sets out.

**D84 · 2026-11-02 · Three Resend lists, not five (changes D81, D82).**
Resend's free marketing plan allows three segments. The Test list goes, since each draft can
send a test copy to the researcher ("Send test email"), and the Gov School and Pool lists
become one, `Invited`: until 7 December it holds only the Gov School group, which is exactly
who M1 and M2 are for, and the rest of the pool joins it before M3. Every later invitation is
then one broadcast to one list, so someone on both of the researcher's lists is one contact
and gets each message once. The Players lists stay two, because each group has its own
Wednesday nights. `scripts/broadcast.py` sends a message only to its heading's list, and
`python -m fish_server.audience` takes withdrawn players out of `Invited`. About 950 people
are invited in all, chosen from the willing pool, so the free plan's 1,000 contacts also hold
every invitation and every player. Alternative: the paid marketing plan, for more segments
and the whole pool of about 5,000 (more invitations than the study needs to manage).

**D85 · 2026-11-02 · B1 (b1-v1) calls only what it can prove, at every memory setting.**
B1 calls a set exactly when Layer 1 shows all six cards with its team, asks the likeliest ask
with each card's possible holders weighted equally, and breaks only ties with its generator;
on the website, `would_call` presses Call for the same certain calls (R.8.8). With little
memory such calls are rare, so six B1s often reach 1,000 asks: in 10 games each, all
finished at full memory, 5 at last-8, 4 at last-2 and none with no memory, while against three
B0s B1 finished and won every game at every setting. T6.7 reports the finished share at each
setting, and the website should end a game once only bots are left (T3.5), so no B1-only table
plays on to 1,000 asks. The definition is frozen as `b1-v1`, pinned by five games. Alternative:
also calling when the chance of being right (equal weights) clears a fixed bar. Games then
finished more often, but at 1/16 and 1/64 full-memory B1 beat B0 only 5 and 4 times in 10,
every call could be wrong, and the bar would be a free parameter of the baseline.

**D86 · 2026-11-02 · B1 is evaluated nightly, at four memory settings, against three opponents.**
`scripts/eval_b1.py` plays B1 with full, last-8, last-2 and no memory against three B0s,
against three full-memory B1s (each seed played with B1 as either team, so seat and first
player cancel out) and against itself, 200 seeds each, and reports finished games, B1's win
share of the finished ones with a 95% Wilson interval, asks, and its proved and forced calls.
The same run is the soak: every game gets the B0 soak's R.9 checks (`check_record`, now
shared) and a replayed record, and a call B1 proved that was wrong fails the night. Win
shares count finished games only, since R.8.2 excludes the rest. In 40 seeds, B1 won every
game against B0 at every setting and lost every game to full-memory B1 at every lower one, and
every proved call was right. Alternative: a separate soak of B1 self-play. It would check
fewer kinds of game than the evaluation already plays.

**D87 · 2026-11-02 · T5.2 close-out: B1 is ready for the website's bots.**
B1 (`b1-v1`) decides from Layer 1 alone (D85), is pinned by five games, presses Call on the
website through `would_call`, takes about 1.2 ms a decision (the performance smoke), and is
evaluated and checked every night (D86). What T3.5 takes from it: `b1(MemorySetting.last_k(k))`
as the bot, shown every view; `would_call` after every event, with the decision dropped if a
window, assignment or choice has begun when its delay ends (R.8.8); and the draws of both from
the seat's `bot_policy` generator, so a website game's bots replay from its seed. The value of
k, and what happens to a game with no people left, are T3.5's to settle.

**D88 · 2026-11-03 · The client names cards and action numbers itself, checked against the
frozen vectors.**
The game screens (T3.4) show cards and offer the actions in `update.actions`, so the client
reads action numbers (`fish-action-index-v1`) and card numbers (§6 of determinism.md) in
`client/src/game`. It decides nothing: which actions a player may take still comes only from
the server. Its tests read `action_index_v1.json` and `deal_v1.json` from fish-rules' vectors
(through `import.meta.glob`, so the image's client build, which has only `client/`, never
needs them) and check all 913 numbers for a seat on each team, both ways. Alternative: the
server sending each action already described. It would make every update several times
larger, for what a hundred lines of client code and a frozen layout give.

**D89 · 2026-11-03 · One game connection per page, drawn a message at a time, retried for
30 seconds.**
`client/src/game/connection.ts` holds the page's one WebSocket to `/ws`: it sends
`client_hello` with its own `PROTOCOL_VERSION` (a server test checks it matches), answers each
`ping` before anything is drawn, and keeps the latest lobby, update, question, rejection and
error. `useGame` draws each message with `flushSync`, so two messages that arrive back to back
are both shown rather than batched into one render (R.2.6; T3.7 checks the client adds no
delay). A connection that drops is tried again after 1, 2, 4, 8 and 15 seconds, 30 in all, the
time a seat is held (R.8.4); the server then sends the game where it stands. It is not tried
again when the server refused it (1008: signed out, or an older page, which must reload) or
closed it because Fish was opened elsewhere (1000), so two tabs never take a game back and
forth. A restart (1012) says so. Alternative: retrying forever. A player whose seat has gone
to a bot gains nothing from it, and an idle tab would keep reconnecting.

**D90 · 2026-11-03 · The table shows seats 1 to 6, from the player's side, and only the latest
event.**
On screen, seats are numbered 1 to 6 (seat 0 in the data is "1") and named from the player's
side: "You", "Teammate 3", "Opponent 5", so no one needs to know the data's numbering, and
the study collects no names to show instead. The other team's three seats sit above the
player's team, each with its hand size, a "bot" label where a bot plays it (never which
kind), and, at the current player's seat, the turn timer (R.2.6). Below them is the most
recent event in one sentence, with a call's six true holders (R.2.3), and nothing older
(R.2.2); then what the game waits for, where a window says only that a call was declared
(R.8.3). Timers count down on the device's clock from the `ms_left` of the latest update,
so each update corrects any drift. Alternative: seats drawn around an oval table. It does not
fit a phone's width with six names, hand sizes and a timer.

**D91 · 2026-11-03 · Every action is chosen, then confirmed, from what the server offers.**
The table offers exactly `update.actions` and `update.pressable` (`client/src/game/offers.ts`),
sorted into asks by opponent, a call to assign, teammates to choose or vote for, and sets to
name in run-out or to press Call on. An ask is a target, then a card, then "Ask Opponent 4 for
the 5♣"; Call is a set, then "Call Low clubs (2–7)", and the press carries the last event the
player saw (R.8.7). A call's six cards are a grid, one row per card and one column per
teammate, with the player's own cards already theirs, and "Make the call" waits for all six
(R.4.3). Once something is sent, the buttons wait for the next update or a rejection, so a
double tap sends it once; a rejection says why in plain words, and a discarded action says a
call was declared first (R.8.3). Alternative: acting on the first tap. A mistaken ask passes
the turn and a mistaken call scores the set for the other team, so one more tap is worth it.

**D92 · 2026-11-03 · After a game: how it ended, then the question, then the lobby.**
When the server sends a player back to the lobby, the client keeps the game's last update to
say how it ended: the result and the sets each team scored; that a bot took over their seat
(their seat among the update's bots, R.8.4); or that the game had to stop, in the words of the
error the server sent at the table. The note-taking question comes next, in the server's own
text, with "Yes", "No" and "Prefer not to say" (`declined`), and the lobby waits until it is
answered, so a player who goes on playing has always been asked (docs/corpus.md §4.2). The
ending stays above the lobby until the player asks for a table. Alternative: a lobby button
beside the question. A player leaving would then go unasked, and `unanswered` is meant for
people who close the page.

**D93 · 2026-11-03 · A room has a link as well as a code; T3.4 close-out.**
The consent text says the study records "whether you joined a game through a link shared
with friends", so a room shows a link, `/?room=CODE`, beside its code, with *Copy link*. The
link opens the front page; once signed in, the lobby has the code filled in and the player
presses *Join*, after which the code leaves the address so a reload does not use it again.
Someone signing in for the first time arrives from the emailed link on a fresh page, without
the code, and opens the room link again or types it. A group game is flagged the same however its players joined. T3.4 is complete: the lobby, the
table, every action, the end of a game and the connection (D88 to D92), described in
`docs/client.md`, and played end to end by six people in a browser on every CI run.
Alternative: joining as soon as the link opens. A link sent to the wrong person would seat
them at once; one tap on *Join* costs little.

**D94 · 2026-11-03 · Bot waits come from the seed, and every one is recorded.**
R.8.8 has bots wait 1.5 to 4 seconds before every action and every Call press until pilot
data exists. `fish_server.bots` draws each wait uniformly, in whole microseconds, from the
game's `bot_delay` stream at event number x 6 + seat (determinism.md §2), so a game's bot
timing follows from its seed like everything else in it. Each wait is a `bot_delay` row when
it ends: not dropped if the bot then acted, dropped if the game moved on first (a press opened
a window, a timer fired), and the bot then waits afresh for the new state. Alternative: a
wait drawn from the operating system. The bots' timing could then not be reproduced, and
RQ1's sensitivity set includes games with bot seats.

**D95 · 2026-11-03 · The website's bot is B1 remembering the latest 8 events, from the moment
it takes the seat.**
A person who is away for 30 seconds or lets the turn timer run out is replaced by `b1-v1`
with last-8 memory (R.8.4; T3.5), and the handover row records exactly that. Bots only ever
replace people: a table still needs six to start (Research Plan §5). Eight events is about a
round of the table; in T5.2's evaluation B1 at last-8 beat B0 in every game and lost every
game to full-memory B1. The bot is shown every view its seat is shown from the moment it
takes it, as a player sitting down would be, not the events before. It chooses among the
actions the website allows, passed to B1 as the view's legal actions, so on a turn it asks
(a call starts with a press, R.4.3), and its random choices come from the game's
`bot_policy` stream (`fish_agents.PolicyStreams`), so a game replays from its seed with the
bots' play in it. Alternatives: full memory, which no person playing without notes has;
and handing the bot the person's last views, which no player taking a seat would get.

**D96 · 2026-11-03 · A bot presses Call only for a call it can prove, decided after every
event.**
R.8.8 has each bot decide after every event whether to declare. The website's B1 decides
with `would_call`, which names a set only when what it remembers proves all six cards are
with its team, and only on a turn; it decides too on taking a seat. The press waits its
delay and is made only if the decision is still about the current events and no window,
assignment, choice or run-out is in progress, so a decision another event overtook (even a
bot's own ask in the same instant) is dropped and made afresh. This also covers R.9 on the
website: a turn offers only asks, and a player with no ask holds only whole sets, which B1
always proves. Every call a bot pressed for in the random server games is right. Alternative:
pressing for calls B1 thinks likely. That is not the B1 frozen in D85, and a wrong call by a
bot scores a set for the other team in a game people are playing.

**D97 · 2026-11-03 · A game nobody is left in ends abandoned.**
When a bot replaces the last person at a table (R.8.4), the game stops in that instant, no bot
acting after, and is written `abandoned`, like a game a restart stopped (corpus.md §3). Nobody
is watching it; six B1s with last-8 memory reach 1,000 asks in a third to a half of their games
(D85, D86), which would hold a game open for an hour; and it could not enter RQ2's set, which
has no handovers. No rule changes: R.8.4 hands the seat to a bot, and stopping a game is the
server's, not the rules'. Alternative: playing it out at bot speed, for RQ1's sensitivity set.
Its last part would be bots alone, whose actions are not scored, at the cost of a game's worth
of server time.

**D98 · 2026-11-03 · T3.5 close-out: B1 replaces people on the website.**
A person away for 30 seconds or out of turn time is replaced by `b1-v1` with last-8 memory
(D95), which waits 1.5 to 4 seconds from the seed before each action and press (D94),
presses Call only for calls it can prove (D96), and a game it is left alone in ends
`abandoned` (D97). Bots never fill an empty seat: a table needs six people (Research Plan
§5), so the corpus's `bot_filled` is never true for a website game, and RQ1's bot-seat
sensitivity set is the games with a handover. Checked by `test_bots.py`, `test_game.py`
(and nightly, 1,250 whole games), and end to end over real sockets with a person who leaves.
The pilot's response times (T4.2) will replace the uniform waits; only `draw_delay` changes.

**D99 · 2026-11-03 · Coming back: the game as it stands, or a word on what happened.**
A person who reconnects within the 30 seconds of R.8.4 is sent their seat's update at once,
the same as anyone's after a change: the view, the actions and presses open to them, and the
timers, the turn timer not restarted, so being away never buys time. The view holds only the
latest event (R.2.2), so nothing they missed is replayed. A person released while away, by a
handover or by their game ending, has no connection to be told on, so the hub keeps one line
for them ("A bot took over your seat while you were away…", "Your game ended while you were
away.") and sends it once when they next connect, before the lobby; the page shows it where
it shows how a game ended. Tested over real WebSockets on a turn, mid-assignment and
mid-vote. Alternative: saying nothing, which left a returning player at the lobby with the
page guessing that the game "had to stop".

**D100 · 2026-11-03 · Simultaneous calls are checked over real sockets.**
Six people press Call on one set in the same instant, sent together over real WebSockets to
the real server: the server opens one window for the first press to arrive and takes the
rest as declarations in it (R.8.3), and when it closes the call that proceeds is the first of
the declarers in `priority_order(seed, window)` (R.8.1), which the test computes itself from
the game's seed. Arrival order varies from run to run and the caller is usually not the
first to arrive, so a server that went by arrival would fail. The same test sends an ask
inside the window (discarded, its sender told) and a press that had not seen an ask moving
a card of its set (stale, R.8.7), and replays the recorded actions to the same call. No
change to the server was needed.

**D101 · 2026-11-03 · Uptime: two keyword checks per site, every 5 minutes, by email.**
UptimeRobot's free plan checks each site from outside Render every 5 minutes and emails
when a check fails and when it recovers. There are two checks per site: `/health` for the
server and `/health/db` for its database. The server stays up when the database doesn't,
and Render's own health check deliberately ignores the database (it must not restart a
working server over it). Both are keyword checks (`"status":"ok"`, `"database":"ok"`), so a
200 from something other than this server still fails. `scripts/try_server.py` now checks
`/health/db` too, including that the database is at the checkout's newest migration, which
shows whether a deploy finished. What to do on an alert is `docs/runbooks/monitoring.md`.
Alternatives: Render's notifications alone, which report failed deploys but not an outside
view of the site or a database the server can't reach; a paid plan with 1-minute checks,
which a study with scheduled game nights doesn't need.

**D102 · 2026-11-03 · The export writes one game at a time.**
`fish_server.corpus_export` used to build every record before writing any. A test game is
about 18 KB of JSON and 64 KB in memory, and a real 20 to 30 minute game, with a round-trip
row per seat every 5 seconds, is likely to be 15 to 20 times that. At the 1,000-game target,
building the whole export at once would need about a gigabyte, on the server's 512 MB instance,
during the study, beside games in progress. Now `records` yields one record at a time and
`main` writes each as it comes. It writes under a temporary name, renamed when complete (a
failed export still leaves no file), gzips a `.gz` name, and prints the file's SHA-256.
`export` still returns a list, for tests. The restore drill builds the export the same way.

**D103 · 2026-11-03 · Backups: Render's three days, and one weekly corpus copy on the laptop.**
Render's point-in-time recovery restores the whole database, but only to the last 3 days on
the Hobby workspace (D14). A fault noticed later would lose everything before it. So each
Monday from 14 December to 15 February, the corpus export is copied to the researcher's
laptop. It is made in the production Shell, copied with `scp -s` over Render's SSH (the image
now has OpenSSH's server and SFTP server, which Render needs for SSH into a Docker service),
and checked there with `scripts/check_export.py` (every game replays; the count and SHA-256
match the server's). The folder is FileVault-encrypted, owner-only and excluded from Time
Machine, and only the latest copy is kept, so a withdrawal leaves it within a week. It is
deleted by 30 June 2027 (`docs/runbooks/backups.md`). The copy is the corpus only:
pseudonymized, with no addresses or ids. It can't rebuild the database, and a withdrawal
made after it can't be found in it.
The restore drill now also checks the restored copy: at least as many rows in every
append-only table as at the marker, and an export that builds. Alternatives: a database dump
on the laptop, which would put email addresses there; an export download page on the site,
which would expose the whole corpus to the web; opening the database to the laptop's address,
which `ipAllowList: []` rules out.

**D104 · 2026-11-03 · T3.6 close-out: the website is ready for real players to drop out, race and lose a server.**
- **Coming back** (D99): a person who reconnects within 30 seconds sees the game as it stands,
  their turn timer not restarted. A person released while away is told why when they next
  connect. Tested over real WebSockets on a turn, mid-call and mid-vote, and in Chromium with
  the connection cut and restored.
- **Simultaneous calls** (D100): six presses in one instant open one window, and R.8.1's
  priority order, not arrival, decides the call. Tested over real sockets.
- **Monitoring** (D101): UptimeRobot checks `/health` and `/health/db` every 5 minutes and
  sends email alerts.
- **Backups** (D102, D103): Render's point-in-time recovery for the last 3 days, a restore
  drill that now also checks every append-only table and the export on the restored copy, and
  one weekly corpus copy on the laptop. The export writes one game at a time.

Three steps are done by hand, each with a runbook and a record:
- the restore drill, repeated before launch (`docs/runbooks/restore-drill.md`);
- the UptimeRobot monitors and a test alert (`monitoring.md` §1);
- the SSH key and a trial copy from the pilot site (`backups.md` §1).

The consent text v1.0 must say that the laptop copy exists before the study site opens (T4.3).
That wording goes to Dr. Hany first; the pilot text is unchanged, since pilot games are
never copied.
