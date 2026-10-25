# The corpus

What every website game records, how corpus membership and the analysis sets are worked out
from it, and what is released. This is the design T1.6 fixes before the server writes a
single game (T3.1, T3.2). Games logged in an older format cannot be fixed afterwards, so a
field the research questions need and this document does not list will never exist.

Section numbers below are cited by the code that implements them. The research questions,
analysis sets and the definition of response time are in the planning document (T1.1); the
rules are the Canonical Ruleset v1.1.

## 1. Principles

- **A game is its log.** The seed and the ordered engine actions reproduce every state
  (determinism.md §8). The log is at once the replay, the audit trail and the corpus
  record; nothing is stored that the log could contradict.
- **The engine decides, the server only keeps time** (D23). The server stamps every action
  with its own clock and records why it was applied. Every rule outcome comes from replay.
- **Nothing is decided by hand.** Corpus membership and every analysis set are computed from
  stored flags (§6). Withdrawing consent appends a row; the next export leaves the game out.
- **Written once.** Every table that records play or consent is append-only (D15, the
  `fish_forbid_change` trigger). A correction is a new row that supersedes an old one, never
  an edit.
- **Hidden information stays on the server.** The log holds every hand, because the seed
  does. Nothing derived from it reaches a client during play; the projection (D31) is the
  only way out.

## 2. Players

| Field | Meaning | Source |
|---|---|---|
| `player_id` | internal identifier, random, never shown | sign-up (T3.1) |
| `signed_up_at` | wall-clock time of sign-up | server |
| `signup_number` | 0, 1, 2, … in sign-up order | server |
| `cohort` | in the held-out cohort (§2.1) | frozen draw at sign-up |
| contact | email for sign-in links | sign-up; a separate table, never exported (§7) |

**2.1 Held-out cohort.** At sign-up, before a first game, a player is assigned to the
held-out cohort by a frozen draw (`fish_rules.cohort`, `fish-cohort-v1`): sign-ups are taken
in blocks of 20 by `signup_number`, and in each block 3 positions, drawn from stream
`cohort` of the cohort seed with the block number as the index, are in the cohort. This
gives exactly 15% at every multiple of 20 sign-ups (about 750 of 5,000), which a 15% coin
flip per player would only approximate, and nobody can choose their own assignment. The
cohort seed is a fixed 64-bit value held in the server's settings and published with the
frozen corpus, so the assignment can be checked. Cohort players are matched only with each
other (T3.1).

**2.2 Consent and age.** Two append-only event tables. A player's status at any moment is
their latest event of each kind.

| Event | Fields |
|---|---|
| consent | `player_id`, `at`, `consent_version` (the exact text shown, by version), `research_use` (yes/no), `public_release` (yes/no, CC BY 4.0), `no_outside_communication` (attested), `no_notes` (attested); a withdrawal is a consent event with `research_use` no |
| age | `player_id`, `at`, `confirmed_18_plus` (T3.3); no date of birth is stored |

## 3. Games

| Field | Meaning | Used for |
|---|---|---|
| `game_id` | internal identifier | |
| `seed` | the game seed (64 bits) | replay; the hands |
| `ruleset`, `action_encoding`, `state_encoding` | versions the game was played under | replay (R.10.2) |
| `server_commit`, `protocol_version` | the code that ran it | reproducibility (T1.1 §5.5) |
| `matchmaking` | `solo` or `group` | analysis sets (§6) |
| `cohort_table` | the table was formed by cohort matchmaking | cohort test set |
| `created_at`, `started_at`, `ended_at` | wall-clock times | operations; release keeps the month only |
| `completion` | `finished` (R.7.1), `unfinished` (1,000 asks, R.8.2) or `abandoned` (the server stopped the game) | analysis sets |

`finished` and `unfinished` are *completed* games: the rules ended them. An abandoned game
stops part-way and is kept in the log but never enters the corpus.

## 4. Seats

| Field | Meaning | Source |
|---|---|---|
| `seat` | 0–5 | |
| controller | a person (`player_id`) or a bot (`agent`, its version, e.g. `b1-v1`) | matchmaking |
| `memory` | `human` for a person; `full`, `last-k` with its k, or `none` for a bot (T2.8) | matchmaking |
| `bot_filled` | a bot held the seat from the start; derived from the controller, not stored | matchmaking (T3.5) |

