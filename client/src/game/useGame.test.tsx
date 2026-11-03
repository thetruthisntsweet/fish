// The game connection as React state (T3.4): every message is drawn as it arrives, even two
// that arrive back to back (R.2.6), and the connection closes when the screen goes away.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeSocket, fakeSockets } from "../test/socket.ts";
import { useGame } from "./useGame.ts";

let latest: () => FakeSocket;
const drawn: (number | null)[] = [];

function Waiting() {
  const game = useGame("ws://fish.test/ws");
  drawn.push(game.state.lobby?.people ?? null);
  return (
    <>
      <p>{game.state.status.kind}</p>
      <button
        onClick={() => {
          game.send({ type: "join_queue" });
        }}
      >
        Play
      </button>
      <button
        onClick={() => {
          game.retry();
        }}
      >
        Try again
      </button>
      <button onClick={game.answered}>Answered</button>
    </>
  );
}

const lobby = (people: number) => ({ type: "lobby", waiting: "solo", code: null, people });

beforeEach(() => {
  latest = fakeSockets();
  drawn.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("each message is drawn the moment it arrives, never two at once", () => {
  render(<Waiting />);
  expect(screen.getByText("connecting")).toBeInTheDocument();
  act(() => {
    latest().hello();
  });
  expect(screen.getByText("open")).toBeInTheDocument();
  act(() => {
    latest().push(lobby(4)); // two messages in one go, as a busy table sends them
    latest().push(lobby(5));
  });
  expect(drawn).toContain(4);
  expect(drawn.at(-1)).toBe(5);
});

test("the screen sends through it, can try again, and closes it when it goes", () => {
  const { unmount } = render(<Waiting />);
  act(() => {
    latest().hello();
  });
  act(() => {
    screen.getByText("Play").click();
    screen.getByText("Answered").click();
  });
  expect(latest().sent.at(-1)).toEqual({ type: "join_queue" });
  act(() => {
    latest().drop(1000); // replaced elsewhere: closed for good
  });
  expect(screen.getByText("closed")).toBeInTheDocument();
  act(() => {
    screen.getByText("Try again").click();
  });
  expect(FakeSocket.made.length).toBe(2);
  const open = latest();
  unmount();
  expect(open.closedWith).toBe(1000);
});
