// Keys for things drawn afresh from each update, such as timers (screens/Countdown.tsx).

const drawn = new WeakMap<object, number>();
let next = 0;

/** A key for timers drawn from `update`: a new one for every update. */
export function keyFor(update: object, name: string): string {
  let id = drawn.get(update);
  if (id === undefined) {
    next += 1;
    id = next;
    drawn.set(update, id);
  }
  return `${name}:${String(id)}`;
}
