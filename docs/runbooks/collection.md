# Runbook: watching collection

T4.3. From opening night, **Sunday 13 December**, to the last night, **Sunday 14 February**,
games are collected on the study's site. This runbook is what to check and when, and what to do
when a number crosses a line. Everything here is read by hand: `python -m fish_server.stats` in
`fish-production`'s **Shell**, Render's **Logs** and **Metrics**, UptimeRobot's emails and
Resend's **Logs**. Nothing new runs on its own.

## 1. Every Monday, 14 December to 15 February

In this order, before M4 goes out at 9:00 am:

1. **`python -m fish_server.stats`** in `fish-production`'s Shell. Check it against §3, and
   act on anything past its line.
2. **`python -m fish_server.integrity`** in the same Shell (T4.4). It prints PASS, or each
   fault with its game: then §4, the same day.
3. **The players' segments and M4** ([email.md](email.md) at the top, §3 and §4).
4. **The weekly corpus copy** ([backups.md](backups.md) §2), compared with last week's copy
   from the second Monday on. If it reports a changed or missing game: §4.
5. **A row in §6**, from what `stats`, the integrity check and the export printed, and
   anything you acted on.

## 2. Each game night

The nights are in [recruitment.md](../recruitment.md) §3: every Sunday, and Wednesdays for one
group or the other, 8:00 – 10:00 pm.

- **7:45 pm.** UptimeRobot shows both study monitors up. Open `fish-production` → **Logs**, and
  keep it open. Nothing is deployed from 7:30 to 10:30 pm ([launch.md](launch.md) §4).
- **During.** As on a pilot night ([pilot.md](pilot.md) §2), but don't play: every game here is
  a study game. Look for `ERROR` lines, and look at **Metrics** at least once while tables are
  full.
- **After, by 10:30 pm.** `python -m fish_server.stats`: the day's row under "Day (last 14
  days)". If the night is a Wednesday, check that its group had at least one table: the "group 2
  tables" column, for group 2.

## 3. What to look at, and what to do

| What | Where | Past this line | Do this |
|---|---|---|---|
| **Pace** | `stats`: "last full week" | two full weeks in a row short of 110 (it says so) | Add a Friday night, 8:00 – 10:00 pm, for everyone ([recruitment.md](../recruitment.md) §3), and include it in that week's M4 |
| **Group 2's games** | `stats`: the week's "group 2 tables" | no group 2 table on its Wednesday, two of its Wednesdays in a row | Its test set needs about 150 games by 14 February, about 17 a week. Tell Dr. Hany, with the counts: the fix is recruitment, not the site |
| **The primary set** | `stats`: the week's "primary" against its "corpus" | under 70% of a full week's corpus games | RQ1 is answered on primary-set games, so this is the count that matters. "Analysis sets" says where the rest went: a bot handover (the row below), rooms, or a yes to note-taking. Tell Dr. Hany if it stays low two weeks running |
| **Bots** | `stats`: the week's "with a handover", and "a bot held a seat" | more than 20% of a week's corpus games | Games with a bot are left out of RQ1's primary set, so the primary set grows slower than the corpus. `stats`' "seats handed to a bot" says why: mostly **a turn ran out** means people stepped away mid-game; mostly **a person dropped out** means connections, so check **Logs** and **Metrics** for restarts around the game nights |
| **Abandoned games** | `stats`: "ended, left out", abandoned | more than 10% of a week's started games | A game is abandoned when its people all leave or the server restarts. Look in **Events** for a deploy or restart at those times, and in **Logs** for `ERROR` lines |
| **Database** | `stats`: "Database", size | 80% of the disk (it says so) | Raise `diskSizeGB` for `fish-production-db` in `render.yaml`, and `DISK_GB["study"]` in `fish_server/stats.py` to match (`test_blueprint.py` checks they agree). It can grow but never shrink |
| **Server load** | `fish-production` → **Metrics**, on a game night | CPU above 80%, or memory above 90%, for more than a few minutes | Raise the instance type in the dashboard at once (it restarts the service, so between games if you can), then the `plan` in `render.yaml` to match |
| **Errors** | `fish-production` → **Logs** | an `ERROR` line that repeats, or a game that stops | Fix it as any fault: a test that shows it, the fix, a PR. Deploy it by [launch.md](launch.md) §4, not on a game night |
| **The site down** | UptimeRobot's email | either study monitor down | [monitoring.md](monitoring.md) §3 |
| **Email** | Resend → **Logs** and **Metrics** | bounces above 4% of a send, or any complaint | Look at what bounced. A complaint unsubscribes that address by itself: never add it back |
| **Requests and withdrawals** | your inbox | any | Within 30 days: [requests.md](requests.md), and withdrawals with `python -m fish_server.withdraw` ([server.md](../server.md) §2) |

