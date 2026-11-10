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
2. **The players' segments and M4** ([email.md](email.md) at the top, §3 and §4).
3. **The weekly corpus copy** ([backups.md](backups.md) §2).
4. **A row in §5**: the week's corpus games, the bot share, abandoned games, the database's
   size, and anything you acted on.

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
| **Bots** | `stats`: "a bot held a seat", and the week's "bot held a seat" | more than 20% of a week's corpus games | Games with a bot are left out of RQ1's primary set, so the primary set grows slower than the corpus. `stats`' "seats handed to a bot" says why: mostly **a turn ran out** means people stepped away mid-game; mostly **a person dropped out** means connections, so check **Logs** and **Metrics** for restarts around the game nights |
| **Abandoned games** | `stats`: "ended, left out", abandoned | more than 10% of a week's started games | A game is abandoned when its people all leave or the server restarts. Look in **Events** for a deploy or restart at those times, and in **Logs** for `ERROR` lines |
| **Database** | `stats`: "Database", size | 80% of the disk (it says so) | Raise `diskSizeGB` for `fish-production-db` in `render.yaml`, and `DISK_GB["study"]` in `fish_server/stats.py` to match (`test_blueprint.py` checks they agree). It can grow but never shrink |
| **Server load** | `fish-production` → **Metrics**, on a game night | CPU above 80%, or memory above 90%, for more than a few minutes | Raise the instance type in the dashboard at once (it restarts the service, so between games if you can), then the `plan` in `render.yaml` to match |
| **Errors** | `fish-production` → **Logs** | an `ERROR` line that repeats, or a game that stops | Fix it as any fault: a test that shows it, the fix, a PR. Deploy it by [launch.md](launch.md) §4, not on a game night |
| **The site down** | UptimeRobot's email | either study monitor down | [monitoring.md](monitoring.md) §3 |
| **Email** | Resend → **Logs** and **Metrics** | bounces above 4% of a send, or any complaint | Look at what bounced. A complaint unsubscribes that address by itself: never add it back |
| **Requests and withdrawals** | your inbox | any | Within 30 days: [requests.md](requests.md), and withdrawals with `python -m fish_server.withdraw` ([server.md](../server.md) §2) |

## 4. Changing the site during collection

Each game records the code it was played with (`server_commit`), and the corpus is analysed as
one study. So from 13 December:

- **Only fixes.** Change how games are played (the rules, timers, bots or what players see)
  only to fix a fault, and record why in [decisions.md](../decisions.md), with the first game
  it affects.
- **Every deploy** by [launch.md](launch.md) §4: merged to main, checked on staging, then a
  tag, never from 7:30 to 10:30 pm on a game night. A deploy ends every game in progress.
- **A text players see** (the study information, the terms, the privacy policy) changes only
  with Dr. Hany's approval, as a new version (Consent Screen §4).

## 5. Record

One row per Monday, and one for anything acted on in between.

| Date | Corpus games (week / all) | Bot share | Abandoned | Database | What was done | By |
|---|---|---|---|---|---|---|

## 6. After the last night

On **Monday 15 February**: the last `stats`, M7 ([email.md](email.md) §3), and the last
weekly corpus copy. Withdrawing through the website closes at the end of 14 February (Consent
Screen §2.7). Then the corpus is checked and frozen (T4.4, T4.5, by 28 February), which also
decides what the site does after the last night.
