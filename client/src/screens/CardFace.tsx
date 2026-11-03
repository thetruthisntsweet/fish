// A card as a player reads it: `10♥`, red for diamonds, hearts and the red joker.
import { cardLabel, isRed, type Card } from "../game/cards.ts";

export function CardFace({ card }: { card: Card }) {
  return <span className={isRed(card) ? "card red" : "card"}>{cardLabel(card)}</span>;
}
