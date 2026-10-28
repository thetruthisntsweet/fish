# The game server

How the website's server plays a game (T3.1, T3.2): consent and signing in, matchmaking, the
website's rules around the engine, the messages, what is written to the database as a game
is played, and how a game that cannot go on ends.
The rules are the Canonical Ruleset v1.1 ([rules.md](rules.md)); what is recorded is
[corpus.md](corpus.md). The server is the `fish-server` package, which is not published.

## 1. The pieces

| Module | Does | Touches |
|---|---|---|
| `table` | one game under website mechanics: presses, windows, the timers, people and bots | nothing: times are passed in |
| `game` | one game in progress: who is sent what, pings, the stand-in bot, rows to write | nothing: times are passed in |
| `lobby` | the solo queue and group rooms | nothing |
| `protocol` | every message, as Pydantic models (the client's types are generated from them) | nothing |
| `signin`, `auth`, `mailer` | signing in with an emailed link | the database, Resend |
| `consent`, `withdraw` | acceptances of the consent screen, withdrawals | the database |
| `games` | writing a new table's game, seats and seat flags; endings; the sweep | the database |
| `hub` | connections, the lobby and the games in progress, on one event loop | sockets, the database |
| `app` | the HTTP endpoints and `/ws` | |

Everything that decides something (the table, the game, the lobby) does no input or output,
so the tests drive it on a fake clock and check every rule exactly; the hub and the app only
move messages and rows.

## 2. Consent and signing in

The consent screen comes first (Consent Screen §2; the client builds it, T3.3). `GET /study`
gives the version this site shows (`FISH_CONSENT_VERSION`: `v1.0`, or `v1.0-pilot` on
staging).

1. `POST /auth/link` with `{"email": …, "consent": {"version": …, "us_resident_adult": true,
   "agrees": true, "no_outside_communication": true}}` emails a link (Resend on Render; printed in the
   server's output locally). It answers 202 whether or not the address has played before,
   and 422, storing nothing, for an acceptance of another version or with a box unticked.
   Someone signing in again sends `"consent": null`.
2. The link opens `/sign-in`, a page with one button. Opening it uses nothing: mail scanners
   open links in emails by themselves.
3. Pressing the button posts to `/auth/verify`, which uses the link (once, within 15 minutes)
   and starts a 30-day session in the `HttpOnly` cookie `fish_session`.
4. The first sign-in from an address makes a player: the next sign-up number, and the
   held-out cohort drawn from it at once ([corpus.md](corpus.md) §2.1). Using a link records
   the acceptance it carries (`fish_server.consent`).

Only SHA-256 hashes of links and sessions are stored. Limits: 3 links per address in 15
minutes, 10 requests per network address an hour, and 90 emails a day from the whole server
(`FISH_SIGNIN_DAILY_LIMIT`), under Resend's free 100. `GET /auth/me` says whether a cookie
signs in and where the player stands with the study (the version last accepted, whether
withdrawn, whether they may play); `POST /auth/sign-out` ends the session.

- **A new version** of the text (Consent Screen §2.8): set `FISH_CONSENT_VERSION`, and each
  player accepts it with `POST /consent` before their next game.
- **Withdrawing** on the website: `POST /withdraw` with `{"confirm": true}`. By email: in
  the `fish-staging` (or production) **Shell**, `python -m fish_server.withdraw <address>`.
  Either way it is a record of its own, made once and never undone; every game the person
  played leaves the corpus at the next export, and they cannot play again.
- **Who may play:** only a player who has accepted the current text and not withdrawn may
  join the queue or a room; anyone else is told why.

## 3. Matchmaking

- **Solo:** `join_queue`. There are two queues, the held-out cohort's and everyone else's, so
  cohort players meet only each other. The six who have waited longest form a table; one
  from the cohort queue is a *cohort table*.
- **Group:** `create_room` returns a six-character code (no I, O, 0 or 1); five more join
  with `join_room`. A group table is never a cohort table.
- `leave` stops waiting. A player waits in one place at a time, and not while seated.
- Seats are drawn with the operating system's randomness, and so is each game's seed.

Until T3.5 a table needs six people; bots then fill empty seats.

## 4. The website's rules

The engine has no clock (R.8.6). `Table` adds the website's mechanics and decides no rule
outcome itself (D23):

- **Presses** (R.8.3). Call is always live: a press names a set and opens a 1-second window
  with the presser's declaration; presses inside the window declare too. An action sent
  during a window is discarded and the sender told. Presses during an assignment, a choice
  or run-out are rejected (R.6.2).
- **Stale presses** (R.8.7). A press carries the last event its player saw; it is rejected
  only if a newer event scored its set or moved one of its cards.
- **Timers** (R.8.5): window 1 s, assignment 30 s (R.4.3), choice or vote 15 s (R.5.2), turn
  60 s (R.8.4). Each timer's outcome is recorded at its deadline, and an input first lets
  every timer due by its arrival fire. The turn timer stops for a window, an assignment or a
  choice, and every new turn starts a fresh one.
- **People and bots** (R.8.4). A person away for 30 seconds, or who lets the turn timer run
  out, is replaced by a bot for the rest of the game and released to the lobby. Until T3.5
  brings B1 (R.8.8), the bot is a stand-in (`b0-v1`) that waits 2 seconds and chooses among
  the actions the website allows.
- On a turn the current player may only ask: a call starts with a press, like anyone's (R.4.3).

## 5. Messages

Over `/ws`, which needs the session cookie. JSON, every message with a `type`, unknown fields
refused ([`protocol.py`](../packages/fish-server/src/fish_server/protocol.py), protocol 3).

| Client | | Server | |
|---|---|---|---|
| `client_hello` | first, with `protocol_version` | `server_hello` | the versions it runs |
| `join_queue`, `create_room`, `join_room`, `leave` | the lobby | `lobby` | waiting for what, with how many |
| `press` | `set_id` and `seen` | `update` | the seat's `fish-view-v1` view, `actions`, `pressable`, `timers`, `bots` |
| `act` | an action index (`fish-action-index-v1`, from the player's seat) | `rejected` | `illegal`, `stale` or `malformed`; `discarded` in a window |
| `pong` | the `ping`'s nonce | `ping` | every 5 s (R.8.7) |
| `note_answer` | `yes`, `no` or `declined` | `note_question` | after a game the rules ended, to each person still in it: "Did you take notes during this game?" (`v1`) |
| | | `error` | `protocol_version`, `bad_message`, `not_signed_in`, `not_now` |

The view's own `legal` list is the environment's mask; a website client offers exactly
`update.actions` and `update.pressable`.

## 6. What is written, and when

When a table forms: its `games` row and six `seats` rows. Then, as the game is played, every
action (with its cause and its received and sent times, microseconds since the game started
on the server's monotonic clock) and every server log row (connections, round trips,
rejections, handovers), in order, from a writer thread so the database never holds up a
game. When the rules end the game: its `game_endings` row, after the last action. The export
(`python -m fish_server.corpus_export`) reads all of it back as `fish-corpus-v2` records.

Games are held in the one server process's memory, so a game that cannot go on ends
`abandoned` (corpus.md §3), and its players are told why:

- **A deploy or restart:** every player's connection closes with code 1012 (service
  restart), which the client shows as the server restarting; the server then stops every
  game, writes what it has, and ends it `abandoned`. Deploying during real games cuts them
  off, so deploy between game nights.
- **The database unreachable:** each write is retried for about a minute; if it never
  succeeds, the game is stopped and nothing more of it is written.
- **A crash**, or a stop the server could not write: the game has no ending. At start and
  every minute the server marks `abandoned` each game with no ending that is not running in
  it and has written nothing for five minutes. A live game writes every few seconds, so the
  old server's games during a deploy are never caught.

Before an ending is written, the game's stored actions are checked for a gap; a game whose
log could not replay it ends `abandoned`, whatever the rules said.

## 7. Trying it

Locally: start the database and the server ([setup.md](setup.md)), ask for a link with
`curl -X POST localhost:8000/auth/link -H 'content-type: application/json' -d
'{"email":"you@example.org"}'`, open the link the server prints, and press the button.

On staging, sign in in a browser with a real address, copy the `fish_session` cookie's value
from the developer tools, and run:

    uv run python scripts/try_server.py https://<your-staging-host> --session <value>

It checks `/health`, `/auth/me` and the socket (hello, lobby, a room made and left) and prints
PASS.

## 8. How it is checked

`test_table.py` (every website rule, on a fake clock, and random games that must be corpus
records), `test_protocol.py` (the view mirrors `fish-view-v1` exactly; strict parsing),
`test_signin.py`, `test_consent.py` (acceptances, new versions, withdrawals, who may play),
`test_lobby.py`, `test_game.py`, `test_hub.py` (retries, stopping, the sweep, the note-taking
question), `test_endings.py` (endings only on a whole log; the sweep never touching a live
game), `test_ws.py` (real WebSockets, a real database), and `test_end_to_end.py`: the real
server on a real port, and six people who accept the consent screen, ask for a link over
HTTP, use it, connect with the cookie, are matched by the solo queue, play a whole game and
answer the note-taking question. The export reads the game back as a corpus record that
replays to the same end with every seat's flags and note, and leaves it out once one of them
withdraws. A second test stops the server mid-game, as a deploy does: every connection closes
with 1012 and the game ends `abandoned`.
