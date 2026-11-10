# Runbook: uptime monitoring

T3.6. UptimeRobot (free plan) checks each site every 5 minutes, from outside Render, and
emails you when a check fails and again when it passes. There are two checks per site: one
for the server and one for its database. A database outage leaves the server answering, so
one check alone would miss it ([server.md](../server.md) §6: games can't be written, and
nobody can sign in).

| Monitor | Address | Passes when the reply contains | Means, when down |
|---|---|---|---|
| `Fish pilot: server` | https://fish-pilot.thedefinitivesanjeevexperience.com/health | `"status":"ok"` | the site can't be reached |
| `Fish pilot: database` | https://fish-pilot.thedefinitivesanjeevexperience.com/health/db | `"database":"ok"` | the server can't reach `fish-staging-db` |
| `Fish study: server` | https://fish.thedefinitivesanjeevexperience.com/health | `"status":"ok"` | the same, for production ([launch.md](launch.md) §2, by 29 Nov) |
| `Fish study: database` | https://fish.thedefinitivesanjeevexperience.com/health/db | `"database":"ok"` | the same, for production |

These are keyword checks, not plain "is it up" checks, because a reply that isn't this
server's (a hosting error page, or an address pointing at the wrong place) can still come
back as 200. `/health/db` replies 503 without the keyword when the database can't be reached.

**What the server sees:** one request to each address every 5 minutes. `/health` touches
nothing; `/health/db` reads the migration number over a pooled connection. Nothing is
written, and games and the corpus are unaffected.

## 1. Set it up (once, before the pilot on 1 December)

**Time needed:** about 20 minutes, half of it waiting for the test alert.

1. **Make the account.** At https://uptimerobot.com, sign up on the **Free** plan with the
   address you want alerts at, and confirm the address. The free plan allows 50 monitors at
   a 5-minute interval, with email alerts. That's enough for both sites.
2. **Add `Fish pilot: server`.** **New monitor**, then:
   - **Monitor type:** Keyword.
   - **URL:** https://fish-pilot.thedefinitivesanjeevexperience.com/health
   - **Keyword:** `"status":"ok"` (with the quotation marks and no spaces, exactly as
     the server writes it).
   - Alert when the keyword **does not exist**.
   - **Friendly name:** `Fish pilot: server`.
   - **Monitoring interval:** 5 minutes.
   - **Notify:** your email (the account's address is there already; tick it).
   - **Create monitor.**
3. **Add `Fish pilot: database`** the same way, with the URL ending `/health/db` and the
   keyword `"database":"ok"`.
4. **Check that both are up.** Both turn green within 5 minutes. If one doesn't, open its
   address in a browser. `/health` should show `{"status":"ok",…}` and `/health/db`
   `{"database":"ok","schema_revision":"0006"}` (or a later number). Correct the keyword to
   match what the page shows.
5. **Test the alert.** Add a third monitor the same way, named `Alert test`, on the
   `/health` address with the keyword `this-is-never-there`. Within about 10 minutes an
   email should say it is down. If it went to spam, mark it **not spam** and add its sender
   to your contacts, so real alerts reach your inbox. Then delete `Alert test`.
6. **Record it** in the table in §4: the date, and "set up; test alert received".

**Production ([launch.md](launch.md) §2, by 29 November):** once the study's address works
([domains.md](domains.md)), add `Fish study: server` and `Fish study: database` the same
way. Keep the pilot's two until the pilot site is switched off.

## 2. Deploys and planned work

Render starts a new version and moves traffic to it only once its `/health` passes. A failed
pre-deploy step (migrations, the server login) leaves the old version running. So a deploy
normally raises no alert. It does end any game in progress ([server.md](../server.md) §6),
so deploy between game nights.

If you expect downtime (for example a database change in Render), **pause** the site's two
monitors first, and **resume** them afterwards. The free plan has no maintenance windows, so
pausing is how to keep the alerts quiet.

## 3. When an alert comes

Open the site's `/health` and `/health/db` in a browser to see which is failing now (an alert
can be up to 5 minutes old). Then:

**The server is down** (`Fish pilot: server`; the database monitor usually fails with it):

1. Look at https://status.render.com. If Render reports an incident in Virginia, wait for it;
   nothing you do will help sooner.
2. In the Render dashboard, open `fish-staging` → **Events**. If a deploy just finished or
   the service shows as failed or restarting, open **Logs** around that time.
3. **If the latest deploy caused it:** in **Events**, find the last deploy that worked and
   **Rollback** to it. Then revert the pull request that broke it on GitHub, so that main is
   right again and the next deploy doesn't bring the fault back.
4. **If nothing was deployed:** **Manual Deploy → Deploy latest commit**, which starts the
   server again from the same code.

**Only the database is down** (`Fish pilot: database`; the server is up):

1. Look at https://status.render.com, then `fish-staging-db` in the dashboard: its status,
   **Events** and **Metrics**.
2. **If its disk is full** (the pilot's is 1 GB): in its **Settings**, raise the disk size.
   It can grow but never shrink.
3. Nothing needs restarting once the database is back: the server checks each connection
   before using it and replaces any that went dead.

While the database is down, nobody can sign in. A game in progress retries each write for
about a minute and then stops, ending `abandoned`. Abandoned games never enter the corpus,
and nothing needs repairing.

**When it's back** (UptimeRobot emails that the monitor is up):

1. From an up-to-date main, run `scripts/try_server.py` against the site
   ([server.md](../server.md) §7). It checks the page, both health addresses (the database
   at the newest migration), sign-in and the game socket.
2. If it happened during a game night, `python -m fish_server.stats` in the Shell shows how
   many games were left out as abandoned.
3. Record it in §4.

## 4. Record

Every alert that wasn't a test, and the setup itself.

| Date | Site | What failed | Down for | Cause and fix | By |
|---|---|---|---|---|---|
| 2026-11-07 | Pilot | — | — | Set up; test alert received | Sanjeev |
