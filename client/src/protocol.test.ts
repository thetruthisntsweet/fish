// Compile-time check that the generated message types exist and have the server's shape.
// If a message changes in Python and the types are regenerated, this file stops compiling
// wherever the client's assumptions no longer hold.
import { expect, test } from "vitest";
import type { ClientHello } from "./generated/ClientHello.ts";
import type { ServerHello } from "./generated/ServerHello.ts";

test("generated message types match the server's messages", () => {
  const hello: ClientHello = { type: "client_hello", protocol_version: 1 };
  const reply: ServerHello = {
    type: "server_hello",
    protocol_version: 1,
    ruleset_version: "1.0",
    rng_algorithm: "splitmix64-sha256-v1",
  };
  expect(hello.type).toBe("client_hello");
  expect(reply.type).toBe("server_hello");
});
