// The table in words (T3.4): seat names from the seat's own side, the most recent event, and
// what the game waits for, a window never saying who declared or which set (R.8.3).
import { describe, expect, test } from "vitest";
import { update } from "../test/updates.ts";
import {
  callHolders,
  endingSentence,
  eventSentence,
  phaseSentence,
  score,
  seatName,
  teamName,
  rejection,
  type LastEvent,
} from "./describe.ts";

const view = (v: Parameters<typeof update>[0]) => update(v).view;

test("seats are named from the player's side, numbered 1 to 6", () => {
  expect([0, 1, 2, 3, 4, 5].map((seat) => seatName(1, seat))).toEqual([
    "Teammate 1",
    "You",
    "Teammate 3",
    "Opponent 4",
    "Opponent 5",
    "Opponent 6",
  ]);
  expect(teamName(4, 1)).toBe("your team");
  expect(teamName(4, 0)).toBe("the other team");
});

describe("the most recent event", () => {
  const ask = { type: "AskEvent", number: 7, card: 37 } as const;

  test("an ask says who asked whom for what, and whether they had it", () => {
    expect(eventSentence(1, { ...ask, asker: 1, target: 4, success: true })).toBe(
      "You asked Opponent 5 for the 10♥: they had it.",
    );
    expect(eventSentence(1, { ...ask, asker: 3, target: 1, success: false })).toBe(
      "Opponent 4 asked you for the 10♥: you did not have it.",
    );
    expect(eventSentence(1, { ...ask, asker: 3, target: 2, success: true })).toBe(
      "Opponent 4 asked Teammate 3 for the 10♥: they had it.",
    );
  });

  test("a call says who called which set, whether it was right, who scored, and where the cards were", () => {
    const call = {
      type: "CallEvent",
      number: 9,
      caller: 0,
      set_id: 2,
      source: "window",
      assignment: [0, 0, 1, 1, 2, 2],
      holders: [0, 0, 1, 1, 2, 3],
      correct: false,
      scored_by: 1,
    } satisfies LastEvent;
    expect(eventSentence(1, call)).toBe(
      "Teammate 1 called Low hearts (2–7): wrong, and the other team scored it.",
    );
    expect(eventSentence(4, { ...call, assignment: null })).toBe(
      "Opponent 1 called Low hearts (2–7): wrong (time ran out), and your team scored it.",
    );
    expect(callHolders(1, call).at(-1)).toEqual({ card: "7♥", holder: "Opponent 4" });
    expect(callHolders(1, { ...ask, asker: 1, target: 4, success: true })).toEqual([]);
  });

  test("a choice says which team chose whom", () => {
    expect(eventSentence(1, { type: "ChoiceEvent", number: 10, team: 0, seat: 1 })).toBe(
      "Your team chose: you take the turn.",
    );
    expect(eventSentence(1, { type: "ChoiceEvent", number: 10, team: 1, seat: 5 })).toBe(
      "The other team chose: Opponent 6 takes the turn.",
    );
  });
});

