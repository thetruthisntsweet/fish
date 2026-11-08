// The game connection as React state (T3.4): every message is drawn as it arrives, even two
// that arrive back to back (R.2.6), and the connection closes when the screen goes away.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { Table } from "../screens/Table.tsx";
import { FakeSocket, fakeSockets } from "../test/socket.ts";
import { update } from "../test/updates.ts";
import { useGame } from "./useGame.ts";

let latest: () => FakeSocket;
const drawn: (number | null)[] = [];

function Waiting() {
  const game = useGame("ws://fish.test/ws");
  drawn.push(game.state.lobby?.people ?? null);
  return (
    <>
      <p>{game.state.status.kind}</p>
      <p data-testid="people">{game.state.lobby?.people ?? ""}</p>
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

test("each message is on the page before the next one is even read", () => {
  // T3.7: no batching, no delay. Inside one act, as when a busy table sends messages back
  // to back, each push is followed at once by a look at the page.
  render(<Waiting />);
  const seen: string[] = [];
  act(() => {
    latest().hello();
    for (const people of [2, 3, 4, 5]) {
      latest().push(lobby(people));
      seen.push(screen.getByTestId("people").textContent);
    }
  });
  expect(seen).toEqual(["2", "3", "4", "5"]);
});

function AtTheTable() {
  const game = useGame("ws://fish.test/ws");
  return game.state.update === null ? null : (
    <Table update={game.state.update} drawn={game.state.updates} />
  );
}

test("the table shows each update, and how many have come, as each arrives", () => {
  const { container } = render(<AtTheTable />);
  const asked = (n: number) =>
    update(
      {
        current: 4,
        last_event: { type: "AskEvent", number: n, asker: 4, target: 1, card: 25, success: false },
      },
      { timers: [{ name: "turn", ms_left: 60_000 }] },
    );
  const drawn: (string | undefined)[] = [];
  act(() => {
    latest().hello();
    for (const n of [0, 1, 2]) {
      latest().push(asked(n));
      const table = container.querySelector<HTMLElement>(".table");
      drawn.push(table?.dataset.updates);
    }
  });
  expect(drawn).toEqual(["1", "2", "3"]);
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
