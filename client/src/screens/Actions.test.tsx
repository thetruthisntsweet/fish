// Taking actions (T3.4): an ask chosen and confirmed (R.3.2), Call pressed naming a set with
// the last event seen (R.8.3, R.8.7), a call's six cards assigned (R.4.3), the choice and
// the vote (R.5.2), run-out's next set (R.6.2), and the server's refusals explained. Only
// what the server offers is offered, and nothing is sent twice.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Rejected } from "../generated/Rejected.ts";
import type { Update } from "../generated/Update.ts";
import { ASSIGN_BASE, CALL_BASE, NOMINATE_BASE, encode } from "../game/actions.ts";
import type { ClientMessage, Notice } from "../game/connection.ts";
import { update } from "../test/updates.ts";
import { Actions } from "./Actions.tsx";

const ALL_ASSIGNMENTS = Array.from({ length: 729 }, (_, i) => ASSIGN_BASE + i);
const button = (name: string | RegExp) => screen.getByRole<HTMLButtonElement>("button", { name });

function show(at: Update, rejected: Notice<Rejected> | null = null) {
  const sent: ClientMessage[] = [];
  const send = vi.fn((message: ClientMessage) => {
    sent.push(message);
    return true;
  });
  const view = render(<Actions update={at} rejected={rejected} send={send} />);
  return {
    sent,
    rerender: (next: Update, r: Notice<Rejected> | null = rejected) => {
      view.rerender(<Actions update={next} rejected={r} send={send} />);
    },
  };
}

test("nothing offered, nothing shown", () => {
  const { container } = render(<Actions update={update()} rejected={null} send={() => true} />);
  expect(container.querySelectorAll("button")).toHaveLength(0);
});

test("an ask: whom, then which card, then confirmed; then wait for the server", () => {
  const actions = [
    encode(1, { kind: "ask", target: 3, card: 2 }),
    encode(1, { kind: "ask", target: 3, card: 40 }),
    encode(1, { kind: "ask", target: 5, card: 2 }),
  ];
  const at = update({ current: 1 }, { actions });
  const { sent, rerender } = show(at);
  expect(screen.queryByRole("button", { name: "Opponent 6" })).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Opponent 5" })).toBeNull(); // nothing to ask
  fireEvent.click(button("Opponent 4"));
  const sets = screen.getAllByRole("group").map((group) => group.getAttribute("aria-label"));
  expect(sets).toEqual(["Low clubs (2–7)", "High hearts (9–A)"]);
  expect(
    within(screen.getByRole("group", { name: "Low clubs (2–7)" })).getByRole("button"),
  ).toHaveTextContent("4♣");
  fireEvent.click(
    within(screen.getByRole("group", { name: "High hearts (9–A)" })).getByRole("button"),
  );
  fireEvent.click(button("Ask Opponent 4 for the K♥"));
  expect(sent).toEqual([{ type: "act", index: encode(1, { kind: "ask", target: 3, card: 40 }) }]);
  expect(button("Opponent 4")).toBeDisabled(); // until the server answers
  rerender(update({ current: 1 }, { actions }));
  expect(button("Opponent 4")).toBeEnabled();
});

test("Call: a set named, confirmed, and pressed with the last event seen", () => {
  const at = update(
    { last_event: { type: "AskEvent", number: 5, asker: 4, target: 1, card: 0, success: false } },
    { pressable: [2, 8] },
  );
  const { sent } = show(at);
  fireEvent.click(button("Call a set"));
  expect(screen.getByRole("region", { name: "Call a set" })).toBeInTheDocument();
  fireEvent.click(button("Not now"));
  expect(screen.queryByRole("region", { name: "Call a set" })).toBeNull();
  fireEvent.click(button("Call a set"));
  fireEvent.click(button("Eights and jokers"));
  fireEvent.click(button("Call Eights and jokers"));
  expect(sent).toEqual([{ type: "press", set_id: 8, seen: 5 }]);
});

test("before any event, a press says it has seen none", () => {
  const { sent } = show(update({}, { pressable: [0] }));
  fireEvent.click(button("Call a set"));
  fireEvent.click(button("Low clubs (2–7)"));
  fireEvent.click(button("Call Low clubs (2–7)"));
  expect(sent).toEqual([{ type: "press", set_id: 0, seen: null }]);
});