## 4. When a check finds a fault

A fault is never repaired, and nothing here changes a stored game. The steps are the same
whichever check found it:

1. **Keep what you have.** Don't delete last week's copy. Note the fault lines as printed.
   Render keeps logs for 7 days and point-in-time recovery for 3 ([backups.md](backups.md)),
   so look the same day.
2. **Find out what happened**, from the table below.
3. **Fix the cause** as any fault: a test that shows it, the fix, a PR, a deploy by
   [launch.md](launch.md) §4.
4. **Decide about the games** it touched, and write the decision in
   [decisions.md](../decisions.md): what the fault was, how many games, and whether they stay.
   If more than a handful of corpus games would go, ask Dr. Hany first.
5. **Leave a game out**, if that is the decision, in `fish-production`'s Shell:

   ```bash
   python -m fish_server.exclude <game id> --reason "D140: <why, in a sentence>"
   ```

   The game's rows stay as they are. From the next export it is left out and counted as
   "excluded after a fault", and the integrity check counts its faults as known and passes
   again. An exclusion **can't be undone**, so decide first.
6. **Run the check again**, and record it in §6.

| Check | What it means | Look at |
|---|---|---|
| `records`, `actions`, `seats` | a completed game was stored wrong or has been damaged. If it is a corpus game, the export stops at it, so there is no weekly copy until it is excluded | **Logs** around the game's time, for `ERROR` lines and retried writes; whether last week's copy holds the game unchanged (then it was damaged since: consider restoring, [restore-drill.md](restore-drill.md)) |
| `stale` | the sweep that ends stopped games isn't running | **Logs** for the sweep's errors; **Events** for restarts. The game is ended `abandoned` once the sweep works; nothing to exclude |
| `consent` | a person's seat has no consent flags, so its game is already left out ("a seat without consent") | how the game began: its start is the fault. Nothing to exclude |
| `cohort` | a table mixed the groups, or is marked wrongly. A mixed solo table means cohort matchmaking failed, and its games would leak held-out players into training | **every** game since the last clean check. Stop and tell Dr. Hany: the cohort test set depends on it (Research Questions §5.1) |
| `draw` | a player's group isn't what the cohort seed gives: `FISH_COHORT_SEED` has changed, or was wrong when they signed up | the service's **Environment**: restore the seed from your password manager. Tell Dr. Hany |
| `versions` | a game names a bot delay table or encoding this code doesn't know, or was played under an old ruleset since launch | what was deployed then (**Events**): a rollback past a version change |
| `seeds` | two games share a seed, which chance doesn't do | the seed source (`games.new_seed`). Both games are suspect |
| `notes` | an answer is stored for a bot's seat | **Logs**; the answer is ignored by the export. Nothing to exclude |
| `two tables` | a person was seated in two games at once | the lobby and reconnection around that time. Decide which game, if either, stays |
| the copy check: a game **changed** | a game already collected is different this week | nothing should be able to do this. Keep both copies, compare the two records, and restore if the database was altered |
| the copy check: games **gone** | more games left than withdrawals explain | `stats`: "ended, left out" by reason, against last week's row in §6 |

## 5. Changing the site during collection

Each game records the code it was played with (`server_commit`), and the corpus is analysed as
one study. So from 13 December:

- **Only fixes.** Change how games are played (the rules, timers, bots or what players see)
  only to fix a fault, and record why in [decisions.md](../decisions.md), with the first game
  it affects.
- **Every deploy** by [launch.md](launch.md) §4: merged to main, checked on staging, then a
  tag, never from 7:30 to 10:30 pm on a game night. A deploy ends every game in progress.
- **A text players see** (the study information, the terms, the privacy policy) changes only
  with Dr. Hany's approval, as a new version (Consent Screen §4).

## 6. Record

One row per Monday, and one for anything acted on in between.

| Date | Corpus (week / all) | Primary (week / all) | Group 2 primary (all) | With a handover (week) | Abandoned (week) | Withdrawn games (export) | Integrity | Copy against last week's | Database | What was done | By |
|---|---|---|---|---|---|---|---|---|---|---|---|

## 7. After the last night

On **Monday 15 February**: the last `stats`, M7 ([email.md](email.md) §3), and the last
weekly corpus copy. Withdrawing through the website closes at the end of 14 February (Consent
Screen §2.7). Then the corpus is given its last integrity check and frozen (T4.5, by 28 February), which also
decides what the site does after the last night.