**4.1 Handovers.** Under R.8.4 a person who does not act within the 60-second turn timer,
or does not reconnect within 30 seconds, is replaced by a B1 bot for the rest of the game
and does not reclaim the seat. The replacement is an appended *handover* row: the seat, the
new controller and its memory setting, the number of actions applied so far, the server
time and the reason (`turn_timeout` or `disconnect`). Who controlled a seat at any action is
therefore known exactly, and a game has a handover if any seat ever had one.

**4.2 The note-taking answer.** After the game, every person who played in it and is still
connected is asked whether they took notes. The answer is appended as `yes`, `no` or
`declined`, with the question's version and time; a person who leaves before answering has
no row (`unanswered`).

## 5. Actions and time

**5.1 The action log.** One append-only row per engine action, numbered 0, 1, 2, … in the
order applied, including the control actions the server applies itself.

| Field | Meaning |
|---|---|
| `seq` | position in the game's action list |
| `action` | the action as `fish-actions-v1` data |
| `cause` | `{"seat": s}` for an input from seat s, including the Call press that opens a window; `{"timer": t}` for the server's timers (`window`, `assignment`, `choice`) |
| `received_us` | when the input reached the server, or the timer fired |
| `sent_us` | when the update it produced was handed to the transport for every connected seat |

Both times are microseconds since the game started, on the server's monotonic clock, so they
are unaffected by clock adjustments; the game's wall-clock start is in §3. Received times
never go back, sent times never go back, and each action is sent no earlier than received.
Whether a person or a bot gave a seat input is not stored: the seats and handovers (§4)
decide it.

A Call press (R.8.3) is recorded as `OpenWindow`, when no window is open, followed by the
presser's `Declare`, both caused by the presser and with the same received time; a press
inside an open window is a `Declare` alone. Windows close only by the window timer, and
nobody passes on the website.

**5.2 Server log rows.** Things that happen but are not engine actions, each with the
number of actions applied so far and a server time (`at_us`), in an append-only table:

| Row | Fields |
|---|---|
| `rtt` | seat, the round trip in microseconds; every connected person is pinged every 10 seconds and after each reconnection |
| `rejected` | seat, the input as received, and why: illegal, a stale Call press, or malformed |
| `bot_delay` | seat, the delay drawn before a bot's action or Call press, and whether the decision was dropped because a window, assignment or choice had begun (R.8.8) |
| `connection` | seat, `connected`, `disconnected` or `reconnected` |
| `handover` | as §4.1 |

**5.3 Response time.** As defined in T1.1: from the moment a player could first act at a
decision point to the moment their action reaches the server, on the server clock. From the
log:

- the *start* of a seat's decision point is the `sent_us` of the action after which the seat
  could act and stayed able to act until it did (the deal counts as an action sent at 0);
- for a Call press, the start is the `sent_us` of the action that produced the most recent
  numbered event (determinism.md §8);
- the response time is the action's `received_us` minus the start; it belongs to the
  press's `Declare`, not its `OpenWindow`;
- it is computed only for a person's input: bot actions and timer actions have none.

No call-entry freeze (the assignment step, R.4.3) ever falls inside a decision point: only
the caller can act during one, and it ends with the call, a numbered event, so T1.1's rule
that the freeze is not counted holds without subtracting anything. A declaration window does
fall inside the current player's decision point, since they could press during it. A value
can be negative when an input arrived while the update it answers was still being sent.

The round-trip times beside it let an analysis allow for each player's network delay.
Response times are computed from the log by `fish_rules.corpus.response_times`, never stored,
so there is one definition.

## 6. Membership and analysis sets

Membership is computed at every export from the latest flags (subtask 4). The analysis-set
flags that depend only on the game (completed, finished, solo, any bot, note answers,
cohort) are computed from the record itself by `fish_rules.corpus.analysis_flags`, so every
reader gets the same sets without trusting a stored copy.

- **Eligible person.** At export time: latest age event confirmed 18+, and latest consent
  event with `research_use` yes. For the public release, also `public_release` yes.
- **Corpus game.** Completed (§3), at least one person played in it, and every person who
  held any seat at any point is eligible. One ineligible person removes the whole game: their
  actions are part of every other seat's history.
- **Primary set** (T1.1): corpus games that finished (R.7.1), were joined through solo
  matchmaking, had no bot in any seat at any point, and in which nobody answered `yes` to
  the note-taking question.
