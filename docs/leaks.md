# Leak audit: what the server sends a player (T3.7)

Everything the server sends to a browser, what each part is computed from, and why that
player may know it. A player may learn only what the rules show them: their own hand, the
public state, the most recent event, and their own answers (Canonical Ruleset R.2; R.4.3 and
R.8.3 for declarations, R.5.2 for votes). That covers a message's **content**, and also
**whether and when** it is sent: a message that arrives because of something hidden tells its
reader that the hidden thing happened.

The audit found two leaks of the second kind, both fixed in T3.7 subtask 2 (§6). Everything
else holds.

What a seat's view may contain is decided once, in `fish_rules.view.project`, and tested
there. `test_view_leaks.py` changes everything hidden from a seat and requires the view not
to move. This audit is the layer around it: the rest of each message, the other messages, and
when they go out.

## 1. On the game socket (`/ws`)

| Message | Sent to | When | Fields, and what they come from | Allowed because |
|---|---|---|---|---|
| `server_hello` | the one connection | once it says hello with the right version | protocol, ruleset and RNG algorithm versions: constants | the same for everyone |
| `lobby` | each person waiting, or no longer waiting | when they join, leave, or the room or queue they wait in changes | `waiting` (solo or group), the room `code` (only to the room's members), `people`: how many are waiting there | their own place; a count, never who |
| `update` | one seat | §3 | §2 | §2, §3 |
| `rejected` | the sender only | an input not applied | `reason` (`illegal`, `stale`, `malformed`), `discarded` (sent while a window was open) | about their own input. `stale` names nothing they won't be shown at once: the update that follows shows the event that made it stale (R.8.7) |
| `ping` | one seat | every 5 s while it is connected | `nonce` | §4 |
| `note_question` | one person | after their game ends, until answered | the question and its version: constants | the same for everyone |
| `error` | the one connection | §1.1 | `code`, `message`: fixed sentences | about their own connection or game |

**1.1 Errors.** `not_signed_in` (no session), `protocol_version` (a stale page), `bad_message`
(unreadable input) and `not_now`. `not_now` covers: a refusal to join (not accepted, withdrawn,
already at a table, a full or unknown room), "You opened Fish somewhere else", why a game had
to stop (the same words to everyone at it), and on coming back, that a bot took their seat or
their game ended (D99). Each one is about the reader's own account, input or game.

**1.2 Closing.** `1008` (not signed in, or wrong version), `1000` (replaced by a newer
connection), `1012` (restarting). None of them carries game information.

**1.3 `/ws/echo`** is the T3.1 connectivity check. It sends `server_hello`, echoes what it is
sent, and reads no game or account.

## 2. An update

| Field | Computed from | Allowed because |
|---|---|---|
| `view` | `project(state, seat, last_event)` | the projection, and its leak tests (R.2) |
| `actions` | `Table.actions(seat)`: the seat's legal actions under website mechanics | they depend on the seat's own hand, the phase and the public state, all in its view |
| `pressable` | `Table.pressable(seat)`: the sets in play, on a turn or in a window the seat hasn't declared in | public, plus the seat's own declaration |
| `timers` | the running window, assignment or choice timer and the turn timer: name and milliseconds to their deadline | every deadline follows from public events: a window lasts exactly 1 s from the press that opened it and never closes early; the others run from the event that started them (R.4.3, R.5.2, R.8.3) |
| `bots` | the seats no person holds | bots are labelled (R.8.4) |

It never contains the game's seed or ID, another seat's hand, declaration or vote, a window's
priority order, any log-only record, whether another person is connected, or anything about
a bot beyond its seat.

## 3. When an update is sent

A seat is sent an update when something it is shown changes, and in a few cases of its own:
on a reconnect or a stale press (the state as it is now, R.8.7), and a last one when its seat
is handed to a bot.

**Finding 1 (fixed).** The server used to send every connected seat an update after **any**
new entry. Two kinds of entry change nothing another seat is shown:
- a **declaration** in an open window: the other five got an update identical to their last
  apart from its timers;
- a **vote** in an after-call choice: only one's own vote is shown (R.5.2).

The update's arrival told everyone that someone had declared or voted, and exactly when. It
didn't say who. Now an update goes to a seat only when its content changes. The time left on
a timer doesn't count as a change, but a timer starting, stopping or moving its deadline does
(`fish_server.game`; tests in `test_game.py`, and over real sockets in `test_end_to_end.py`).

## 4. Pings

The server pings each connected person every 5 seconds to time the round trip
(`round-trip time` in the Research Plan §6).

**Finding 2 (fixed).** The nonce came from one counter shared by the whole game. So the gap
between two pings to a seat counted the pings sent to the other seats meanwhile. When a person
dropped out, their pings stopped and the gaps shrank: the others could tell, up to 30 seconds
before the bot took the seat (R.8.4), and could tell when the person came back. Now each seat
counts its own pings, 1, 2, 3 and so on, and a pong is matched by its seat and nonce together.

## 5. Over HTTP

| Address | Says | To whom |
|---|---|---|
| `/health` | `ok`, the server, ruleset, RNG and protocol versions, and the bots' delay table | anyone: no game or account |
| `/health/db` | whether the database answers, and its migration number, never error details | anyone: no game or account |
| `/study` | the versions of the consent text and terms shown, the last day to withdraw, whether that is still open, and, while the site takes no new tables, why (`tables`) | anyone: the same for everyone |
| `/auth/me` | whether this browser is signed in, and the person's own standing (versions accepted, withdrawn, may play) | the person only, by their session cookie |
| `POST /auth/link` | 202 whether or not the address has an account; 422 for a bad address or acceptance; 429 past the hourly or daily limit | says nothing about any other person, or about whether the address has played |
| `/sign-in`, `POST /auth/verify` | the page that signs in with a link, and the session cookie, or a sentence that the link has expired or been used | the link's holder |
| `POST /consent`, `/withdraw`, `/auth/sign-out` | 204, or a refusal about the person's own standing | the person only |
| the pages, `/assets/…`, `/favicon.svg` | the built client: the same files for everyone | anyone. The client holds every text, version and rule label, and nothing per player or per game |

Unknown paths get the standard 404, and `/health/db` names no host in an error.

## 6. Findings

| | Finding | Reveals | Fix | Status |
|---|---|---|---|---|
| 1 | Every entry sent every seat an update | that someone declared in a window, or voted in a choice, and when (R.4.3, R.5.2, R.8.3) | an update only when the seat's own content changes (T3.7 subtask 2) | fixed |
| 2 | Ping nonces came from one counter for the whole game | whether another person is connected, before a bot takes the seat (R.8.4) | a counter per seat (T3.7 subtask 2) | fixed |

## 7. How it's tested

- **What a view may hold:** `fish-rules/tests/test_view_leaks.py` (T2.4, D32).
- **Everything else in an update:** `fish-server/tests/test_wire_leaks.py`. At every step of
  whole random games played through `Game`, with people coming and going and bots taking
  their seats, every seat's whole update is unchanged when everything hidden from it is
  scrambled. That means the other hands (sizes kept), the seed, other seats' window answers
  and votes, and who else is connected or away. Also: a rejection goes only to the seat whose
  input it rejects, and each seat's pings are numbered 1, 2, 3 on their own.
- **When updates are sent:** `test_game.py`. A declaration or a vote reaches only its maker,
  and no seat is ever sent an update showing it nothing new. With the test above, that makes
  whether a seat is sent an update depend only on what it may know: it compares two updates
  that each do. `test_end_to_end.py` checks a declaration and pings over real sockets.

Each test fails on the leak it guards against: the two findings' tests on the code before
their fixes, and the wire test on an update made to read another seat's hand, or whether
another person is connected. The wire test runs 10 games in development, 25 in CI and 1,250
nightly.

## 8. What clients send

`client_hello`, `join_queue`, `create_room`, `join_room` (a room code), `leave`, `press` (a set
and the last event seen), `act` (an action index), `note_answer` and `pong` (the nonce back).
Each carries only what its sender already knows, and goes only to the server. No other
player ever sees it except as what the rules then show: a window opening, an action applied.
