// Playing (T3.4): the signed-in front page holds the game connection, and shows the lobby,
// the table, or what happened to the connection.
import { useGame } from "../game/useGame.ts";
import type { Closed, Status } from "../game/connection.ts";
import { Lobby } from "./Lobby.tsx";
import { Table } from "./Table.tsx";

interface Props {
  /** The server no longer knows this browser: ask the site again, which shows sign-in. */
  onSignedOut: () => void;
}

export function Play({ onSignedOut }: Props) {
  const game = useGame();
  const { status } = game.state;

  function body() {
    switch (status.kind) {
      case "connecting":
        return <p className="quiet">Connecting…</p>;
      case "reconnecting":
        return <Reconnecting status={status} />;
      case "closed":
        return <ClosedMessage why={status.why} onRetry={game.retry} onSignedOut={onSignedOut} />;
      case "open":
        if (game.state.atTable && game.state.update !== null) {
          return <Table update={game.state.update} />;
        }
        return <Lobby lobby={game.state.lobby} error={game.state.error} send={game.send} />;
    }
  }

  return (
    <section className="panel">
      <h1>Play Fish</h1>
      {body()}
    </section>
  );
}

function Reconnecting({ status }: { status: Extract<Status, { kind: "reconnecting" }> }) {
  return (
    <p className="notice" role="status">
      {status.restart ? "Fish is restarting." : "The connection was lost."} Reconnecting…
    </p>
  );
}

const CLOSED: Record<Closed, { text: string; button: string }> = {
  "signed-out": { text: "You have been signed out. Sign in again to play.", button: "Sign in" },
  version: { text: "Fish has been updated. Reload this page to play.", button: "Reload" },
  elsewhere: {
    text: "Fish is open in another tab or browser. Play there, or play here instead.",
    button: "Play here",
  },
  lost: {
    text: "Fish cannot be reached. Check your connection and try again.",
    button: "Try again",
  },
};

function ClosedMessage({
  why,
  onRetry,
  onSignedOut,
}: {
  why: Closed;
  onRetry: () => void;
  onSignedOut: () => void;
}) {
  const { text, button } = CLOSED[why];
  function act() {
    if (why === "signed-out") {
      onSignedOut();
    } else if (why === "version") {
      window.location.reload();
    } else {
      onRetry();
    }
  }
  return (
    <>
      <p role="alert">{text}</p>
      <div className="actions">
        <button type="button" className="primary" onClick={act}>
          {button}
        </button>
      </div>
    </>
  );
}