- **Sensitivity sets:** group-joined games; games with a `yes` note answer; games with a
  bot-filled seat or a handover (RQ1 only, bot actions not scored). Games where some answers
  are `unanswered` or `declined` are counted and reported, and a second sensitivity run
  excludes them.
- **Cohort test set:** corpus games in which every person was in the held-out cohort. Games
  with both cohort and non-cohort people (possible only through group joins) are excluded
  from the cohort test set and from training.
- **In-population split:** every other corpus game, assigned to train 70%, validation 15%
  and test 15% by a frozen draw on the release game number, with the seed recorded at the
  freeze (T4.5).
- **Synthetic set:** bot-only games are played under environment mechanics, not website
  mechanics, so they are not `fish-corpus-v1` records; T5.4 defines their format, which
  shares the game record of determinism.md §8.

## 7. What is released

The export is one `fish-corpus-v1` record per game (`fish_rules.corpus`): the game record of
determinism.md §8, so `replay_record` still replays it, plus `corpus`, `game` (§3), `seats`
(§4), `times` and `causes` (§5.1, one per action) and `log` (§5.2).
`read_corpus_record` checks every field and replays the game; `corpus_record` writes one and
reads it back, so no writer can produce a record that does not read.

| Released | Coarsened | Never leaves the server |
|---|---|---|
| seed, actions, causes, versions; seat controllers, memory settings, handovers; matchmaking, cohort table, completion; each person's cohort flag and note answer; action times and server log rows as microseconds since game start | the game date, to the month | email and contact data; internal player and game ids; wall-clock times; IP addresses, user agents; consent texts and attestation times |

- **Players** appear under a pseudonym drawn at random for each release, the same for every
  game of that release and unrelated to any internal identifier, so per-player analyses
  (T1.1 §5.1, the most-frequent-players check) still work.
- **Consent** is represented only by membership: every released game passed §6.
- **Re-export.** A release is regenerated from the log, never edited. After a withdrawal,
  the next export simply leaves the game out.

## 8. Who builds what

| Task | Part |
|---|---|
| T1.5 | the consent text and its versions (§2.2) |
| T1.6 | this design; the record format (`fish_rules.corpus`) and cohort draw (`fish_rules.cohort`); the tables; membership and export; the datasheet plan |
| T3.1 | writing players, games, seats, actions and server log rows; cohort matchmaking |
| T3.2 | the logging pipeline and completion status |
| T3.3 | the age event |
| T3.5 | bot seats, memory settings, handovers |
| T4.4 | weekly integrity checks and the handover share |
| T4.5 | the freeze, the split seed, anonymisation |
| T7.1 | the release datasheet |

## 9. Tables

`fish_server.db` defines the tables and migration 0003 creates them. A test checks that the
two agree. Every table but `player_contacts` is append-only (§1).

| Table | Holds | Becomes in the record |
|---|---|---|
| `players` | `player_id`, `signup_number` (from the `signup_numbers` sequence), `cohort`, `signed_up_at` (§2) | each person's pseudonym and cohort flag |
| `player_contacts` | the email address for sign-in links; the only table rows can be deleted from | nothing |
| `consent_events`, `age_events` | §2.2 | membership only (§6) |
| `games` | §3 except the ending; the seed as `numeric(20,0)`, since 64-bit seeds do not fit PostgreSQL's signed `bigint` | `seed`, versions, `game` |
| `game_endings` | `completion` and `ended_at`, one row written when the game ends | `game.completion`; a game with no row has not ended |
| `seats` | the six controllers at the start (§4) | `seats` |
| `note_answers` | one row per seat that answered (§4.2) | the seat's `note`; no row is `unanswered` |
| `actions` | §5.1, with the cause as `cause_seat` or `cause_timer` | `actions`, `times`, `causes` |
| `server_log` | §5.2: `after_seq`, `at_us`, `seat`, `type`, and the type's own fields as `data` | `log` |

Check constraints repeat what a single row can show of the record format: seats 0 to 5, a
person's seat has memory `human` and no agent, `k` exactly when memory is `last-k`, exactly
one cause, an action sent no earlier than received, the allowed names of every enumerated
field. Whatever needs the whole game, such as legality and times never going back, is checked
by `fish_rules.corpus` when the record is read (subtask 4). A sign-up number drawn for a
sign-up that then fails is never reused, so the cohort is exactly 3 in every block of 20
numbers rather than of 20 players.
