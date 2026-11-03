// The game connection (T3.4): one WebSocket to the server's /ws (docs/server.md §5). It says
// hello, answers every ping at once (the server times round trips with them, R.8.7), and
// keeps the latest of everything the server says, so the screens show exactly that. If the
// connection drops it tries again for about 30 seconds, the time a seat is held for a player
// who disconnected (R.8.4); the server then shows the game again where it stands.
import type { Act } from "../generated/Act.ts";
import type { ClientHello } from "../generated/ClientHello.ts";
import type { CreateRoom } from "../generated/CreateRoom.ts";
import type { JoinQueue } from "../generated/JoinQueue.ts";
import type { JoinRoom } from "../generated/JoinRoom.ts";
import type { Leave } from "../generated/Leave.ts";
import type { Lobby } from "../generated/Lobby.ts";
import type { NoteAnswer } from "../generated/NoteAnswer.ts";
import type { NoteQuestion } from "../generated/NoteQuestion.ts";
import type { Ping } from "../generated/Ping.ts";
import type { Pong } from "../generated/Pong.ts";
import type { Press } from "../generated/Press.ts";
import type { Rejected } from "../generated/Rejected.ts";
import type { ServerError } from "../generated/ServerError.ts";
import type { ServerHello } from "../generated/ServerHello.ts";
import type { Update } from "../generated/Update.ts";

/** The message format this client speaks; fish_server.protocol.PROTOCOL_VERSION. */
export const PROTOCOL_VERSION = 3;

export type ServerMessage =
  ServerHello | Lobby | Update | Rejected | Ping | NoteQuestion | ServerError;

/** What a player may send once the connection is open (hello and pong are sent for them). */
export type ClientMessage = JoinQueue | CreateRoom | JoinRoom | Leave | Press | Act | NoteAnswer;

/** Seconds between attempts to reconnect: about 30 in all, then the player is asked. */
export const RETRY_S: readonly number[] = [1, 2, 4, 8, 15];

/** Why the connection is closed for good, until the player asks to try again. */
export type Closed =
  | "signed-out" // the server has no session for this browser (1008)
  | "version" // this page is older than the server: reload it (1008)
  | "elsewhere" // the player opened Fish in another tab or browser
  | "lost"; // no answer after every retry

export type Status =
  | { readonly kind: "connecting" }
  | { readonly kind: "open" }
  /** The connection dropped; `restart` if the server said it was restarting (1012). */
  | { readonly kind: "reconnecting"; readonly attempt: number; readonly restart: boolean }
  | { readonly kind: "closed"; readonly why: Closed };

/** A message to show once; `n` tells two identical ones apart. */
export interface Notice<T> {
  readonly message: T;
  readonly n: number;
}

export interface GameState {
  readonly status: Status;
  /** The latest lobby message: where the player waits, if anywhere. */
  readonly lobby: Lobby | null;
  /** The latest update; kept after the player leaves the table, to show how it ended. */
  readonly update: Update | null;
  /** Whether the player is at a table: the latest of lobby and update was an update. */
  readonly atTable: boolean;
  /** The note-taking question, until it is answered. */
  readonly question: NoteQuestion | null;
  /** The latest input the server did not apply (R.8.3, R.8.7). */
  readonly rejected: Notice<Rejected> | null;
  /** The latest error the server sent, in its own words. */
  readonly error: Notice<ServerError> | null;
  /** The game the player just left, to say how it ended, until they move on. */
  readonly ended: Ended | null;
  /** An error the server sent while the player was at the table: why a game had to stop. */
  readonly tableError: ServerError | null;
}

/** A game the player has left: its last update, and the error that ended it, if one did. */
export interface Ended {
  readonly update: Update;
  readonly error: ServerError | null;
}

export const INITIAL: GameState = {
  status: { kind: "connecting" },
  lobby: null,
  update: null,
  atTable: false,
  question: null,
  rejected: null,
  error: null,
  ended: null,
  tableError: null,
};

/** The state after the server sent `message`. */
export function receive(state: GameState, message: ServerMessage): GameState {
  switch (message.type) {
    case "server_hello":
      return { ...state, status: { kind: "open" } };
    case "lobby": {
      const left = state.atTable && state.update !== null;
      const ended = left ? { update: state.update, error: state.tableError } : state.ended;
      return { ...state, lobby: message, atTable: false, ended, tableError: null };
    }
    case "update":
      return { ...state, update: message, atTable: true, question: null, ended: null };
    case "note_question":
      return { ...state, question: message };
    case "rejected":
      return { ...state, rejected: { message, n: (state.rejected?.n ?? 0) + 1 } };
    case "error": {
      const error = { message, n: (state.error?.n ?? 0) + 1 };
      return { ...state, error, tableError: state.atTable ? message : state.tableError };
    }
    case "ping":
      return state; // answered by the connection itself
  }
}

