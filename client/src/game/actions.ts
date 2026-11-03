// The server's action numbers (fish-action-index-v1, docs/determinism.md §9), read from the
// player's own seat. The server says which numbers a player may send (update.actions); the
// client only names them and builds the one a player picks, so it holds no rules logic.
import {
  CARDS_PER_SET,
  NUM_CARDS,
  NUM_SETS,
  opponents,
  teammates,
  type Card,
  type Seat,
  type SetId,
} from "./cards.ts";

export const ACTION_INDEX_ENCODING = "fish-action-index-v1";

export const ASK_BASE = 0;
export const CALL_BASE = ASK_BASE + 3 * NUM_CARDS; // 162
export const DECLARE_BASE = CALL_BASE + NUM_SETS; // 171
export const PASS_INDEX = DECLARE_BASE + NUM_SETS; // 180
export const ASSIGN_BASE = PASS_INDEX + 1; // 181
export const NOMINATE_BASE = ASSIGN_BASE + 3 ** CARDS_PER_SET; // 910
export const NUM_ACTIONS = NOMINATE_BASE + 3; // 913

/** A seat action, with real seat numbers rather than team positions. */
export type SeatAction =
  | { readonly kind: "ask"; readonly target: Seat; readonly card: Card }
  | { readonly kind: "call"; readonly set: SetId }
  | { readonly kind: "declare"; readonly set: SetId }
  | { readonly kind: "pass" }
  | { readonly kind: "assign"; readonly holders: readonly Seat[] }
  /** Choose a teammate in the after-call choice, or vote for one (R.5.2). */
  | { readonly kind: "nominate"; readonly seat: Seat };

function at<T>(list: readonly T[], i: number): T {
  const found = list[i];
  if (found === undefined) {
    throw new RangeError(`no entry ${String(i)}`);
  }
  return found;
}

/** The action number `index` stands for when `seat` sends it. */
export function decode(seat: Seat, index: number): SeatAction {
  if (!Number.isInteger(index) || index < 0 || index >= NUM_ACTIONS) {
    throw new RangeError(`not an action number: ${String(index)}`);
  }
  if (index < CALL_BASE) {
    const offset = index - ASK_BASE;
    return {
      kind: "ask",
      target: at(opponents(seat), Math.floor(offset / NUM_CARDS)),
      card: offset % NUM_CARDS,
    };
  }
  if (index < DECLARE_BASE) {
    return { kind: "call", set: index - CALL_BASE };
  }
  if (index < PASS_INDEX) {
    return { kind: "declare", set: index - DECLARE_BASE };
  }
  if (index === PASS_INDEX) {
    return { kind: "pass" };
  }
  const mates = teammates(seat);
  if (index < NOMINATE_BASE) {
    let rest = index - ASSIGN_BASE;
    const holders: Seat[] = [];
    for (let i = 0; i < CARDS_PER_SET; i++) {
      holders.unshift(at(mates, rest % 3)); // the last card is the least significant digit
      rest = Math.floor(rest / 3);
    }
    return { kind: "assign", holders };
  }
  return { kind: "nominate", seat: at(mates, index - NOMINATE_BASE) };
}

function position(seats: readonly Seat[], seat: Seat, what: string): number {
  const i = seats.indexOf(seat);
  if (i < 0) {
    throw new RangeError(`seat ${String(seat)} is not ${what}`);
  }
  return i;
}

/** The number `seat` sends for `action`. */
export function encode(seat: Seat, action: SeatAction): number {
  switch (action.kind) {
    case "ask":
      if (!Number.isInteger(action.card) || action.card < 0 || action.card >= NUM_CARDS) {
        throw new RangeError(`not a card: ${String(action.card)}`);
      }
      return (
        ASK_BASE + NUM_CARDS * position(opponents(seat), action.target, "an opponent") + action.card
      );
    case "call":
    case "declare":
      if (!Number.isInteger(action.set) || action.set < 0 || action.set >= NUM_SETS) {
        throw new RangeError(`not a set: ${String(action.set)}`);
      }
      return (action.kind === "call" ? CALL_BASE : DECLARE_BASE) + action.set;
    case "pass":
      return PASS_INDEX;
    case "assign": {
      if (action.holders.length !== CARDS_PER_SET) {
        throw new RangeError(`a call assigns six cards, not ${String(action.holders.length)}`);
      }
      const mates = teammates(seat);
      return (
        ASSIGN_BASE +
        action.holders.reduce((sum, holder) => 3 * sum + position(mates, holder, "a teammate"), 0)
      );
    }
    case "nominate":
      return NOMINATE_BASE + position(teammates(seat), action.seat, "a teammate");
  }
}
