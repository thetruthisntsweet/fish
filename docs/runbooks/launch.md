# Runbook: launching the study's site

T4.3. The study's site is `fish-production`, at https://fish.thedefinitivesanjeevexperience.com,
with its own database, `fish-production-db` ([render.yaml](../../render.yaml)). It deploys only
the `production` branch, which only the Deploy workflow moves, to a `site-*` tag on main whose
CI passed ([deploy.yml](../../.github/workflows/deploy.yml), D122). This runbook covers creating
it, checking it, the launch week, and every deploy after.

Anyone signed up can play at any time ([recruitment.md](../recruitment.md) §3). So every game on
this site is a study game, from the day it opens to the last. Until **Tuesday 8 December** the
site refuses new tables and says when the study opens (`FISH_OPENS`, `fish_server.opening`), so it can be built and
checked without anyone playing on it early. Don't play on it yourself, before or after.

| When | What | Section |
|---|---|---|
| By Sun 29 Nov | Create the site, give it its address, check it, monitor it | §1, §2 |
| Sat 5 – Mon 7 Dec | The pilot's figures, bot delays and MDEs are merged | [pilot.md](pilot.md) §4 |
| Mon 7 Dec | Resend Pro, the full Invited list, the launch deploy, M3 scheduled | §3 |
| Tue 8 Dec | The site opens at midnight; M3 at 9:00 am | §3 |
| Sun 13 Dec | Opening night | §3 |
| Any deploy after | Staging first, then a tag, between game nights | §4, §5 |

## 1. Creating the site (once, by Sunday 29 November)

After the rehearsal ([rehearsal.md](rehearsal.md)), on a day with no pilot night. About an hour,
most of it waiting for DNS.

1. **Its Resend key.** In Resend, **API Keys → Create**: name it `fish-production server`,
   permission **Sending access**, domain `mail.thedefinitivesanjeevexperience.com`. Copy it; it
   is shown once.
2. **Its cohort seed.** On your laptop:

   ```bash
   python3 -c "import secrets; print(secrets.randbelow(2**64))"
   ```

   Save it in your password manager as "Fish study cohort seed". It decides who is in the
   held-out cohort (corpus.md §2.1), is published with the frozen corpus, and must **never
   change** once anyone has signed up. Never reuse staging's.
3. **The `production` branch.** Render needs it to exist before it can create the service.
   This is the only time it is moved by hand:

   ```bash
   git fetch origin
   git push origin origin/main:refs/heads/production
   ```

4. **Merge the T4.3 change**: the draft PR, with subtasks 1 to 3 in it. When the Blueprint
   syncs, Render creates `fish-production-db` and `fish-production`.
   - If the sync asks for `FISH_RESEND_API_KEY` and `FISH_COHORT_SEED`, paste the key from step
     1 and the seed from step 2.
   - Otherwise, open `fish-production` → **Environment**, set both, and **Save, rebuild, and
     deploy**.

   Its first deploy is the `production` branch from step 3: main from before T4.3. Only its
   `onrender.com` address reaches it, and nothing links there.
5. **Deploy by tag, the first time.** Once CI has passed on the merge (**Actions → CI**), from
   an up-to-date main:

   ```bash
   git switch main && git pull
   git tag site-2026.11.29          # that day's date; .2 for a second deploy that day
   git push origin site-2026.11.29
   ```

   **Actions → Deploy** shows the run: the tag is checked, then `production` moves. Then
   `fish-production` → **Events** shows the deploy as live. It runs migrations first, as
   staging does. The site now refuses new tables until 8 December. From here, a tag is the
   only way the site changes (§4).
6. **Its address.** Follow [domains.md](domains.md) steps 1 to 3 with `fish`. The Render host is
   under `fish-production`'s name. Then in **Settings → Custom Domains**, press **Verify** until
   `fish.thedefinitivesanjeevexperience.com` shows as verified, with its certificate issued.
7. **Switch its `onrender.com` address off,** in a small PR:
   - in `render.yaml`, under `fish-production`'s `domains`, add the line
     `    renderSubdomainPolicy: disabled`, as staging has, and delete the comment above
     `domains` that says it comes later;
   - in `packages/fish-server/tests/test_blueprint.py`, make it `ADDRESS_PENDING: Final[set[str]]
     = set()`.

   `./scripts/check.sh`, then merge it. It changes the service's settings, not its code: once
   the Blueprint syncs, the site answers only at its own address, with no new tag needed.

## 2. Checking it

Once §1 is done, and again after every deploy that changes what people see:

- [ ] **The address:**

  ```bash
  curl -sI https://fish.thedefinitivesanjeevexperience.com/health | head -1   # HTTP/2 200
  ```

  and the `onrender.com` address answers 404.
