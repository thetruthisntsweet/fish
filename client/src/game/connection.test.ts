// The game connection (T3.4): hello first, pings answered at once, the latest of everything
// the server says kept, and a dropped connection tried again for about 30 seconds.
import type { Update } from "../generated/Update.ts";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeSocket, fakeSockets } from "../test/socket.ts";
import {
  Connection,
  INITIAL,
  PROTOCOL_VERSION,
  RETRY_S,
  parse,
  receive,
  socketUrl,
  type GameState,
} from "./connection.ts";

const LOBBY = { type: "lobby", waiting: "solo", code: null, people: 4 } as const;
const AWAY = { type: "lobby", waiting: null, code: null, people: 0 } as const;
const UPDATE: Update = {
  type: "update",
  actions: [0],
  bots: [],
  pressable: [],
  timers: [{ name: "turn", ms_left: 60000 }],
  view: {
    encoding: "fish-view-v1",
    seat: 0,
    hand: [0, 1, 2, 3, 4, 5, 6, 7, 8],
    hand_sizes: [9, 9, 9, 9, 9, 9],
    scored_by: [null, null, null, null, null, null, null, null, null],
    phase: "turn",
    current: 0,
    call: null,
    choice: null,
    window: null,
    last_event: null,
    legal: [0],
    outcome: null,
    winner: null,
  },
};
const QUESTION = {
  type: "note_question",
  version: "v1",
  text: "Did you take notes during this game?",
} as const;

let latest: () => FakeSocket;
let states: GameState[];
let connection: Connection;

function now(): GameState {
  const state = states.at(-1);
  if (state === undefined) {
    throw new Error("no state yet");
  }
  return state;
}

beforeEach(() => {
  vi.useFakeTimers();
  latest = fakeSockets();
  states = [];
  connection = new Connection((state) => states.push(state), "ws://fish.test/ws");
  connection.start();
});

afterEach(() => {
  connection.stop();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("the socket is the page's own address", () => {
  expect(socketUrl({ protocol: "https:", host: "fish.example" } as Location)).toBe(
    "wss://fish.example/ws",
  );
  expect(socketUrl({ protocol: "http:", host: "127.0.0.1:5173" } as Location)).toBe(
    "ws://127.0.0.1:5173/ws",
  );
  expect(latest().url).toBe("ws://fish.test/ws");
});

test("hello goes first, and the server's hello opens the connection", () => {
  expect(connection.send({ type: "join_queue" })).toBe(false); // not open yet: nothing sent
  latest().accept();
  expect(latest().sent).toEqual([{ type: "client_hello", protocol_version: PROTOCOL_VERSION }]);
  expect(connection.send({ type: "join_queue" })).toBe(false); // no server hello yet
  latest().hello();
  expect(now().status).toEqual({ kind: "open" });
  expect(connection.send({ type: "join_queue" })).toBe(true);
  expect(latest().sent.at(-1)).toEqual({ type: "join_queue" });
});

test("a ping is answered at once, and changes nothing shown", () => {
  latest().hello();
  const before = states.length;
  latest().push({ type: "ping", nonce: 41 });
  expect(latest().sent.at(-1)).toEqual({ type: "pong", nonce: 41 });
  expect(states.length).toBe(before);
});

test("the latest lobby, update, question, rejection and error are kept", () => {
  latest().hello();
  latest().push(LOBBY);
  expect(now()).toMatchObject({ lobby: LOBBY, atTable: false });
  latest().push(UPDATE);
  expect(now()).toMatchObject({ update: UPDATE, atTable: true, lobby: LOBBY });
  latest().push(QUESTION);
  latest().push(AWAY); // back to the lobby: the last update stays, to show how it ended
  expect(now()).toMatchObject({ update: UPDATE, atTable: false, question: QUESTION });
  connection.answered();
  expect(now().question).toBeNull();
  const rejected = { type: "rejected", reason: "stale", discarded: false } as const;
  latest().push(rejected);
  latest().push(rejected);
  expect(now().rejected).toEqual({ message: rejected, n: 2 }); // shown twice, not once
  const error = { type: "error", code: "not_now", message: "You are not at a table." } as const;
  latest().push(error);
  expect(now().error).toEqual({ message: error, n: 1 });
});

test("a new game's first update puts the old question away", () => {
  const asked = receive({ ...INITIAL, question: QUESTION }, UPDATE);
  expect(asked.question).toBeNull();
});

test("anything that is not a server message is ignored", () => {
  latest().hello();
  const before = states.length;
  for (const raw of ["not json", "[]", '{"type": "surprise"}', "null", '{"no": "type"}']) {
    latest().push(raw);
  }
  expect(states.length).toBe(before);
  expect(parse(new ArrayBuffer(2))).toBeNull();
});

describe("when the connection drops", () => {
  test("it tries again, and the server's hello makes it whole", () => {
    latest().hello();
    latest().drop();
    expect(now().status).toEqual({ kind: "reconnecting", attempt: 1, restart: false });
    expect(connection.send({ type: "leave" })).toBe(false);
    vi.advanceTimersByTime(999);
    expect(FakeSocket.made.length).toBe(1); // not yet: the first wait is a second
    vi.advanceTimersByTime(1);
    expect(FakeSocket.made.length).toBe(2);
    latest().hello();
    expect(now().status).toEqual({ kind: "open" });
    latest().drop(); // a fresh start: the first wait again
    expect(now().status).toMatchObject({ attempt: 1 });
  });

  test("after about 30 seconds without an answer, it stops and can be started again", () => {
    latest().hello();
    expect(RETRY_S.reduce((a, b) => a + b, 0)).toBe(30);
    for (const wait of RETRY_S) {
      latest().drop();
      vi.advanceTimersByTime(1000 * wait);
    }
    latest().drop();
    expect(now().status).toEqual({ kind: "closed", why: "lost" });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.made.length).toBe(RETRY_S.length + 1); // no more tries
    connection.start();
    expect(now().status).toEqual({ kind: "connecting" });
    expect(FakeSocket.made.length).toBe(RETRY_S.length + 2);
  });

  test("a server restart says so, through every try", () => {
    latest().hello();
    latest().drop(1012);
    expect(now().status).toEqual({ kind: "reconnecting", attempt: 1, restart: true });
    vi.advanceTimersByTime(1000 * (RETRY_S[0] ?? 0));
    latest().drop(); // the server is not back yet
    expect(now().status).toEqual({ kind: "reconnecting", attempt: 2, restart: true });
  });

  test.each([
    ["not_signed_in", "signed-out"],
    ["protocol_version", "version"],
  ] as const)("refused for %s, it does not try again", (code, why) => {
    latest().accept();
    latest().push({ type: "error", code, message: "No." });
    latest().drop(1008);
    expect(now().status).toEqual({ kind: "closed", why });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.made.length).toBe(1);
  });

  test("replaced by Fish opened somewhere else, it does not take the game back", () => {
    latest().hello();
    latest().push({ type: "error", code: "not_now", message: "You opened Fish somewhere else." });
    latest().drop(1000);
    expect(now().status).toEqual({ kind: "closed", why: "elsewhere" });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.made.length).toBe(1);
  });
});

