# Setup

How to get a working copy of Fish on your own machine, the commands you will use every day,
and fixes for the problems people actually hit. Every step here was run on a fresh clone
before it was written down.

## 1. What you need

| Tool | Version | Why |
|---|---|---|
| Git | any recent | version control |
| [uv](https://docs.astral.sh/uv/) | 0.11.32 or newer | installs Python 3.14 and every Python package from `uv.lock` |
| [Node.js](https://nodejs.org/) | 24 LTS (or 22.22.2 or newer) | the client, its tools, and the independent RNG check |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | any recent | runs PostgreSQL 17 locally |
| VS Code | optional | the repository includes shared settings and extension suggestions |

You do not install Python yourself: uv reads `.python-version` and fetches Python 3.14.

## 2. First-time setup

From wherever you keep projects:

```
git clone https://github.com/thetruthisntsweet/fish
cd fish
uv python install
uv sync --all-packages
npm --prefix client ci
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d db
uv run --env-file .env python -m fish_server.deploy
uv run pre-commit install
./scripts/check.sh
```

What each line does:

1. `uv python install` installs the Python version pinned in `.python-version`.
2. `uv sync --all-packages` creates `.venv` with all five packages and their dependencies.
   **Always pass `--all-packages`** (see Troubleshooting).
3. `npm --prefix client ci` installs the client's exact dependencies from
   `client/package-lock.json`. The pre-commit hooks need these too.
4. `cp .env.example .env` creates your local settings. `.env` is never committed.
5. `docker compose … up -d db` starts PostgreSQL on `127.0.0.1:55432`. Wait until
   `docker compose -f infra/docker-compose.yml ps` shows `healthy`.
6. `python -m fish_server.deploy` does what Render does before every deploy: applies the
   migrations, creates the server's own database login (`fish_server`), and checks that
   login can read but not alter. It should end with `Pre-deploy checks passed.`
7. `pre-commit install` turns on the checks that run on every `git commit`. Needed once per
   clone: git does not copy hooks.
8. `./scripts/check.sh` runs every check CI runs. It should end with `All checks passed.`
   and no skipped tests.

## 3. Everyday commands

All from the repository root.

| To… | Run |
|---|---|
| Run every check (same as CI) | `./scripts/check.sh` |
| Run the Python tests only | `uv run --env-file .env pytest` |
| Run one package's tests | `uv run --env-file .env pytest packages/fish-rules` |
| Start the server (reloads on save) | `uv run --env-file .env uvicorn fish_server.app:app --reload` |
| Start the client (http://localhost:5173) | `npm --prefix client run dev` |
| Run the client tests | `npm --prefix client test` |
| Build the published packages, install them as a user would, and run the README examples | `uv run --no-project --python 3.14 python scripts/check_install.py` |
| Make a release | [runbooks/release.md](runbooks/release.md) |
| Export the corpus (docs/corpus.md §7) | `uv run --env-file .env python -m fish_server.corpus_export --out corpus.jsonl` |
| Regenerate client types after changing `protocol.py` | `scripts/gen_types.sh` |
| Create a migration after changing `fish_server/db.py` | `uv run --env-file .env alembic revision --autogenerate --rev-id 0003 -m "what changed"` (next free number; read the file it writes) |
| Apply migrations and refresh the server login | `uv run --env-file .env python -m fish_server.deploy` |
| Check the server login's rights | `uv run --env-file .env python -m fish_server.privileges check` |
| Run the hooks on every file | `uv run pre-commit run --all-files` |
| Hold a WebSocket open to test a server | `uv run python scripts/ws_soak.py ws://localhost:8000/ws/echo --minutes 1 --every 10` |

With the server and client both running, the client's `/api` and `/ws` requests are
forwarded to the server on port 8000.

## 4. The local database

| To… | Run |
|---|---|
| Start | `docker compose -f infra/docker-compose.yml up -d db` |
| Stop (data kept) | `docker compose -f infra/docker-compose.yml down` |
| Wipe everything and start over | `docker compose -f infra/docker-compose.yml down -v`, then start, then `uv run --env-file .env python -m fish_server.deploy` |
| Open a SQL prompt | `docker compose -f infra/docker-compose.yml exec db psql -U fish -d fish` |

Two logins exist locally, as on Render:

- `fish` — the owner. Migrations, the restore drill and admin tools use it.
- `fish_server` — what the running server uses. It may read and add rows, never change or
  delete them, and never create tables.

The test suite creates and drops its own throwaway databases and its own login
(`fish_server_test_<random>`), so running tests never touches your `fish` database or the
`fish_server` password.

## 5. Settings (`.env`)

| Variable | Used by | Meaning |
|---|---|---|
| `FISH_ADMIN_DATABASE_URL` | migrations, `fish_server.deploy`, admin tools | the database as its owner |
| `FISH_APP_DB_PASSWORD` | the server, `fish_server.deploy` | password of the `fish_server` login (16+ characters: letters, digits, `+/=_-.`) |
| `FISH_TEST_DATABASE_URL` | tests | a database on the same server the tests may use to create throwaway databases; unset = database tests skip |
| `FISH_APP_DB_USER` | tests only | overrides the login name; leave unset |
| `HYPOTHESIS_PROFILE` | tests | `dev` (default, 100 examples), `ci` (1,000), `nightly` (50,000); see [testing.md](testing.md) |
| `PORT` | the server image | port to listen on; Render sets it |
| `FISH_EMAIL` | the server | `console` (default: sign-in emails printed in the server's output) or `resend` (sent through Resend; Render) |
| `FISH_RESEND_API_KEY` | the server, with `resend` | Resend key with sending access to the sending domain only; set in Render, never in a file |
| `FISH_EMAIL_FROM` | the server | sender of sign-in emails; defaults to `Fish <signin@mail.thedefinitivesanjeevexperience.com>` |
| `FISH_COHORT_SEED` | the server | 64-bit seed of the held-out cohort draw (corpus.md §2.1); never changed once anyone has signed up |
| `FISH_PUBLIC_URL` | the server | where sign-in links point; defaults to `RENDER_EXTERNAL_URL` (Render sets it), else `http://127.0.0.1:8000` |
| `FISH_SIGNIN_DAILY_LIMIT` | the server | most sign-in emails sent in 24 hours; default 90, under Resend's free 100 a day |

The server's own URL is never written anywhere: it is the admin URL with the user and
password swapped for `fish_server` and `FISH_APP_DB_PASSWORD`.

## 6. Making a change

1. `git checkout main && git pull`, then `git checkout -b <task>-<short-name>`.
   Commits on `main` are refused by a hook.
2. Work. VS Code formats on save; the hooks check each commit.
3. `./scripts/check.sh` before pushing.
4. Push and open a pull request. Five CI checks must pass before merging:
   *Hooks*, *Python tests + coverage + migrations*, *Determinism*, *Client tests + build*,
   *Server image builds and serves*.
5. Merge. Render deploys the new `main` to staging once CI has passed on it.

Changing what the server sends or receives: edit `fish_server/protocol.py`, run
`scripts/gen_types.sh`, fix what `npm --prefix client run typecheck` reports, commit all three
layers together.

Changing the database: edit `fish_server/db.py`, create a migration (table above), read it,
run `fish_server.deploy` locally. New tables automatically give `fish_server` read and insert
rights only. Tables that must never change once written get
`fish_server.privileges.append_only_sql(table)` in their migration.

## 7. Staging on Render

- Server: `fish-staging` (Virginia). Database: `fish-staging-db` (PostgreSQL 17, private
  network only). Configuration: `render.yaml`.
- `GET /health` — is the server up, and which versions it runs.
- `GET /health/db` — can it reach its database, and at which migration.
- Sign-in: `POST /auth/link` with `{"email": …}` emails a link, which opens `/sign-in` with
  one button; pressing it signs in for 30 days (`fish_server.auth`). Locally the link is
  printed in the server's output.
- The game: `/ws`, a WebSocket that needs the session cookie and starts with
  `client_hello` (`fish_server.protocol`, `fish_server.hub`). Games are held in the server's
  memory and written to the database as they happen; a deploy or restart ends any game in
  progress.
- Checking a deploy as a player would: `scripts/try_server.py` ([server.md](server.md) §7).
- The **Shell** page of `fish-staging` runs commands on the server, for example
  `python -m fish_server.privileges check`. The database accepts no connections from outside
  Render, so the Shell is the way in.
- Backups and restores: `docs/runbooks/restore-drill.md`.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Pyright: `Import "fish_env" could not be resolved` (or another package) | `uv add` or a plain `uv sync` installed only part of the workspace. Run `uv sync --all-packages`. |
| `test_import` or `test_packaging` says the version is wrong after pulling a version change | The installed workspace packages still carry the old metadata. Run `uv sync --all-packages`. |
| Database tests show `SKIPPED … FISH_TEST_DATABASE_URL not set` | `.env` is missing, or you ran pytest without `--env-file .env`. `check.sh` loads `.env` itself. |
| `connection refused` on port 55432 | The database is not running: start it (section 4). |
| `/health/db` says `unavailable` locally | The `fish_server` login does not exist or has a different password. Run `uv run --env-file .env python -m fish_server.deploy`. |
| Hook fails: `client/node_modules/.bin/prettier not found` | Run `npm --prefix client ci`. |
| `npm warn EBADENGINE` | Node is older than 22.22.2. Install Node 24 LTS. |
| `don't commit to branch … Failed` | You are on `main`. Create a branch (section 6). |
| `Generated types are out of date` | Run `scripts/gen_types.sh` and commit the result. |
| Port 55432 already in use | Something else uses it. Stop that, or change the port in both `infra/docker-compose.yml` and `.env`. |
