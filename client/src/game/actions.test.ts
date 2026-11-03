// The action numbers (T3.4), checked against every one of the 913 in the frozen vectors for
// seat 1 (team 0) and seat 4 (team 1) (docs/determinism.md §9), both ways.
import { describe, expect, test } from "vitest";
import { vector } from "../test/vectors.ts";
import { ACTION_INDEX_ENCODING, NUM_ACTIONS, decode, encode, type SeatAction } from "./actions.ts";

interface Frozen {
  encoding: string;
  num_actions: number;
  seats: Record<string, [number, Record<string, unknown>][]>;
}

const frozen = vector("action_index_v1.json") as Frozen;

/** A vector's action (fish-actions-v1) as the client names it. */
function expected(action: Record<string, unknown>): SeatAction {
  switch (action.type) {
    case "Ask":
      return { kind: "ask", target: action.target as number, card: action.card as number };
    case "Call":
      return { kind: "call", set: action.set_id as number };
    case "Declare":
      return { kind: "declare", set: action.set_id as number };
    case "Pass":
      return { kind: "pass" };
    case "Assign":
      return { kind: "assign", holders: action.holders as number[] };
    case "Choose":
    case "Vote":
      return { kind: "nominate", seat: action.chosen as number };
    default:
      throw new Error(`unexpected ${JSON.stringify(action)}`);
  }
}

test("the layout is the frozen one", () => {
  expect(frozen.encoding).toBe(ACTION_INDEX_ENCODING);
  expect(frozen.num_actions).toBe(NUM_ACTIONS);
  expect(Object.keys(frozen.seats)).toEqual(["1", "4"]);
});

describe.each(["1", "4"])("from seat %s", (name) => {
  const seat = Number(name);
  const entries = frozen.seats[name] ?? [];

  test("all 913 numbers are listed", () => {
    expect(entries.map(([index]) => index)).toEqual(
      Array.from({ length: NUM_ACTIONS }, (_, i) => i),
    );
  });

  test("every number decodes to the frozen action and encodes back", () => {
    for (const [index, action] of entries) {
      const named = expected(action);
      expect(action.seat).toBe(seat);
      expect(decode(seat, index)).toEqual(named);
      expect(encode(seat, named)).toBe(index);
    }
  });
});

test("anything else is refused", () => {
  for (const bad of [-1, NUM_ACTIONS, 2.5]) {
    expect(() => decode(0, bad)).toThrow(RangeError);
  }
  expect(() => encode(0, { kind: "ask", target: 1, card: 0 })).toThrow("not an opponent");
  expect(() => encode(0, { kind: "ask", target: 3, card: 54 })).toThrow("not a card");
  expect(() => encode(0, { kind: "call", set: 9 })).toThrow("not a set");
  expect(() => encode(0, { kind: "assign", holders: [0, 1, 2] })).toThrow("six cards");
  expect(() => encode(0, { kind: "assign", holders: [0, 1, 2, 3, 0, 1] })).toThrow(
    "not a teammate",
  );
  expect(() => encode(4, { kind: "nominate", seat: 0 })).toThrow("not a teammate");
});
