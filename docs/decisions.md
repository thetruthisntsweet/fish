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
