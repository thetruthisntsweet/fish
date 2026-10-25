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