- [ ] **The study's texts.** In a browser, the site shows "Fish research study: before you
  play" without the word "pilot". Its footer links Terms of Use v1.0 and Privacy Policy v1.0,
  and `/study` says `"version":"v1.0"` and `"terms_version":"v1.0"`.
- [ ] **Sign-in.** Ask for a link with your own address. The email comes from
  `signin@mail.…`, and its link starts with `https://fish.thedefinitivesanjeevexperience.com`.
  Signing in makes you a player in the study database, which is fine as long as you never play.
- [ ] **`try_server`**, with that session, from an up-to-date main:

  ```bash
  uv run python scripts/try_server.py https://fish.thedefinitivesanjeevexperience.com --session <value>
  ```

  It prints PASS, the schema revision of main's newest migration, and `bots:` with the study's
  table. That is `stand-in-v1` until the pilot's table is merged: fine before 8 December, a
  FAIL from then on. Until 8 December it also prints `tables: not_open - The study opens on
  Tuesday 8 December 2026…`, and checks that making a room is refused in those words. From 8
  December it makes a room and leaves it.
- [ ] **Monitors.** Add `Fish study: server` and `Fish study: database` to UptimeRobot
  ([monitoring.md](monitoring.md) §1), and check that both are up.
- [ ] Record it in §6.

## 3. Launch week

**Sat 5 – Mon 7 December.** The pilot's work, in [pilot.md](pilot.md) §4's order: the report,
M3's game length, the bots' table (a PR setting `BOT_DELAYS`), and the MDEs in `docs/mde.md`.
Each is merged to main, so staging runs it first.

**Mon 7 December** (no game night):
1. **Resend Pro**, and check that `render.yaml` gives `fish-production`
   `FISH_SIGNIN_DAILY_LIMIT=1500` ([email.md](email.md) §2).
2. **The rest of the pool** is imported into `Invited` ([email.md](email.md) §1).
3. **The launch deploy.** Check that `./scripts/check.sh` passes on main: from 8 December it
   fails while the bots' table is the stand-in. Then tag main `site-2026.12.07` and push it (§4).
4. **The checks in §2**, with `try_server` now printing `bots:   pilot-2026-12-v1`, or whatever
   version the pilot's table was given.
5. **M3**, scheduled for 9:00 am Tuesday with the pilot's game length
   ([email.md](email.md) §3).

**Tue 8 December.** The site opens at midnight. M3 goes at 9:00 am. During the day:
- `python -m fish_server.stats` in `fish-production`'s Shell every few hours: sign-ups, and
  the held-out cohort's share (about 15%);
- Resend's **Logs** for bounces, and the day's sign-in count well under 1,500;
- `fish-production` → **Logs** for `ERROR` lines;
- replies to M3 in your inbox.

**Wed 9 – Sat 12 December.** `stats` once a day. Answer emails, and requests
([requests.md](requests.md)). Deploy only to fix a fault (§4), and not in the evening.

**Sun 13 December, opening night, 8 – 10 pm.** Watch as on a pilot night ([pilot.md](pilot.md)
§2), on `fish-production`, but don't play. Afterwards, `stats` once more, and a row in §6. Then
the collection routine takes over ([collection.md](collection.md)).

## 4. Deploying a change

1. **Merge it to main.** Staging deploys it once CI passes. Check it there: `try_server`
   against the pilot site, and play through what changed.
2. **Choose the moment:** not on a game night between 7:30 and 10:30 pm. A deploy ends every
   game in progress ([server.md](../server.md) §6), and those games are lost to the study.
3. **Tag it**, from an up-to-date main:

   ```bash
   git switch main && git pull
   git tag site-YYYY.MM.DD          # today, Eastern; .2, .3 for later deploys the same day
   git push origin site-YYYY.MM.DD
   ```

   The Deploy workflow refuses a tag that is not on main, or whose commit's CI did not pass
   (a run cancelled by a newer push doesn't count: tag that newer commit). Render then deploys,
   running migrations first; if they fail, the old version keeps running.
4. **Check it** (§2) once **Events** shows it live.

**Rehearsing a deploy.** **Actions → Deploy → Run workflow**, with a tag that already exists.
It runs both checks and moves nothing.

## 5. Rolling back

If a deploy breaks the site, tag the last good commit of main and push it:

```bash
git tag site-YYYY.MM.DD.N <last good commit>
git push origin site-YYYY.MM.DD.N
```

This works only if that commit has the same newest migration as the one running
(`ls packages/fish-server/migrations/versions` at each). An older version doesn't know the
newer database revision, so its pre-deploy step stops, and the broken version keeps running.
Then fix forward instead: a fix merged to main, then a new tag.

## 6. Record

| Date | What (created, checked, deployed `site-…`, rolled back) | Commit | By |
|---|---|---|---|
