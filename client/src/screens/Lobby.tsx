// The lobby (T3.4; docs/server.md §3): find a table through solo matchmaking, make a room for
// a group and share its code, or join one with a code; then wait, with how many are here, or
// leave. The server says where the player waits (lobby); this screen only asks.
import { useState, type SyntheticEvent } from "react";
import type { Lobby as LobbyMessage } from "../generated/Lobby.ts";
import type { ServerError } from "../generated/ServerError.ts";
import type { ClientMessage, Notice } from "../game/connection.ts";
import { ROOM_CODE_PATTERN, asCode } from "../game/rooms.ts";

const SEATS = 6;

interface Props {
  /** Where the server says this player waits; null until it says. */
  lobby: LobbyMessage | null;
  /** The latest error the server sent, such as why this player may not play. */
  error: Notice<ServerError> | null;
  send: (message: ClientMessage) => boolean;
}

export function Lobby({ lobby, error, send }: Props) {
  const [typed, setTyped] = useState("");
  // Errors from before this screen, or before the player's last request, are not shown.
  const [errorsFrom, setErrorsFrom] = useState(error?.n ?? 0);
  // The lobby message current when the player last asked for something: until a new one
  // (or an error) arrives, the buttons wait, so nothing is asked twice.
  const [askedAt, setAskedAt] = useState<LobbyMessage | null | undefined>(undefined);

  const shownError = error !== null && error.n > errorsFrom ? error.message.message : null;
  const waitingForAnswer = askedAt === lobby && shownError === null;

  function ask(message: ClientMessage) {
    setErrorsFrom(error?.n ?? 0);
    if (send(message)) {
      setAskedAt(lobby);
    }
  }

  const code = asCode(typed);
  const valid = new RegExp(ROOM_CODE_PATTERN).test(code);
  const wrongLetters = /[^A-Z2-9]|[IO]/.test(code); // not in ROOM_CODE_ALPHABET

  function join(event: SyntheticEvent) {
    event.preventDefault();
    if (valid) {
      ask({ type: "join_room", code });
    }
  }

  const problem = shownError !== null && (
    <p className="problem" role="alert">
      {shownError}
    </p>
  );

  if (lobby === null) {
    return <p className="quiet">Loading…</p>;
  }

  if (lobby.waiting !== null) {
    const here = `${String(lobby.people)} of ${String(SEATS)} players are here.`;
    return (
      <>
        {lobby.waiting === "solo" ? (
          <>
            <h2>Finding a table</h2>
            <p role="status">{here} The game starts when six are here.</p>
          </>
        ) : (
          <>
            <h2>Your room</h2>
            <p>Share this code with the people you want to play with:</p>
            <p className="room-code" aria-label="Room code">
              {lobby.code}
            </p>
            <p role="status">{here} The game starts when six are here.</p>
          </>
        )}
        {problem}
        <div className="actions">
          <button
            type="button"
            disabled={waitingForAnswer}
            onClick={() => {
              ask({ type: "leave" });
            }}
          >
            Leave
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <p>Play with five others: three on each team.</p>
      {problem}
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={waitingForAnswer}
          onClick={() => {
            ask({ type: "join_queue" });
          }}
        >
          Find a table
        </button>
        <button
          type="button"
          disabled={waitingForAnswer}
          onClick={() => {
            ask({ type: "create_room" });
          }}
        >
          Make a room for friends
        </button>
      </div>
      <form onSubmit={join}>
        <label className="field">
          <span>Join a room</span>
          <input
            type="text"
            inputMode="text"
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            placeholder="Room code"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
        </label>
        {wrongLetters && (
          <p className="quiet">Room codes have letters and digits, but no I, O, 0 or 1.</p>
        )}
        <div className="actions">
          <button type="submit" disabled={!valid || waitingForAnswer}>
            Join
          </button>
        </div>
      </form>
    </>
  );
}
