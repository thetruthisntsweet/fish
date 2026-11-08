// Nothing in the client delays drawing an event (T3.7; R.2.6): no CSS transition or animation,
// and no timer, deferred render or transition in the code, except the two that draw no event.
// A new one fails here until it is shown to draw nothing late and added below, with why.
import { expect, test } from "vitest";

const CODE = import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}", "!./test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});
const STYLES = import.meta.glob<string>("./**/*.css", {
  query: "?raw",
  import: "default",
  eager: true,
});

const DELAYS =
  /\b(setTimeout|setInterval|requestAnimationFrame|requestIdleCallback|queueMicrotask|startTransition|useTransition|useDeferredValue)\b/g;

const ALLOWED: Readonly<Record<string, readonly string[]>> = {
  // Waiting before trying to reconnect: nothing is drawn while the connection is down.
  "./game/connection.ts": ["setTimeout"],
  // Ticking a timer's display down between updates; each update still draws at once.
  "./screens/Countdown.tsx": ["setInterval"],
};

test("the code holds no timer or deferred render but the two allowed", () => {
  expect(Object.keys(CODE).length).toBeGreaterThan(20); // the glob found the client
  const found: Record<string, string[]> = {};
  for (const [path, text] of Object.entries(CODE)) {
    const uses = [...new Set([...text.matchAll(DELAYS)].map((m) => m[1] ?? ""))].sort();
    if (uses.length > 0) {
      found[path] = uses;
    }
  }
  expect(found).toEqual(ALLOWED);
});

test("no style animates or eases anything in", () => {
  expect(Object.keys(STYLES)).toContain("./index.css");
  for (const [path, text] of Object.entries(STYLES)) {
    expect(text, path).not.toMatch(/\b(transition|animation)(-[a-z-]+)?\s*:|@keyframes/);
  }
});
