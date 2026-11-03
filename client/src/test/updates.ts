// Updates as the server sends them, for the client's tests: seat 1 (team 0) at the start of a
// game, unless a test says otherwise.
import type { Update } from "../generated/Update.ts";

type View = Update["view"];

export function update(
  view: Partial<View> = {},
  rest: Partial<Omit<Update, "type" | "view">> = {},
): Update {
  return {
    type: "update",
    actions: [],
    pressable: [],
    timers: [],
    bots: [],
    ...rest,
    view: {
      encoding: "fish-view-v1",
      seat: 1,
      hand: [0, 1, 7, 12, 25, 37, 48, 52, 53],
      hand_sizes: [9, 9, 9, 9, 9, 9],
      scored_by: [null, null, null, null, null, null, null, null, null],
      phase: "turn",
      current: 4,
      call: null,
      choice: null,
      window: null,
      last_event: null,
      legal: [],
      outcome: null,
      winner: null,
      ...view,
    },
  };
}
