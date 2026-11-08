// A stand-in for the browser's WebSocket, for the client's tests: it keeps every socket made
// and everything sent on it, and lets a test open it, send it messages as the server would,
// and close it with a code.
import { vi } from "vitest";

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  /** Every socket made, oldest first. */
  static made: FakeSocket[] = [];

  readyState = FakeSocket.CONNECTING;
  readonly sent: unknown[] = [];
  closedWith: number | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.made.push(this);
  }

  send(data: string): void {
    if (this.readyState !== FakeSocket.OPEN) {
      throw new Error("sent on a socket that is not open");
    }
    this.sent.push(JSON.parse(data));
  }

  /** The client closed it. */
  close(code = 1000): void {
    this.closedWith = code;
    this.readyState = FakeSocket.CLOSED;
  }

  // ------------------------------------------------ the server's side

  /** The connection opened. */
  accept(): void {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  /** The server sends `message` (an object, sent as JSON, or a raw string). */
  push(message: unknown): void {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }

  /** The connection closed from the server's side, or dropped. */
  drop(code = 1006): void {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.({ code });
  }

  /** Accept, and answer the hello as the server does. */
  hello(): void {
    this.accept();
    this.push({
      type: "server_hello",
      protocol_version: 3,
      ruleset_version: "1.2",
      rng_algorithm: "splitmix64-sha256-v1",
    });
  }
}

/** Use FakeSocket for WebSocket in this test; returns the latest socket made. */
export function fakeSockets(): () => FakeSocket {
  FakeSocket.made = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  return () => {
    const latest = FakeSocket.made.at(-1);
    if (latest === undefined) {
      throw new Error("no socket was made");
    }
    return latest;
  };
}
