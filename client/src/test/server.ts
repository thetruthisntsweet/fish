// A stand-in for the server's study and sign-in endpoints, for the client's tests. It
// answers fetch as fish_server.auth does and keeps every request, so a test can check
// exactly what was sent and that nothing was sent before it should be.
import { vi } from "vitest";

export interface Sent {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

export interface FakeServer {
  readonly sent: Sent[];
  version: string;
  withdrawalOpen: boolean;
  /** Null: no one signed in. */
  standing: { accepted: string | null; withdrawn: boolean } | null;
  /** Answers to give instead, by "METHOD /path", once each. */
  readonly next: Map<string, { status: number; body?: unknown }>;
  reachable: boolean;
  /** Requests that changed something: every one but the reads. */
  posts(): Sent[];
}

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

export function fakeServer(): FakeServer {
  const server: FakeServer = {
    sent: [],
    version: "v1.0",
    withdrawalOpen: true,
    standing: null,
    next: new Map(),
    reachable: true,
    posts: () => server.sent.filter((s) => s.method !== "GET"),
  };
  vi.stubGlobal("fetch", (path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    server.sent.push({ method, path, body });
    if (!server.reachable) {
      return Promise.reject(new TypeError("Failed to fetch"));
    }
    const key = `${method} ${path}`;
    const instead = server.next.get(key);
    if (instead !== undefined) {
      server.next.delete(key);
      return Promise.resolve(json(instead.status, instead.body));
    }
    switch (key) {
      case "GET /study":
        return Promise.resolve(
          json(200, {
            version: server.version,
            withdraw_until: server.version === "v1.0" ? "2027-02-14" : "2027-03-31",
            withdrawal_open: server.withdrawalOpen,
          }),
        );
      case "GET /auth/me": {
        const standing = server.standing;
        if (standing === null) {
          return Promise.resolve(json(401, { signed_in: false }));
        }
        return Promise.resolve(
          json(200, {
            signed_in: true,
            study: {
              current: server.version,
              accepted: standing.accepted,
              withdrawn: standing.withdrawn,
              may_play: standing.accepted === server.version && !standing.withdrawn,
            },
          }),
        );
      }
      case "POST /auth/link":
        return Promise.resolve(json(202, { status: "sent" }));
      case "POST /withdraw":
        if (server.standing === null) {
          return Promise.resolve(json(401, { detail: "Sign in first." }));
        }
        if (!server.standing.withdrawn && !server.withdrawalOpen) {
          return Promise.resolve(
            json(409, { detail: "Withdrawing closed at the end of 14 February 2027." }),
          );
        }
        server.standing.withdrawn = true;
        return Promise.resolve(json(204));
      case "POST /auth/sign-out":
        server.standing = null;
        return Promise.resolve(json(204));
      case "POST /consent":
        if (server.standing !== null) {
          server.standing.accepted = server.version;
        }
        return Promise.resolve(json(204));
      default:
        return Promise.resolve(json(404, { detail: "Not Found" }));
    }
  });
  return server;
}
