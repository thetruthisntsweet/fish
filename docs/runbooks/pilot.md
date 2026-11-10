# Runbook: the pilot

T4.2. Known players (the Gov School group) play full games on the pilot site, so that the
study opens knowing four things:

| What | From | Used for |
|---|---|---|
| How long a game takes, deal to end | the pilot report (§4) | M3's "about {N} minutes" ([recruitment.md](../recruitment.md) §5); Research Plan §3 "Time asked" |
| The share of game time spent in call windows | the pilot report | Research Plan §2 |
| Human response times, by kind of action | the pilot report | the bots' delays (R.8.8) and the H1c placebo (Research Questions §2) |
| The minimum detectable effect of each primary metric | the pilot's games (`docs/mde.md`) | Research Questions §5.4, recorded before launch |

And it confirms, at real tables, that the site shows events and timers as they happen.

**Dates** (Eastern; recruitment.md §2, §3):

| | |
|---|---|
| Mon 16 Nov | M1, the pilot invitation |
| Mon 30 Nov | M2, the reminder |
| Tue 1 Dec, 8:00 – 10:00 pm | Pilot night 1 |
| Thu 3 Dec, 8:00 – 10:00 pm | Pilot night 2 |
| Sat 5 Dec, 3:00 – 5:00 pm | Pilot night 3 |
| Sun 6 – Mon 7 Dec | The report, the bots' delays and the MDEs (§4) |
| Tue 8 Dec | M3, the launch invitation, with the game length |

Pilot games are played on the staging site (`fish-staging`), which shows the pilot's study
information and terms. They are never published or copied, and they are deleted with the
pilot's database on 31 March 2027 ([requests.md](requests.md) §6).

## 1. By Sunday 29 November

- [ ] Everything through T4.2 is deployed on `fish-staging`: `scripts/try_server.py` against
  the pilot site, from an up-to-date main, prints PASS with schema revision `0008` and
  `bots:   uniform-1.5-4s-v1`.
- [ ] The rehearsal is done, by Sunday 22 November, and anything it found is fixed
  ([rehearsal.md](rehearsal.md)).
- [ ] The pilot site shows "Fish research study: before you play" in its pilot version, and
  its footer links the pilot terms and privacy policy (T3.8 subtask 6's live check).
- [ ] UptimeRobot's two pilot monitors are green ([monitoring.md](monitoring.md) §1).
- [ ] The restore drill has been repeated ([restore-drill.md](restore-drill.md)).
- [ ] M1 went out on 16 November ([email.md](email.md)). Count the one-word replies per night
  in your inbox. A night with fewer than six probably won't fill a table: plan to play
  yourself (§2), and mention it in M2 if it's still short.
- [ ] Your own sign-in on the pilot site works, with an address you'll play from.

On **Monday 30 November**, send M2 as usual (email.md §3).

## 2. Each pilot night

**Half an hour before:**
- [ ] `scripts/try_server.py` against the pilot site prints PASS.
- [ ] UptimeRobot shows both pilot monitors up.
- [ ] Open `fish-staging` → **Logs** in Render, and keep it open.

**During:**
- **Play at a table yourself** when one needs a sixth, and in any case for at least one
  game. You are a known player, so your games count as pilot games. While you play, check
  by eye that:
  - each ask, call, window and choice shows the moment it happens, for you and in the
    other players' reactions;
  - the turn timer counts down smoothly and matches the time left;
  - the call window's timer shows only while the window is open.

  Note anything else in §5.
- **Every hour**, run `python -m fish_server.stats` in `fish-staging`'s Shell: completed
  games, bot handovers, abandoned games.
- **In the logs**, look for `ERROR` lines. One that repeats, or a game that stops, is a fault
  to fix before the next night.
- **If the site goes down**, follow [monitoring.md](monitoring.md) §3.
- **If games can't be played** (they don't start, or every one stops), suspend `fish-staging`
  in Render, so nobody is left at a broken table. Reply to anyone who emails, fix it, and
  resume the service before the next night.
