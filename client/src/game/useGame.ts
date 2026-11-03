// The game connection as React state (T3.4). Each message from the server is drawn the moment
// it arrives, one at a time, never batched with the next (R.2.6): React would otherwise draw
// two messages that arrive close together as one, and a player would never see the first.
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Connection, INITIAL, type ClientMessage, type GameState } from "./connection.ts";

export interface Game {
  readonly state: GameState;
  /** Send a message; false if the connection is not open, so nothing was sent. */
  readonly send: (message: ClientMessage) => boolean;
  /** The note-taking question was answered: stop showing it. */
  readonly answered: () => void;
  /** Try again after the connection closed for good. */
  readonly retry: () => void;
}

/** Open the game connection while the component is shown. */
export function useGame(url?: string): Game {
  const [state, setState] = useState<GameState>(INITIAL);
  const connection = useRef<Connection | null>(null);

  useEffect(() => {
    const opened = new Connection((next) => {
      flushSync(() => {
        setState(next);
      });
    }, url);
    connection.current = opened;
    opened.start();
    return () => {
      opened.stop();
      connection.current = null;
    };
  }, [url]);

  return {
    state,
    send: (message) => connection.current?.send(message) ?? false,
    answered: () => connection.current?.answered(),
    retry: () => connection.current?.start(),
  };
}
