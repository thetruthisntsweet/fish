// Room codes (T3.4): the client accepts exactly the codes the server does.
import { expect, test } from "vitest";
import { ROOM_CODE_ALPHABET, ROOM_CODE_PATTERN, asCode } from "./rooms.ts";

const SCHEMAS = import.meta.glob<unknown>("../../../schemas/JoinRoom.json", {
  eager: true,
  import: "default",
});

test("a room code is the pattern the server's JoinRoom schema allows", () => {
  const schema = Object.values(SCHEMAS)[0] as
    { properties: { code: { pattern: string } } } | undefined;
  expect(schema?.properties.code.pattern).toBe(ROOM_CODE_PATTERN);
  expect(ROOM_CODE_ALPHABET).not.toMatch(/[IO01]/);
});

test("what someone types becomes a code", () => {
  expect(asCode(" k7m-p2q ")).toBe("K7MP2Q");
  expect(new RegExp(ROOM_CODE_PATTERN).test(asCode("k7m p2q"))).toBe(true);
  expect(new RegExp(ROOM_CODE_PATTERN).test(asCode("K7MP2O"))).toBe(false); // an O
  expect(new RegExp(ROOM_CODE_PATTERN).test(asCode("K7MP2"))).toBe(false); // five
});
