# Runbook: rehearsing the pilot on staging

T4.2. Before the first pilot night, everything the pilot depends on is run once on the pilot
site, with test players instead of people: whole games over the internet, a player going
away, then every command of the pilot runbook's §4 on those games. It finds what would
otherwise go wrong on 1 December, while there is still a week to fix it.

**When:** by **Sunday 22 November**, once T4.2 is merged. A rehearsal after the pilot needs
`FISH_TABLES_OPEN=yes` on `fish-staging` while it runs ([pilot.md](pilot.md) §4).
**Time needed:** about an hour: 15 minutes signing in six test accounts, half an hour of
games, 15 minutes of commands.

The rehearsal's games are real games on the pilot site, played by your own test accounts.
They started before 1 December, so the pilot's `--since 2026-12-01` leaves them out of
everything that counts.

## 1. The deploy

- [ ] Render deploys `fish-staging` from main once CI passes (`autoDeployTrigger:
  checksPass`). Wait until `fish-staging` → **Events** shows the deploy of T4.2's last commit
  as live.
- [ ] From an up-to-date main, run `scripts/try_server.py` against the pilot site. It prints
  PASS, with schema revision `0008` and `bots:   uniform-1.5-4s-v1`.

## 2. Six test accounts

Each test player needs its own account and its own session cookie. Use six addresses that
reach your inbox: with Gmail, your address with `+r1` to `+r6` before the `@`
(`you+r1@gmail.com`). For each of the six, one at a time:

1. Open a **new private window** and go to the pilot site.
2. Read the study information, confirm the three things, and enter the address.
3. Open the sign-in email (it may take a minute), and use the link **in that same private
   window**.
4. In the developer tools (**Application**, or **Storage**, then **Cookies**), copy the value
   of `fish_session`. Add it as a line of `~/rehearsal-sessions.txt`.
5. Close the window. The session stays signed in on the server.

Then `chmod 600 ~/rehearsal-sessions.txt`. Each line is a sign-in: keep the file to yourself,
and delete it at the end (§5).

## 3. The games

From an up-to-date main:

```bash
uv run python scripts/rehearse.py https://fish-pilot.thedefinitivesanjeevexperience.com \
    --sessions ~/rehearsal-sessions.txt --games 6
```

Six games, a few minutes each. In the 2nd, a player goes away for 40 seconds, and is told
when they come back that a bot took their seat. At the end it prints the median wait the
players chose for each kind of decision, and PASS.

While it runs, keep `fish-staging` → **Logs** open, as on a pilot night, and look for
`ERROR` lines. You can also watch: sign in as yourself on your laptop. Your own account
isn't one of the six, so it isn't at their table, but it shows the site is up.

## 4. The commands

In `fish-staging`'s **Shell**, with today's date (Eastern) as `--since`:

```bash
python -m fish_server.stats
python -m fish_server.pilot_report --since 2026-11-22 --out /tmp/rehearsal.json
cat /tmp/rehearsal.json
time python -m fish_server.mde --since 2026-11-22
```

Check, and note in §6 anything that doesn't hold:

- [ ] **The report** counts 6 games in the corpus, none abandoned, and 1 with a bot handover.
  Under Connections it shows 1 handover (`disconnect 1`) and at least 1 disconnection.
- [ ] **Response times.** Each kind's median is at least the median wait `rehearse.py`
  printed for it, and no more than about a second above it. A player who is sent a new update
  while waiting starts a new wait, so some times are longer than the wait chosen. The round
  trip's median is a few tens of milliseconds to a few hundred.
- [ ] **Game length** and the **share of time in windows** are shown. The games are random,
  so their values mean nothing.
- [ ] **The MDE table** prints, with its warning that 6 finished games are too few. The
  `real` time tells you how long the pilot's will take, roughly in proportion to its games.
- [ ] **The bots' table.** Copy what `cat` printed into `~/Downloads/rehearsal.json` on your
  laptop. Then, from main:

  ```bash
  uv run python scripts/make_bot_delays.py ~/Downloads/rehearsal.json rehearsal-v1 \
      --tables /tmp/rehearsal-tables
  ```

  It writes `/tmp/rehearsal-tables/rehearsal-v1.json`, or says which kind has fewer than 50
  times. Six games can be too few for presses and assignments, so either is fine. It
  writes nothing in the repository.

## 5. Afterwards

- Delete `~/rehearsal-sessions.txt`, `~/Downloads/rehearsal.json` and
  `/tmp/rehearsal-tables`.
- Anything that went wrong is fixed the usual way before 30 November: a test that shows it,
  the fix, `./scripts/check.sh`, a PR. Then rehearse again.
- The six test accounts stay on the pilot site. Their games are left out of the pilot by
  date, and their addresses are deleted with the pilot's on 31 March 2027
  ([requests.md](requests.md) §6).

## 6. Record

| Date | Games | Report, MDEs, bots' table | What went wrong | By |
|---|---|---|---|---|
