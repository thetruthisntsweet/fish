# Runbook: backup-restore drill (staging)

T2.1 subtask 13. Proves that Render's point-in-time recovery brings data back, before any
real participant data depends on it. Repeat before launch (T3.6) and after any change to
the database setup.

**Time needed:** about 45 minutes, most of it waiting.
**Cost:** the restored database is a second $6/month database for the hour it exists,
billed by the second; delete it at the end.

## How Render restores

A point-in-time restore never overwrites the original. It creates a **new** database as the
original was at the chosen moment, with its own connection URL. Hobby workspaces can go back
3 days; Pro and above, 7. You cannot restore to within 10 minutes of the current time.

## Steps

All commands run in the **Shell** page of the `fish-staging` web service in the Render
Dashboard. The database accepts no outside connections, so the server is the way in.

1. **Write the marker.**
   `python -m fish_server.restore_drill mark`
   Note the database time it prints. This is **T-mark**.
2. **Wait at least 10 minutes.** Render cannot restore to a time that recent.
3. **Cause the "accident".**
   `python -m fish_server.restore_drill damage` (prints `Deleted 1 marker row(s)`)
   `python -m fish_server.restore_drill check` (prints `FAIL: marker not found.`: it is gone)
   Note the time. This is **T-damage**.
4. **Restore.** Dashboard → `fish-staging-db` → **Recovery** → **Restore Database**.
   Name it `fish-staging-db-drill`. Choose a time between T-mark and T-damage (times are in
   your browser's time zone; T-mark was printed with its UTC offset, e.g. `+00:00`). Keep **Copy Existing Settings**.
   Click **Start Recovery** and wait for the status to reach **Available**.
5. **Check the restored copy.** Open `fish-staging-db-drill` → **Connect** → copy the
   **Internal Database URL**. In the server's Shell:
   `python -m fish_server.restore_drill check --url '<paste the internal URL>'`
   Expect `PASS: marker present.`
6. **Clean up.**
   - Delete `fish-staging-db-drill` (its **Settings** page → **Delete Database**).
   - In the server's Shell: `python -m fish_server.restore_drill cleanup`
7. **Record the result** below.

If step 5 fails, do not delete anything; record what happened and investigate before
launch.

## Results

| Date | T-mark (UTC) | Restored to | Time to Available | Result | By |
|---|---|---|---|---|---|
| 2026-10-14 | 04:52:31 | 04:53 UTC (12:53 AM EDT) | 7 min | PASS | Sanjeev |
