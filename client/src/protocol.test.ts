// Compile-time check that the generated message types exist and have the server's shape.
// If a message changes in Python and the types are regenerated, this file stops compiling
// wherever the client's assumptions no longer hold.
import { expect, test } from "vitest";
import type { Act } from "./generated/Act.ts";
import type { ClientHello } from "./generated/ClientHello.ts";
import type { Lobby } from "./generated/Lobby.ts";
import type { NoteAnswer } from "./generated/NoteAnswer.ts";
import type { NoteQuestion } from "./generated/NoteQuestion.ts";
import type { Press } from "./generated/Press.ts";
import type { Rejected } from "./generated/Rejected.ts";
import type { ServerHello } from "./generated/ServerHello.ts";
import type { Update } from "./generated/Update.ts";

test("generated message types match the server's messages", () => {
  const hello: ClientHello = { type: "client_hello", protocol_version: 3 };
  const reply: ServerHello = {
    type: "server_hello",
    protocol_version: 3,
    ruleset_version: "1.1",
    rng_algorithm: "splitmix64-sha256-v1",
  };
  const press: Press = { type: "press", set_id: 3, seen: null };
  const act: Act = { type: "act", index: 0 };
  const lobby: Lobby = { type: "lobby", waiting: "solo", code: null, people: 4 };
  const rejected: Rejected = { type: "rejected", reason: "stale", discarded: false };
  expect([hello.type, reply.type, press.type, act.type]).toEqual([
    "client_hello",
    "server_hello",
    "press",
    "act",
  ]);
  const question: NoteQuestion = {
    type: "note_question",
    version: "v1",
    text: "Did you take notes during this game?",
  };
  const answer: NoteAnswer = { type: "note_answer", answer: "no" };
  expect([lobby.type, rejected.type]).toEqual(["lobby", "rejected"]);
  expect([question.type, answer.type]).toEqual(["note_question", "note_answer"]);
});

test("an update carries the seat's fish-view-v1 view", () => {
  const update: Update = {
    type: "update",
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
      last_event: {
        type: "AskEvent",
        number: 0,
        asker: 0,
        target: 3,
        card: 9,
        success: false,
      },
      outcome: null,
      winner: null,
      legal: [10, 11],
    },
    actions: [10, 11],
    pressable: [0, 1, 2, 3, 4, 5, 6, 7, 8],
    timers: [{ name: "turn", ms_left: 60000 }],
    bots: [],
  };
  expect(update.view.encoding).toBe("fish-view-v1");
});
