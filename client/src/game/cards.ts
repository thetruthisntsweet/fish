// Cards, sets, seats and teams, as the client shows them (T3.4). The numbering is frozen
// (docs/determinism.md §6): card number = 6 × set + position, and the server names cards by
// number. Nothing here decides a rule; it only names things.

export type Card = number;
export type SetId = number;
export type Seat = number;
export type Team = 0 | 1;

export const NUM_CARDS = 54;
export const NUM_SETS = 9;
export const CARDS_PER_SET = 6;
export const SEATS: readonly Seat[] = [0, 1, 2, 3, 4, 5];

const SUITS = ["C", "D", "H", "S"] as const;
type Suit = (typeof SUITS)[number];
const LOW_RANKS = ["2", "3", "4", "5", "6", "7"];
const HIGH_RANKS = ["9", "10", "J", "Q", "K", "A"];

/** Each card's frozen name (`2C`, `10H`, `RJ`, …), as fish_rules.cards.CARD_NAMES. */
export const CARD_NAMES: readonly string[] = [
  ...SUITS.flatMap((suit) => LOW_RANKS.map((rank) => rank + suit)),
  ...SUITS.flatMap((suit) => HIGH_RANKS.map((rank) => rank + suit)),
  ...SUITS.map((suit) => "8" + suit),
  "RJ",
  "BJ",
];

/** Each set's frozen name (`low-C`, …, `eights`), as fish_rules.cards.SET_NAMES. */
export const SET_NAMES: readonly string[] = [
  ...SUITS.map((suit) => `low-${suit}`),
  ...SUITS.map((suit) => `high-${suit}`),
  "eights",
];

const SYMBOL: Record<Suit, string> = { C: "♣", D: "♦", H: "♥", S: "♠" };
const SUIT_WORD: Record<Suit, string> = {
  C: "clubs",
  D: "diamonds",
  H: "hearts",
  S: "spades",
};

function check(value: number, size: number, what: string): number {
  if (!Number.isInteger(value) || value < 0 || value >= size) {
    throw new RangeError(`not a ${what}: ${String(value)}`);
  }
  return value;
}

function nameOf(card: Card): string {
  return CARD_NAMES[check(card, NUM_CARDS, "card")] ?? "";
}

/** The card as a player reads it: `10♥`, `A♠`, `Red joker`. */
export function cardLabel(card: Card): string {
  const name = nameOf(card);
  if (name === "RJ") {
    return "Red joker";
  }
  if (name === "BJ") {
    return "Black joker";
  }
  return name.slice(0, -1) + SYMBOL[name.slice(-1) as Suit];
}

/** Whether the card is printed in red: diamonds, hearts and the red joker. */
export function isRed(card: Card): boolean {
  const name = nameOf(card);
  return name === "RJ" || name.endsWith("D") || name.endsWith("H");
}

/** The set a card belongs to. */
export function setOf(card: Card): SetId {
  return Math.floor(check(card, NUM_CARDS, "card") / CARDS_PER_SET);
}

/** A set's six cards, in order. */
export function setCards(set: SetId): Card[] {
  const first = check(set, NUM_SETS, "set") * CARDS_PER_SET;
  return Array.from({ length: CARDS_PER_SET }, (_, i) => first + i);
}

/** The set as a player reads it: `Low hearts (2–7)`, `High spades (9–A)`, `Eights and jokers`. */
export function setLabel(set: SetId): string {
  const name = SET_NAMES[check(set, NUM_SETS, "set")] ?? "";
  if (name === "eights") {
    return "Eights and jokers";
  }
  const [height, suit] = name.split("-") as ["low" | "high", Suit];
  return height === "low" ? `Low ${SUIT_WORD[suit]} (2–7)` : `High ${SUIT_WORD[suit]} (9–A)`;
}

/** The team a seat plays for: seats 0–2 are team 0, seats 3–5 team 1 (R.1.1). */
export function teamOf(seat: Seat): Team {
  return check(seat, SEATS.length, "seat") < 3 ? 0 : 1;
}

/** A team's three seats, ascending. */
export function teamSeats(team: Team): Seat[] {
  return SEATS.filter((seat) => teamOf(seat) === team);
}

/** A seat's team, itself included, ascending: the order the action numbers use. */
export function teammates(seat: Seat): Seat[] {
  return teamSeats(teamOf(seat));
}

/** The other team's seats, ascending: the order the action numbers use. */
export function opponents(seat: Seat): Seat[] {
  return teamSeats(teamOf(seat) === 0 ? 1 : 0);
}

/** How `seat` looks from `own`: you, a teammate or an opponent. */
export function relation(own: Seat, seat: Seat): "you" | "teammate" | "opponent" {
  if (seat === own) {
    return "you";
  }
  return teamOf(seat) === teamOf(own) ? "teammate" : "opponent";
}