- **Don't ask players for feedback**, by email or otherwise. The privacy policy says the study
  collects no other text from them. If someone writes to you anyway, answer their question,
  and keep their words out of the study's records.

**After:**
- [ ] `python -m fish_server.stats` once more.
- [ ] A row in §5: tables, completed games, and anything that went wrong.

## 3. If the pilot finds a fault

Anything that went wrong in a game is fixed before M3 goes out on 8 December, the way any
fix is made: a test that shows it, the fix, `./scripts/check.sh`, a PR. A fix to how games
are played changes the code the study uses, so note in §5 which pilot games came before
it. The pilot's games still count for its four figures unless the fault changed how long
games took or how people responded. If it did, leave those games out of the report with
`--since` (§4).

## 4. After the last night: Saturday 5 – Monday 7 December

From midnight after the last night (Sunday 6 December, Eastern), the pilot site takes no new
tables. Its lobby says the pilot is over and links to the study (`FISH_PILOT_ENDED` in
`render.yaml`, `fish_server.opening`), so no one plays pilot games that no one will use.
Signing in, the study information and withdrawing still work, and the commands below run in
its Shell as before. To try something on staging afterwards, set `FISH_TABLES_OPEN=yes` in
`fish-staging` → **Environment**, and delete it when you're done.

In this order:

1. **The report**, in `fish-staging`'s Shell:

   ```bash
   python -m fish_server.pilot_report --since 2026-12-01 --out /tmp/pilot.json
   cat /tmp/pilot.json
   ```

   It counts only games started from 1 December, so your earlier test games are left out.
   Copy what it prints into §6. Then copy what `cat` prints into a file `pilot.json` on
   your laptop. It holds every percentile of the response times, which step 3 needs, and
   the Shell's `/tmp` is gone at the next deploy. It names no game or player.
2. **The game length.** The report's median game length, rounded to five minutes, is M3's
   `{N}`. Send M3 on Tuesday 8 December with it (email.md §3).
3. **The bots' delays.** On your laptop, from an up-to-date main:

   ```bash
   git switch -c bot-delays-pilot
   uv run python scripts/make_bot_delays.py ~/Downloads/pilot.json pilot-2026-12-v1
   ```

   It writes `packages/fish-agents/src/fish_agents/delay_tables/pilot-2026-12-v1.json`, or
   says which kind has too few times (fewer than 50). Set `BOT_DELAYS = "pilot-2026-12-v1"`
   in `packages/fish-server/src/fish_server/study.py`, as it says. Run `./scripts/check.sh`,
   then commit, push and merge the PR, and deploy it to production before 8 December.
   `scripts/try_server.py` against production then prints `bots:   pilot-2026-12-v1`, and
   fails if production would open with the stand-in. The pilot site keeps
   `uniform-1.5-4s-v1`.
4. **The minimum detectable effects**, in `fish-staging`'s Shell:

   ```bash
   python -m fish_server.mde --since 2026-12-01
   ```

   It takes a minute or two. It prints the table for [docs/mde.md](../mde.md) §3, from the
   same games as the report. Paste it there with the number of games, then commit, push and
   merge the PR before 8 December. If it says there are too few finished games (fewer than
   10), record what it prints anyway, and say so under the table.
5. **Production** opens on 8 December with all of it ([launch.md](launch.md) §3).

## 5. Record

| Night | Tables | Completed games | What went wrong | By |
|---|---|---|---|---|

## 6. What the pilot found

Filled in from the report on 6 or 7 December.

| Figure | Value |
|---|---|
| Completed games (from 1 Dec) | |
| Game length: median (interquartile range) | |
| Share of game time in call windows | |
| Response times: median by kind | |
| Round trip: median (95th percentile) | |
| Games with a bot handover / abandoned | |