test("stopped, it closes the socket, tries nothing more and hears nothing more", () => {
  const socket = latest();
  socket.hello();
  socket.drop();
  connection.stop();
  vi.advanceTimersByTime(60_000);
  expect(FakeSocket.made.length).toBe(1);
  connection.start();
  const before = states.length;
  socket.push(LOBBY); // the old socket is not listened to
  socket.drop();
  expect(states.length).toBe(before);
  connection.stop();
  expect(latest().closedWith).toBe(1000);
});

describe("leaving a table", () => {
  const error = { type: "error", code: "not_now", message: "The game had to stop." } as const;

  test("the last update, and any error sent at the table, are kept to say how it ended", () => {
    const seated = receive(receive(INITIAL, LOBBY), UPDATE);
    expect(seated.ended).toBeNull();
    const stopped = receive(receive(seated, error), AWAY);
    expect(stopped.ended).toEqual({ update: UPDATE, error });
    expect(stopped.tableError).toBeNull();
    expect(receive(stopped, UPDATE).ended).toBeNull(); // a new game
    expect(receive(stopped, LOBBY).ended).toEqual({ update: UPDATE, error }); // still waiting
  });

  test("an error in the lobby is no reason a game ended", () => {
    const waiting = receive(receive(INITIAL, LOBBY), error);
    expect(waiting.tableError).toBeNull();
    const finished = receive(receive(receive(waiting, UPDATE), AWAY), AWAY);
    expect(finished.ended).toEqual({ update: UPDATE, error: null });
  });

  test("moving on forgets it", () => {
    latest().hello();
    latest().push(UPDATE);
    latest().push(AWAY);
    expect(now().ended).not.toBeNull();
    connection.movedOn();
    expect(now().ended).toBeNull();
    const before = states.length;
    connection.movedOn(); // nothing to forget: nothing changes
    expect(states.length).toBe(before);
  });
});
