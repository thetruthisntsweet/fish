// The table (T3.4): every seat with its hand size, bots labelled as bots and nothing more, the
// player's hand by set, only the most recent event (R.2.2), a window that hides who declared
// (R.8.3), and the timers, the turn timer at the current player's seat (R.2.6).
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { update } from "../test/updates.ts";
import { Table } from "./Table.tsx";

afterEach(() => {
  vi.useRealTimers();
});

test("six seats, the other team's and the player's, each with a hand size", () => {
  render(<Table update={update({ hand_sizes: [9, 9, 9, 8, 1, 10] })} />);
  const theirs = within(screen.getByRole("list", { name: "The other team" }));
  const ours = within(screen.getByRole("list", { name: "Your team" }));
  expect(theirs.getAllByRole("listitem").map((seat) => seat.textContent)).toEqual([
    "Opponent 48 cards",
    "Opponent 51 card",
    "Opponent 610 cards",
  ]);
  expect(ours.getAllByRole("listitem").map((seat) => seat.textContent)).toEqual([
    "Teammate 19 cards",
    "You9 cards",
    "Teammate 39 cards",
  ]);
});

test("a bot's seat says bot, and nothing about which kind", () => {
  render(<Table update={update({}, { bots: [2, 5] })} />);
  const badges = screen.getAllByText("bot");
  expect(
    badges.map((badge) => badge.closest("li")?.querySelector(".seat-name")?.textContent),
  ).toEqual(["Opponent 6", "Teammate 3"]);
  expect(document.body.textContent).not.toMatch(/B0|B1|B2|B3|random|stand-in/);
});

test("the player's hand, set by set, red cards marked", () => {
  render(<Table update={update()} />);
  const region = screen.getByRole("region", { name: "Your hand" });
  const hand = within(region);
  expect(hand.getByRole("heading", { name: "Your hand" })).toBeInTheDocument();
  const rows = region.querySelectorAll("li");
  expect([...rows].map((row) => row.textContent)).toEqual([
    "Low clubs (2–7)2♣3♣",
    "Low diamonds (2–7)3♦",
    "Low hearts (2–7)2♥",
    "High clubs (9–A)10♣",
    "High hearts (9–A)10♥",
    "Eights and jokers8♣Red jokerBlack joker",
  ]);
  expect(hand.getByText("10♥")).toHaveClass("red");
  expect(hand.getByText("Black joker")).not.toHaveClass("red");
  expect(hand.getByText("Red joker")).toHaveClass("red");
});

test("only the most recent event is shown, never an earlier one (R.2.2)", () => {
  const first = update({
    last_event: { type: "AskEvent", number: 0, asker: 4, target: 1, card: 0, success: true },
  });
  const { rerender } = render(<Table update={first} />);
  expect(screen.getByText("Opponent 5 asked you for the 2♣: you had it.")).toBeInTheDocument();
  const second = update({
    last_event: { type: "AskEvent", number: 1, asker: 4, target: 0, card: 9, success: false },
  });
  rerender(<Table update={second} />);
  expect(screen.queryByText(/asked you for the 2♣/)).toBeNull();
  expect(
    screen.getByText("Opponent 5 asked Teammate 1 for the 5♦: they did not have it."),
  ).toBeInTheDocument();
});

test("a call's result shows where all six cards were (R.2.3)", () => {
  render(
    <Table
      update={update({
        last_event: {
          type: "CallEvent",
          number: 4,
          caller: 1,
          set_id: 0,
          source: "turn",
          assignment: [1, 1, 0, 0, 2, 2],
          holders: [1, 1, 0, 0, 2, 2],
          correct: true,
          scored_by: 0,
        },
        scored_by: [0, null, null, null, null, null, null, null, null],
      })}
    />,
  );
  expect(
    screen.getByText("You called Low clubs (2–7): right, and your team scored it."),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("list", { name: "Where the cards were" })).getAllByRole("listitem"),
  ).toHaveLength(6);
  expect(screen.getByLabelText("Score")).toHaveTextContent("Your team 1 · Other team 0");
  expect(screen.getByRole("region", { name: "Sets scored" })).toHaveTextContent(
    "Low clubs (2–7): your team",
  );
});

test("a window says a call was declared, and shows only the player's own declaration", () => {
  render(
    <Table
      update={update(
        { phase: "window", window: { own_declaration: 2, responded: true } },
        { timers: [{ name: "window", ms_left: 800 }] },
      )}
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("A call has been declared.");
  expect(screen.getByText("You declared Low hearts (2–7).")).toBeInTheDocument();
  expect(screen.getByRole("timer", { name: "Call window" })).toHaveTextContent("1s");
});

test("the turn timer runs at the current player's seat, from the server's figure", () => {
  vi.useFakeTimers();
  const first = update({ current: 4 }, { timers: [{ name: "turn", ms_left: 60_000 }] });
  const { rerender } = render(<Table update={first} />);
  const current = screen.getByText("Opponent 5").closest("li");
  expect(current).toHaveAttribute("aria-current", "true");
  expect(within(current as HTMLElement).getByRole("timer", { name: "Turn" })).toHaveTextContent(
    "60s",
  );
  act(() => {
    vi.advanceTimersByTime(50_250);
  });
  const timer = screen.getByRole("timer", { name: "Turn" });
  expect(timer).toHaveTextContent("10s");
  expect(timer).toHaveClass("low");
  rerender(
    <Table update={update({ current: 1 }, { timers: [{ name: "turn", ms_left: 60_000 }] })} />,
  );
  expect(screen.getByRole("timer", { name: "Turn" })).toHaveTextContent("60s"); // a new turn
  expect(screen.getByText("You").closest("li")).toHaveAttribute("aria-current", "true");
  act(() => {
    vi.advanceTimersByTime(120_000);
  });
  expect(screen.getByRole("timer", { name: "Turn" })).toHaveTextContent("0s");
});

test("an empty hand says so", () => {
  render(<Table update={update({ hand: [], hand_sizes: [9, 0, 9, 9, 9, 9] })} />);
  expect(screen.getByText("You have no cards.")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Sets scored" })).toBeNull();
});
