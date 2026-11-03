// Playing (T3.4): the lobby's three ways to a table, waiting and leaving, the server's
// refusals shown in its own words, and what the player is told when the connection drops or
// closes.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeSocket, fakeSockets } from "../test/socket.ts";
import { update } from "../test/updates.ts";
import { Play } from "./Play.tsx";

let latest: () => FakeSocket;
let signedOut: () => void;

const AWAY = { type: "lobby", waiting: null, code: null, people: 0 };
const button = (name: string) => screen.getByRole<HTMLButtonElement>("button", { name });
const server = (message: unknown) => {
  act(() => {
    latest().push(message);
  });
};

beforeEach(() => {
  latest = fakeSockets();
  signedOut = vi.fn();
  render(<Play onSignedOut={signedOut} />);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function inLobby() {
  act(() => {
    latest().hello();
  });
  server(AWAY);
}

test("it connects first, then shows the lobby", () => {
  expect(screen.getByRole("heading", { name: "Play Fish" })).toBeInTheDocument();
  expect(screen.getByText("Connecting…")).toBeInTheDocument();
  inLobby();
  expect(button("Find a table")).toBeEnabled();
  expect(button("Make a room for friends")).toBeEnabled();
  expect(button("Join")).toBeDisabled(); // no code yet
});

test("finding a table: asked once, then waiting with the count, then leaving", () => {
  inLobby();
  fireEvent.click(button("Find a table"));
  expect(latest().sent.at(-1)).toEqual({ type: "join_queue" });
  expect(button("Find a table")).toBeDisabled(); // until the server answers
  server({ type: "lobby", waiting: "solo", code: null, people: 3 });
  expect(screen.getByRole("status")).toHaveTextContent("3 of 6 players are here.");
  fireEvent.click(button("Leave"));
  expect(latest().sent.at(-1)).toEqual({ type: "leave" });
  server(AWAY);
  expect(button("Find a table")).toBeEnabled();
});

test("making a room shows its code to share", () => {
  inLobby();
  fireEvent.click(button("Make a room for friends"));
  expect(latest().sent.at(-1)).toEqual({ type: "create_room" });
  server({ type: "lobby", waiting: "group", code: "K7MP2Q", people: 1 });
  expect(screen.getByLabelText("Room code")).toHaveTextContent("K7MP2Q");
  expect(screen.getByRole("status")).toHaveTextContent("1 of 6 players are here.");
});

test("joining a room takes the code however it is typed, and only a real one", () => {
  inLobby();
  const field = screen.getByPlaceholderText("Room code");
  fireEvent.change(field, { target: { value: "k7m-p2o" } });
  expect(screen.getByText(/no I, O, 0 or 1/)).toBeInTheDocument();
  expect(button("Join")).toBeDisabled();
  fireEvent.change(field, { target: { value: "k7m p2q" } });
  expect(screen.queryByText(/no I, O, 0 or 1/)).toBeNull();
  fireEvent.click(button("Join"));
  expect(latest().sent.at(-1)).toEqual({ type: "join_room", code: "K7MP2Q" });
});

test("a refusal is shown in the server's words, and the buttons work again", () => {
  inLobby();
  fireEvent.click(button("Find a table"));
  server({ type: "error", code: "not_now", message: "There is no room with that code." });
  expect(screen.getByRole("alert")).toHaveTextContent("There is no room with that code.");
  expect(button("Find a table")).toBeEnabled();
  fireEvent.click(button("Find a table"));
  expect(screen.queryByRole("alert")).toBeNull(); // asking again puts it away
  server({ type: "error", code: "not_now", message: "The game could not start. Try again." });
  expect(screen.getByRole("alert")).toHaveTextContent("The game could not start."); // unasked
});

test("once seated, the lobby gives way to the game", () => {
  inLobby();
  server(update());
  expect(screen.queryByRole("button", { name: "Find a table" })).toBeNull();
  expect(screen.getByRole("region", { name: "Your hand" })).toBeInTheDocument();
});

test("a dropped connection says it is reconnecting, and why", () => {
  vi.useFakeTimers();
  inLobby();
  act(() => {
    latest().drop(1012);
  });
  expect(screen.getByRole("status")).toHaveTextContent("Fish is restarting. Reconnecting…");
  act(() => {
    vi.advanceTimersByTime(1000);
    latest().hello();
  });
  server(AWAY);
  expect(button("Find a table")).toBeEnabled();
  act(() => {
    latest().drop();
  });
  expect(screen.getByRole("status")).toHaveTextContent("The connection was lost. Reconnecting…");
});

test("signed out, the player is sent to sign in", () => {
  act(() => {
    latest().accept();
    latest().push({ type: "error", code: "not_signed_in", message: "Sign in first." });
    latest().drop(1008);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("You have been signed out.");
  fireEvent.click(button("Sign in"));
  expect(signedOut).toHaveBeenCalledOnce();
});

test("an older page is asked to reload", () => {
  act(() => {
    latest().accept();
    latest().push({ type: "error", code: "protocol_version", message: "Protocol 4." });
    latest().drop(1008);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Reload this page to play.");
  expect(button("Reload")).toBeInTheDocument();
});

test.each([
  [1000, "Fish is open in another tab or browser.", "Play here"],
  [1006, "Fish cannot be reached.", "Try again"],
] as const)("closed with %i, the player can start again", (code, text, name) => {
  vi.useFakeTimers();
  inLobby();
  act(() => {
    latest().drop(code);
    for (let i = 0; i < 6; i++) {
      vi.advanceTimersByTime(15_000);
      if (latest().readyState === FakeSocket.CONNECTING) {
        latest().drop();
      }
    }
  });
  expect(screen.getByRole("alert")).toHaveTextContent(text);
  const before = FakeSocket.made.length;
  fireEvent.click(button(name));
  expect(FakeSocket.made.length).toBe(before + 1);
});

describe("after a game", () => {
  const finished = update({
    phase: "over",
    current: null,
    outcome: "finished",
    winner: 0,
    scored_by: [0, 0, 1, 0, 1, 0, 1, 0, 0],
  });
  const question = {
    type: "note_question",
    version: "v1",
    text: "Did you take notes during this game?",
  };

  test("the result, then the question, then the lobby; playing again puts the result away", () => {
    inLobby();
    server(update());
    server(finished);
    expect(screen.getByRole("status")).toHaveTextContent("Your team won!");
    server(question);
    server(AWAY);
    expect(screen.getByRole("region", { name: "Your last game" })).toHaveTextContent(
      "Your team won, 6 sets to 3.",
    );
    expect(
      screen.getByRole("heading", { name: "Did you take notes during this game?" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find a table" })).toBeNull(); // answer first
    fireEvent.click(button("No"));
    expect(latest().sent.at(-1)).toEqual({ type: "note_answer", answer: "no" });
    expect(screen.queryByRole("heading", { name: /take notes/ })).toBeNull();
    expect(screen.getByRole("region", { name: "Your last game" })).toBeInTheDocument();
    fireEvent.click(button("Find a table"));
    expect(screen.queryByRole("region", { name: "Your last game" })).toBeNull();
  });

  test.each([
    ["yes", "Yes"],
    ["declined", "Prefer not to say"],
  ] as const)("the question can be answered %s", (answer, name) => {
    inLobby();
    server(update());
    server(finished);
    server(question);
    server(AWAY);
    fireEvent.click(button(name));
    expect(latest().sent.at(-1)).toEqual({ type: "note_answer", answer });
  });

  test("a seat handed to a bot says so, and asks nothing (R.8.4)", () => {
    inLobby();
    server(update());
    server(update({}, { bots: [1] }));
    server(AWAY);
    expect(screen.getByRole("region", { name: "Your last game" })).toHaveTextContent(
      "A bot took over your seat",
    );
    expect(screen.queryByRole("heading", { name: /take notes/ })).toBeNull();
    expect(button("Find a table")).toBeEnabled();
  });

  test("a game that had to stop says why, once", () => {
    inLobby();
    server(update());
    server({
      type: "error",
      code: "not_now",
      message: "The game had to stop: the server is restarting.",
    });
    server(AWAY);
    expect(screen.getByRole("region", { name: "Your last game" })).toHaveTextContent(
      "The game had to stop: the server is restarting.",
    );
    expect(screen.queryByRole("alert")).toBeNull(); // not repeated by the lobby
  });
});

describe("coming back", () => {
  const took = "A bot took over your seat while you were away, and that game goes on without you.";

  test("after a drop, the table as it now stands", () => {
    vi.useFakeTimers();
    inLobby();
    server(update());
    act(() => {
      latest().drop();
    });
    expect(screen.getByRole("status")).toHaveTextContent("The connection was lost. Reconnecting…");
    act(() => {
      vi.advanceTimersByTime(1000);
      latest().hello();
    });
    server(update({ current: 1 }, { timers: [{ name: "turn", ms_left: 41_000 }] }));
    expect(screen.getByRole("timer", { name: "Turn" })).toHaveTextContent("41s");
  });

  test("too late, the server's word that a bot took the seat", () => {
    vi.useFakeTimers();
    inLobby();
    server(update());
    act(() => {
      latest().drop();
      vi.advanceTimersByTime(1000);
      latest().hello();
    });
    server({ type: "error", code: "not_now", message: took });
    server(AWAY);
    expect(screen.getByRole("region", { name: "Your last game" })).toHaveTextContent(took);
  });

  test("on a fresh page, the same word above the lobby", () => {
    act(() => {
      latest().hello();
    });
    server({ type: "error", code: "not_now", message: took });
    server(AWAY);
    expect(screen.getByRole("alert")).toHaveTextContent(took);
  });
});
