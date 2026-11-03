// What the server lets this seat do now (update.actions and update.pressable), sorted by
// kind so the screens can offer each (T3.4). The server decides every one; the client never
// adds an action or works out whether one is legal.
import type { Update } from "../generated/Update.ts";
import { decode, encode, type SeatAction } from "./actions.ts";
import type { Card, Seat, SetId } from "./cards.ts";

export interface Offers {
  /** Asks, by opponent: the cards this seat may ask each one for (R.3.2). */
  readonly asks: ReadonlyMap<Seat, readonly Card[]>;
  /** Sets this seat may call with an action: run-out (R.6.2), or a turn with no ask left. */
  readonly calls: readonly SetId[];
  /** Whether this seat is assigning a call's six cards (R.4.3). */
  readonly assigning: boolean;
  /** Teammates this seat may choose, or vote for, to take the turn (R.5.2). */
  readonly nominations: readonly Seat[];
  /** Sets this seat may press Call on (R.8.3). */
  readonly pressable: readonly SetId[];
}

export function offers(update: Update): Offers {
  const seat = update.view.seat;
  const asks = new Map<Seat, Card[]>();
  const calls: SetId[] = [];
  const nominations: Seat[] = [];
  let assigning = false;
  for (const index of update.actions) {
    const action: SeatAction = decode(seat, index);
    switch (action.kind) {
      case "ask":
        asks.set(action.target, [...(asks.get(action.target) ?? []), action.card]);
        break;
      case "call":
        calls.push(action.set);
        break;
      case "assign":
        assigning = true;
        break;
      case "nominate":
        nominations.push(action.seat);
        break;
      case "declare":
      case "pass":
        break; // the website has no window answers: a call starts with a press
    }
  }
  return { asks, calls, assigning, nominations, pressable: update.pressable };
}

/** The number to send for `action`, if the server offers it; null if it does not. */
export function offered(update: Update, action: SeatAction): number | null {
  const index = encode(update.view.seat, action);
  return update.actions.includes(index) ? index : null;
}
