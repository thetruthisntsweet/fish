# The web client

The website players use (T3.3, T3.4): React and TypeScript in `client/`, built by Vite and
served by the game server itself ([server.md](server.md) §2). It holds no rules logic of its
own (Plan §3): it shows what the server sends and offers exactly what the server allows. The
rules are the Canonical Ruleset v1.1 ([rules.md](rules.md)).

## 1. The pages

| Path | Shows |
|---|---|
| `/` | the consent screen to anyone not signed in (or whose accepted text is out of date); signed in, the game (§3) |
| `/information` | the study information the player accepted |
| `/account` | the version accepted, "Withdraw from the study", Sign out |

The study texts are in `client/src/study/texts.ts`, word for word (Consent Screen §1, §4).
Signing in, consenting and withdrawing are described in [server.md](server.md) §2.

## 2. The pieces

| Module | Does |
|---|---|
| `game/cards.ts` | card and set names (`10♥`, `Low hearts (2–7)`), teams and seats from a seat's side |
| `game/actions.ts` | action numbers (`fish-action-index-v1`) read and built, with real seat numbers |
| `game/rooms.ts` | room codes and the link that carries one |
| `game/connection.ts` | the page's one WebSocket to `/ws`: hello, pongs, retries, the latest of every message |
| `game/useGame.ts` | the connection as React state, each message drawn as it arrives |
| `game/offers.ts` | what the server offers this seat now (`update.actions`, `update.pressable`), by kind |
| `game/describe.ts` | the table in words: seat names, the latest event, what the game waits for, how it ended |
| `screens/Play.tsx` | the signed-in front page: the lobby, the table, or the connection's trouble |
| `screens/Lobby.tsx` | finding a table, making or joining a room, waiting |
| `screens/Table.tsx`, `screens/Actions.tsx` | the table, and what the player can do at it |
| `screens/AfterGame.tsx` | how the game ended, and the note-taking question |

Message types come from the server's own models (`client/src/generated/`, made by
`scripts/gen_types.sh`; never written by hand). The client's tests read fish-rules' frozen
vectors, so the client names every card and all 913 action numbers exactly as fish-rules does
(D88), and the server's own schema, so room codes match. A server test checks that the client
speaks the server's protocol version.

## 3. Playing

**The lobby** (docs/server.md §3). *Find a table* joins solo matchmaking; *Make a room for
friends* shows a six-character code and a link (`/?room=CODE`) to share; a link opens the
lobby with its code filled in, and *Join* sends it. (Someone not yet signed in signs in
through the emailed link, which opens a fresh page: they open the room link again, or type
the code.) The screen says how many of the six are
here, and *Leave* stops waiting. The server's refusals are shown in its own words.

**The table** (D90). Seats are numbered 1 to 6 on screen and named from the player's side:
"You", "Teammate 3", "Opponent 5". The other team sits above the player's. Each seat shows its
hand size, and **BOT** where a bot plays it, never which kind (Research Plan §5). The current
player's seat is outlined and carries the turn timer (R.2.6). Below are the latest event in
one sentence, with a call's six true holders (R.2.3), and nothing older (R.2.2); what the game
waits for, where an open window says only that a call was declared (R.8.3); the player's
hand, by set; and the sets scored. Timers count down on the device's clock from the server's
latest figure.

**Acting** (D91). Every action is chosen, then confirmed:

- *Ask for a card* (R.3.2): an opponent, then a card, then "Ask Opponent 4 for the 5♣".
- *Call a set* (R.8.3): a set, then "Call Low clubs (2–7)"; the press carries the last event
  seen (R.8.7). It is offered whenever the server says Call is live.
- *Assigning a call* (R.4.3): a grid, a row per card and a column per teammate, the player's
  own cards already theirs; "Make the call" once all six are placed.
- *Who takes the turn* (R.5.2): a button for each teammate the server lists, to choose or
  vote; a vote shows the player's own.
- *Run-out* (R.6.2): the next set to call.

Once something is sent, the buttons wait for the next update or a rejection, so a double tap
sends it once. A rejection says why: an action sent during a window was discarded because a
call was declared first (R.8.3), or a press was stale (R.8.7).

**After the game** (D92): how it ended (the result and the sets each team scored; a seat
handed to a bot, R.8.4; or a game that had to stop, in the server's words), then the
note-taking question with "Yes", "No" and "Prefer not to say", then the lobby.

## 4. The connection

One WebSocket per page (D89). It sends `client_hello`, answers every `ping` before anything
is drawn (the server times round trips with them, R.8.7), and keeps the latest lobby, update,
question, rejection and error. Each message is drawn with `flushSync`, so two that arrive
back to back are both shown (R.2.6). If the connection drops, it tries again after 1, 2, 4, 8
and 15 seconds, 30 in all, the time a seat is held (R.8.4); the server then shows the game
where it stands. It does not try again when the server refused it (signed out, or a page
older than the server, which says to reload) or when Fish was opened somewhere else, which
says so and offers *Play here*. A restart says "Fish is restarting".

## 5. How it is checked

Vitest with jsdom (`npm --prefix client test`), against stand-ins for the server's
endpoints (`test/server.ts`) and for the WebSocket (`test/socket.ts`): every screen, every
action and the numbers it sends, the connection's retries and close codes, and the sentences.
In a real browser (`pytest -m browser`, [testing.md](testing.md) §4): the consent screen
and the account page, a room made and left, and six people playing a whole game at phone
width, from the lobby to the note-taking question, against the real server and database.