describe("what the game waits for", () => {
  test("a turn: yours, or someone's", () => {
    expect(phaseSentence(view({ current: 1 }))).toBe("Your turn: ask for a card, or call a set.");
    expect(phaseSentence(view({ current: 4 }))).toBe("Opponent 5's turn.");
  });

  test("a window says only that a call was declared", () => {
    const declared = view({ phase: "window", window: { own_declaration: 3, responded: true } });
    expect(phaseSentence(declared)).toBe("A call has been declared.");
  });

  test("an assignment names the caller and the set, shown to all (R.8.3)", () => {
    expect(phaseSentence(view({ phase: "assign", call: { caller: 1, set_id: 8 } }))).toBe(
      "Your call: put each card of Eights and jokers with the teammate who holds it.",
    );
    expect(phaseSentence(view({ phase: "assign", call: { caller: 5, set_id: 8 } }))).toBe(
      "Opponent 6 is calling Eights and jokers.",
    );
    expect(phaseSentence(view({ phase: "assign" }))).toBe("A call is being made.");
  });

  test("the choice and the vote (R.5.2)", () => {
    const choice = { team: 0, candidates: [0, 1], own_vote: null };
    expect(phaseSentence(view({ phase: "choose", choice: { ...choice, chooser: 1 } }))).toBe(
      "Choose who on your team takes the turn.",
    );
    expect(phaseSentence(view({ phase: "choose", choice: { ...choice, chooser: 2 } }))).toBe(
      "Teammate 3 is choosing who takes the turn.",
    );
    expect(phaseSentence(view({ phase: "vote", choice: { ...choice, chooser: null } }))).toBe(
      "Your team votes on who takes the turn.",
    );
    expect(
      phaseSentence(view({ phase: "vote", choice: { ...choice, team: 1, chooser: null } })),
    ).toBe("The other team is choosing who takes the turn.");
    expect(phaseSentence(view({ phase: "choose" }))).toBe("Choosing who takes the turn.");
  });

  test("run-out names who calls next (R.6.2)", () => {
    expect(phaseSentence(view({ phase: "runout", current: 1 }))).toBe(
      "The other team has no cards: name the next set to call.",
    );
    expect(phaseSentence(view({ phase: "runout", current: 0 }))).toBe(
      "One team has no cards: Teammate 1 names the next set to call.",
    );
  });

  test("the end: won, lost, or stopped at 1,000 asks (R.8.2)", () => {
    expect(
      phaseSentence(view({ phase: "over", current: null, outcome: "finished", winner: 0 })),
    ).toBe("Your team won!");
    expect(
      phaseSentence(view({ phase: "over", current: null, outcome: "finished", winner: 1 })),
    ).toBe("The other team won.");
    expect(phaseSentence(view({ phase: "over", current: null, outcome: "unfinished" }))).toBe(
      "The game stopped at 1,000 asks, with no winner.",
    );
  });
});

test("the score counts each team's sets, the player's team first", () => {
  expect(score(view({ seat: 4, scored_by: [0, 1, 1, null, null, null, null, null, 0] }))).toEqual([
    2, 2,
  ]);
  expect(
    score(view({ seat: 4, scored_by: [0, 0, 1, null, null, null, null, null, null] })),
  ).toEqual([1, 2]);
});

test("a refusal says why the action was not made", () => {
  const rejected = (reason: "illegal" | "stale" | "malformed", discarded = false) =>
    rejection({ type: "rejected", reason, discarded });
  expect(rejected("illegal")).toBe("That is not allowed now. Choose again.");
  expect(rejected("stale")).toBe("That set changed before your call arrived. Choose again.");
  expect(rejected("malformed")).toBe("That could not be sent. Choose again.");
  expect(rejected("illegal", true)).toBe(
    "A call was declared before your action arrived, so it was not made.",
  );
});

describe("how the last game ended", () => {
  const over = (winner: number | null, outcome: "finished" | "unfinished" = "finished") =>
    update({
      phase: "over",
      current: null,
      outcome,
      winner,
      scored_by: [0, 0, 1, 0, 1, 0, 1, 0, null],
    });

  test("a result, with the sets each team scored", () => {
    expect(endingSentence({ update: over(0), error: null })).toBe("Your team won, 5 sets to 3.");
    expect(
      endingSentence({ update: { ...over(0), view: { ...over(0).view, seat: 4 } }, error: null }),
    ).toBe("The other team won, 5 sets to 3.");
    expect(endingSentence({ update: over(null, "unfinished"), error: null })).toBe(
      "The game stopped at 1,000 asks, with no winner. (5 sets to 3.)",
    );
  });

  test("a seat handed to a bot (R.8.4)", () => {
    expect(endingSentence({ update: update({}, { bots: [1] }), error: null })).toMatch(
      /^A bot took over your seat, because you were away for 30 seconds or your turn ran out./,
    );
  });

  test("a game stopped, in the server's words if it gave them", () => {
    const error = { type: "error", code: "not_now", message: "The server is restarting." } as const;
    expect(endingSentence({ update: update(), error })).toBe("The server is restarting.");
    expect(endingSentence({ update: update(), error: null })).toBe("The game had to stop.");
  });
});