const SERVER_TYPES = new Set<string>([
  "server_hello",
  "lobby",
  "update",
  "rejected",
  "ping",
  "note_question",
  "error",
]);

/** A message from the server, or null for anything this client cannot read. */
export function parse(raw: unknown): ServerMessage | null {
  if (typeof raw !== "string") {
    return null;
  }
  try {
    const data: unknown = JSON.parse(raw);
    if (typeof data === "object" && data !== null && "type" in data) {
      const type = data.type;
      if (typeof type === "string" && SERVER_TYPES.has(type)) {
        return data as ServerMessage;
      }
    }
  } catch {
    // not JSON
  }
  return null;
}

/** Where the game socket is: the page's own address, so the session cookie goes with it. */
export function socketUrl(location: Location = window.location): string {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
}

const POLICY_VIOLATION = 1008; // not signed in, or the wrong protocol version
const SERVICE_RESTART = 1012;
const NORMAL = 1000; // the server closed it on purpose: a newer connection replaced it

/** One player's game connection. `onChange` hears every new state, one message at a time. */
export class Connection {
  private socket: WebSocket | null = null;
  private state: GameState = INITIAL;
  private attempt = 0;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private lastError: ServerError | null = null;

  private readonly onChange: (state: GameState) => void;
  private readonly url: string;

  constructor(onChange: (state: GameState) => void, url: string = socketUrl()) {
    this.onChange = onChange;
    this.url = url;
  }

  /** Open the connection (again, after it closed for good). */
  start(): void {
    this.stopped = false;
    this.attempt = 0;
    this.open();
  }

  /** Close it, and try no more: the page is going away. */
  stop(): void {
    this.stopped = true;
    if (this.retry !== null) {
      clearTimeout(this.retry);
      this.retry = null;
    }
    this.socket?.close(NORMAL);
    this.socket = null;
  }

  /** Send a message; false if the connection is not open, so nothing was sent. */
  send(message: ClientMessage): boolean {
    if (this.state.status.kind !== "open" || this.socket?.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify(message));
    return true;
  }

  /** Forget the note-taking question once answered. */
  answered(): void {
    this.set({ ...this.state, question: null });
  }

  /** Forget how the last game ended: the player has moved on. */
  movedOn(): void {
    if (this.state.ended !== null) {
      this.set({ ...this.state, ended: null });
    }
  }

  private set(state: GameState): void {
    this.state = state;
    this.onChange(state);
  }

  private open(): void {
    if (this.attempt === 0 && this.state.status.kind !== "connecting") {
      this.set({ ...this.state, status: { kind: "connecting" } });
    }
    this.lastError = null;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      const hello: ClientHello = { type: "client_hello", protocol_version: PROTOCOL_VERSION };
      socket.send(JSON.stringify(hello));
    };
    socket.onmessage = (event: MessageEvent) => {
      const message = parse(event.data);
      if (message === null || this.socket !== socket) {
        return;
      }
      if (message.type === "ping") {
        const pong: Pong = { type: "pong", nonce: message.nonce };
        socket.send(JSON.stringify(pong)); // at once, before anything is drawn
        return;
      }
      if (message.type === "server_hello") {
        this.attempt = 0;
      }
      if (message.type === "error") {
        this.lastError = message;
      }
      this.set(receive(this.state, message));
    };
    socket.onclose = (event: CloseEvent) => {
      if (this.socket !== socket || this.stopped) {
        return;
      }
      this.socket = null;
      this.closed(event.code);
    };
  }

  private closed(code: number): void {
    if (code === POLICY_VIOLATION) {
      const version = this.lastError?.code === "protocol_version";
      this.finish(version ? "version" : "signed-out");
      return;
    }
    if (code === NORMAL) {
      this.finish("elsewhere");
      return;
    }
    const wait = RETRY_S[this.attempt];
    if (wait === undefined) {
      this.finish("lost");
      return;
    }
    this.attempt += 1;
    const was = this.state.status;
    const restart = code === SERVICE_RESTART || (was.kind === "reconnecting" && was.restart);
    this.set({ ...this.state, status: { kind: "reconnecting", attempt: this.attempt, restart } });
    this.retry = setTimeout(() => {
      this.retry = null;
      this.open();
    }, wait * 1000);
  }

  private finish(why: Closed): void {
    this.set({ ...this.state, status: { kind: "closed", why } });
  }
}