test("assigning a call: the player's own cards start with them, and all six are needed", () => {
  const at = update(
    { phase: "assign", call: { caller: 1, set_id: 0 }, hand: [0, 1, 30] },
    { actions: ALL_ASSIGNMENTS },
  );
  const { sent } = show(at);
  const make = button("Make the call");
  expect(make).toBeDisabled();
  const row = (card: string) =>
    within(screen.getByRole("group", { name: `Who holds the ${card}` }));
  expect(row("2♣").getByRole("button", { name: "You" })).toHaveAttribute("aria-pressed", "true");
  expect(row("3♣").getByRole("button", { name: "You" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(row("4♣").getByRole("button", { name: "Teammate 1" }));
  fireEvent.click(row("5♣").getByRole("button", { name: "Teammate 1" }));
  fireEvent.click(row("6♣").getByRole("button", { name: "Teammate 3" }));
  expect(make).toBeDisabled();
  fireEvent.click(row("7♣").getByRole("button", { name: "Teammate 3" }));
  fireEvent.click(row("3♣").getByRole("button", { name: "Teammate 3" })); // changed their mind
  fireEvent.click(make);
  expect(sent).toEqual([
    { type: "act", index: encode(1, { kind: "assign", holders: [1, 2, 0, 0, 2, 2] }) },
  ]);
});

test("someone else's call shows no assignment", () => {
  show(update({ phase: "assign", call: { caller: 0, set_id: 0 } }, { actions: ALL_ASSIGNMENTS }));
  expect(screen.queryByRole("button", { name: "Make the call" })).toBeNull();
});

test("the after-call choice and the vote offer the teammates the server lists", () => {
  const choice = { team: 0, candidates: [0, 2], chooser: 1, own_vote: null };
  const { sent } = show(
    update({ phase: "choose", choice }, { actions: [NOMINATE_BASE + 0, NOMINATE_BASE + 2] }),
  );
  expect(screen.getByRole("heading", { name: "Who takes the turn?" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "You" })).toBeNull();
  fireEvent.click(button("Teammate 3"));
  expect(sent).toEqual([{ type: "act", index: NOMINATE_BASE + 2 }]);
});

test("a vote shows the player's own vote", () => {
  const choice = { team: 1, candidates: [3, 4], chooser: null, own_vote: 3 };
  show(update({ seat: 4, phase: "vote", choice }, { actions: [NOMINATE_BASE, NOMINATE_BASE + 1] }));
  expect(screen.getByRole("heading", { name: "Vote for who takes the turn" })).toBeInTheDocument();
  expect(screen.getByText("You voted for Teammate 4.")).toBeInTheDocument();
  expect(button("Teammate 4")).toHaveAttribute("aria-pressed", "true");
});

test("run-out: the next set to call is named with an action (R.6.2)", () => {
  const { sent } = show(
    update({ phase: "runout", current: 1 }, { actions: [CALL_BASE + 3, CALL_BASE + 6] }),
  );
  fireEvent.click(button("Low spades (2–7)"));
  fireEvent.click(button("Call Low spades (2–7)"));
  expect(sent).toEqual([{ type: "act", index: CALL_BASE + 3 }]);
});

test("a refusal after sending is explained, and the buttons work again", () => {
  const actions = [encode(1, { kind: "ask", target: 3, card: 2 })];
  const at = update({ current: 1 }, { actions });
  const { rerender } = show(at, {
    message: { type: "rejected", reason: "illegal", discarded: false },
    n: 1,
  });
  expect(screen.queryByRole("alert")).toBeNull(); // from before: not shown
  fireEvent.click(button("Opponent 4"));
  fireEvent.click(button("4♣"));
  fireEvent.click(button("Ask Opponent 4 for the 4♣"));
  rerender(at, { message: { type: "rejected", reason: "illegal", discarded: true }, n: 2 });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "A call was declared before your action arrived, so it was not made.",
  );
  expect(button("Opponent 4")).toBeEnabled();
});

test("a send that fails leaves the buttons as they were", () => {
  const actions = [encode(1, { kind: "ask", target: 3, card: 2 })];
  render(<Actions update={update({}, { actions })} rejected={null} send={() => false} />);
  fireEvent.click(button("Opponent 4"));
  fireEvent.click(button("4♣"));
  fireEvent.click(button("Ask Opponent 4 for the 4♣"));
  expect(button("Opponent 4")).toBeEnabled();
});
