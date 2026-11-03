// What the server offers, sorted by kind (T3.4): nothing added, nothing worked out.
import { expect, test } from "vitest";
import { update } from "../test/updates.ts";
import { ASSIGN_BASE, CALL_BASE, NOMINATE_BASE, PASS_INDEX, encode } from "./actions.ts";
import { offered, offers } from "./offers.ts";

test("asks by opponent, calls, an assignment and nominations, each as offered", () => {
  const actions = [
    encode(1, { kind: "ask", target: 3, card: 2 }),
    encode(1, { kind: "ask", target: 5, card: 2 }),
    encode(1, { kind: "ask", target: 3, card: 3 }),
    CALL_BASE + 4,
    ASSIGN_BASE + 5,
    NOMINATE_BASE + 2,
    PASS_INDEX, // the website never offers one, and the client shows none
  ];
  const can = offers(update({}, { actions, pressable: [1, 8] }));
  expect([...can.asks]).toEqual([
    [3, [2, 3]],
    [5, [2]],
  ]);
  expect(can.calls).toEqual([4]);
  expect(can.assigning).toBe(true);
  expect(can.nominations).toEqual([2]);
  expect(can.pressable).toEqual([1, 8]);
});

test("nothing offered, nothing to do", () => {
  const can = offers(update());
  expect([can.asks.size, can.calls, can.assigning, can.nominations, can.pressable]).toEqual([
    0,
    [],
    false,
    [],
    [],
  ]);
});

test("an action is sent only if the server offers it", () => {
  const ask = { kind: "ask", target: 3, card: 2 } as const;
  const index = encode(1, ask);
  expect(offered(update({}, { actions: [index] }), ask)).toBe(index);
  expect(offered(update(), ask)).toBeNull();
});
