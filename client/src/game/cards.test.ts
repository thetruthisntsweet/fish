// Card, set, seat and team names (T3.4), checked against the frozen deal vectors' names
// (docs/determinism.md §6).
import { describe, expect, test } from "vitest";
import { vector } from "../test/vectors.ts";
import {
  CARD_NAMES,
  NUM_CARDS,
  SET_NAMES,
  cardLabel,
  isRed,
  opponents,
  relation,
  setCards,
  setLabel,
  setOf,
  teamOf,
  teamSeats,
  teammates,
} from "./cards.ts";

const deal = vector("deal_v1.json") as { card_names: string[]; set_names: string[] };

test("cards and sets have the frozen names", () => {
  expect(CARD_NAMES).toEqual(deal.card_names);
  expect(SET_NAMES).toEqual(deal.set_names);
});

describe("a card", () => {
  test("reads as a player would say it", () => {
    expect([0, 37, 29, 48, 52, 53].map(cardLabel)).toEqual([
      "2♣",
      "10♥",
      "A♣",
      "8♣",
      "Red joker",
      "Black joker",
    ]);
  });

  test("is red for diamonds, hearts and the red joker", () => {
    const red = Array.from({ length: NUM_CARDS }, (_, card) => card).filter(isRed);
    expect(red.map((card) => CARD_NAMES[card])).toEqual(
      CARD_NAMES.filter((name) => name === "RJ" || /[DH]$/.test(name)),
    );
  });

  test("belongs to the set its number says", () => {
    for (let card = 0; card < NUM_CARDS; card++) {
      expect(setCards(setOf(card))).toContain(card);
    }
    expect(setCards(8).map((card) => CARD_NAMES[card])).toEqual([
      "8C",
      "8D",
      "8H",
      "8S",
      "RJ",
      "BJ",
    ]);
  });

  test("outside 0–53 is refused", () => {
    for (const bad of [-1, 54, 1.5, Number.NaN]) {
      expect(() => cardLabel(bad)).toThrow(RangeError);
      expect(() => setOf(bad)).toThrow(RangeError);
    }
    expect(() => setCards(9)).toThrow(RangeError);
    expect(() => setLabel(-1)).toThrow(RangeError);
  });
});

test("sets read as a player would say them", () => {
  expect([0, 2, 5, 7, 8].map(setLabel)).toEqual([
    "Low clubs (2–7)",
    "Low hearts (2–7)",
    "High diamonds (9–A)",
    "High spades (9–A)",
    "Eights and jokers",
  ]);
});

test("seats 0–2 play seats 3–5, each seen from a seat", () => {
  expect([0, 1, 2, 3, 4, 5].map(teamOf)).toEqual([0, 0, 0, 1, 1, 1]);
  expect(teamSeats(1)).toEqual([3, 4, 5]);
  expect(teammates(4)).toEqual([3, 4, 5]);
  expect(opponents(4)).toEqual([0, 1, 2]);
  expect([0, 1, 2, 3, 4, 5].map((seat) => relation(1, seat))).toEqual([
    "teammate",
    "you",
    "teammate",
    "opponent",
    "opponent",
    "opponent",
  ]);
  expect(() => teamOf(6)).toThrow(RangeError);
});
