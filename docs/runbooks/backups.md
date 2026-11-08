# Runbook: backups

T3.6. The study's data has two backups besides the database itself:

| Backup | Holds | Goes back | Where | Restores |
|---|---|---|---|---|
| Render's point-in-time recovery | the whole database | any moment in the last 3 days (Hobby workspace), not the last 10 minutes | Render | the database, as a new copy ([restore-drill.md](restore-drill.md)) |
| The weekly corpus copy | the corpus export only: the games that count, pseudonymized ([corpus.md](../corpus.md) §7) | the latest Monday | your laptop, one file | the research data, not the database |

The weekly copy covers what Render's three days can't: a fault noticed late (a bad migration,
a deleted table, a lost database) would otherwise lose everything older. It holds no email
addresses, internal ids or wall-clock times, and its pseudonyms are drawn fresh at every
export, so one week's copy can't be matched to another's. Only one copy is ever kept: each
Monday's replaces the last, so a person who withdraws leaves the laptop within a week, as
they leave every export. It's deleted by **30 June 2027** (§4).

## 1. Set it up (once, before 30 November)

**Time needed:** about 20 minutes.

1. **The folder.** On your laptop:

   ```bash
   mkdir -m 700 ~/FishBackups
   tmutil addexclusion ~/FishBackups   # Time Machine would keep every week's copy
   ```

   Check that FileVault is on (System Settings → Privacy & Security → FileVault), so the
   copy is encrypted at rest. `~/FishBackups` is outside Desktop and Documents, so iCloud
   doesn't sync it. Never put a copy in the repository, or anywhere else.
2. **An SSH key for Render.**

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/render -C "render (laptop)"   # set a passphrase
   pbcopy < ~/.ssh/render.pub
   ```

   In the Render dashboard: **Account Settings → SSH Public Keys → Add SSH Public Key**,
   paste it, and name it `laptop`.
3. **The service's SSH address.** Open the service (`fish-staging` now; `fish-production`
   once it exists, T4.3) → **Connect** → **SSH**. The address looks like
   `srv-abc123@ssh.virginia.render.com`. Note it for each service. Below it is written
   `SRV@ssh.virginia.render.com`.
4. **Try it on the pilot site** once this change is deployed, while the site still holds no
   games:
   - In `fish-staging`'s **Shell**:
     `python -m fish_server.corpus_export --out /tmp/corpus-try.jsonl.gz`. It prints
     `exported: 0`, the file, and its `sha256:`.
   - On your laptop, from the repository:

     ```bash
     scp -s -i ~/.ssh/render SRV@ssh.virginia.render.com:/tmp/corpus-try.jsonl.gz ~/FishBackups/
     uv run python scripts/check_export.py ~/FishBackups/corpus-try.jsonl.gz
     ```

     Expect `PASS` with the same `exported` and `sha256` as the Shell printed.
   - Delete both copies: `rm ~/FishBackups/corpus-try.jsonl.gz` on your laptop and
     `rm /tmp/corpus-try.jsonl.gz` in the Shell.

   If `scp` says `Permission denied (publickey)`, the key isn't in Render yet (step 2) or
   `-i` points at the wrong file. If it says `subsystem request failed`, the image has no
   SFTP server, so check that the deploy included this change.
5. **Record it** in §5.

## 2. Every Monday, 14 December to 15 February

This is part of the Monday routine ([email.md](email.md)). It runs one week past the last game
night, so the last copy holds the whole corpus. Use the production service.

1. **Export**, in `fish-production`'s **Shell**, with that day's date:

   ```bash
   python -m fish_server.corpus_export --out /tmp/corpus-2026-12-14.jsonl.gz
   ```

   It builds one game at a time, so it's safe beside games in progress. Note the
   `exported:`, `people:` and `sha256:` lines it prints.
2. **Copy and check**, on your laptop, from the repository:

   ```bash
   scp -s -i ~/.ssh/render SRV@ssh.virginia.render.com:/tmp/corpus-2026-12-14.jsonl.gz ~/FishBackups/
   uv run python scripts/check_export.py ~/FishBackups/corpus-2026-12-14.jsonl.gz
   ```

   It reads and replays every game. Go on only if it prints `PASS` and the same `exported`,
   `people` and `sha256` as step 1.
3. **Keep only this week's**, on both sides:

   ```bash
   rm ~/FishBackups/corpus-2026-12-07.jsonl.gz   # last week's; none on 14 December
   ls ~/FishBackups                              # one file: this week's
   ```

   and in the Shell `rm /tmp/corpus-*.jsonl.gz`. A deploy or restart would clear the server's
   copy anyway, but don't leave it there.

If step 2 fails, keep last week's copy and run steps 1 and 2 again. If the export itself
prints `FAIL game …`, a stored game no longer replays. That needs looking into before the
next game night, the same as a failed restore drill.

## 3. Restoring from it

If the database is lost beyond Render's three days, the latest copy is the corpus as of that
Monday: every game that counted, in the form the study releases (corpus.md §7). Games played
since then, and everything that isn't the corpus (who signed up, their addresses, consents
and withdrawals), can't be recovered from it. Nor can anyone who withdrew after that Monday be
found in it, since its pseudonyms are linked to nobody. Before using it, ask Dr. Hany how to
treat withdrawals that came in after the copy was made.

## 4. Deleting it, by 30 June 2027

```bash
rm ~/FishBackups/*.jsonl.gz && rmdir ~/FishBackups
rm ~/.ssh/render ~/.ssh/render.pub
```

In Render, delete the `laptop` SSH key (**Account Settings → SSH Public Keys**). Record the
date in §5.

## 5. Record

| Date | What | By |
|---|---|---|
| 2026-11-07 | Set up; trial copy matched (exported 0, same sha256) | Sanjeev |
