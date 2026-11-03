// What the table shows, in words (T3.4), from the seat's own view: seat names, the most recent
// event (the only one shown, R.2.2) and what the game is waiting for. Nothing here decides a
// rule; it only says what the server's view already holds.
import type { Rejected } from "../generated/Rejected.ts";
import type { Update } from "../generated/Update.ts";
import { cardLabel, relation, setCards, setLabel, teamOf, type Seat } from "./cards.ts";

export type View = Update["view"];
export type LastEvent = NonNullable<View["last_event"]>;

/** A seat as players see it: seats are numbered 1 to 6 on screen. */
export function seatNumber(seat: Seat): number {
  return seat + 1;
}

/** "You", "Teammate 2" or "Opponent 5", from `own` seat. */
export function seatName(own: Seat, seat: Seat): string {
  switch (relation(own, seat)) {
    case "you":
      return "You";
    case "teammate":
      return `Teammate ${String(seatNumber(seat))}`;
    case "opponent":
      return `Opponent ${String(seatNumber(seat))}`;
  }
}

/** The same, inside a sentence: "you", "Teammate 2", "Opponent 5". */
function who(own: Seat, seat: Seat): string {
  return seat === own ? "you" : seatName(own, seat);
}

function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "your team" or "the other team", from `own` seat. */
export function teamName(own: Seat, team: number): string {
  return team === teamOf(own) ? "your team" : "the other team";
}

/** The most recent event, in one sentence (R.2.2, R.2.3). */
export function eventSentence(own: Seat, event: LastEvent): string {
  switch (event.type) {
    case "AskEvent": {
      const asker = who(own, event.asker);
      const target = who(own, event.target);
      const card = cardLabel(event.card);
      const had =
        event.target === own
          ? event.success
            ? "you had it"
            : "you did not have it"
          : event.success
            ? "they had it"
            : "they did not have it";
      return `${capital(asker)} asked ${target} for the ${card}: ${had}.`;
    }
    case "CallEvent": {
      const caller = who(own, event.caller);
      const result = event.correct ? "right" : "wrong";
      const late = event.assignment === null ? " (time ran out)" : "";
      return `${capital(caller)} called ${setLabel(event.set_id)}: ${result}${late}, and ${teamName(own, event.scored_by)} scored it.`;
    }
    case "ChoiceEvent": {
      const chosen = who(own, event.seat);
      const verb = event.seat === own ? "take" : "takes";
      return `${capital(teamName(own, event.team))} chose: ${chosen} ${verb} the turn.`;
    }
  }
}

/** Where each card of a call was (R.2.3), for the event above. */
export function callHolders(own: Seat, event: LastEvent): { card: string; holder: string }[] {
  if (event.type !== "CallEvent") {
    return [];
  }
  return setCards(event.set_id).map((card, i) => ({
    card: cardLabel(card),
    holder: seatName(own, event.holders[i] ?? 0),
  }));
}

/** What the game is waiting for, in one sentence. A window says that a call was declared,
 * never by whom or for which set (R.8.3). */
export function phaseSentence(view: View): string {
  const own = view.seat;
  const current = view.current;
  switch (view.phase) {
    case "turn":
      return current === own
        ? "Your turn: ask for a card, or call a set."
        : `${seatName(own, current ?? own)}'s turn.`;
    case "window":
      return "A call has been declared.";
    case "assign": {
      const call = view.call;
      if (call === null) {
        return "A call is being made.";
      }
      return call.caller === own
        ? `Your call: put each card of ${setLabel(call.set_id)} with the teammate who holds it.`
        : `${seatName(own, call.caller)} is calling ${setLabel(call.set_id)}.`;
    }
    case "choose":
    case "vote": {
      const choice = view.choice;
      if (choice === null) {
        return "Choosing who takes the turn.";
      }
      if (choice.team !== teamOf(own)) {
        return "The other team is choosing who takes the turn.";
      }
      if (choice.chooser === null) {
        return "Your team votes on who takes the turn.";
      }
      return choice.chooser === own
        ? "Choose who on your team takes the turn."
        : `${seatName(own, choice.chooser)} is choosing who takes the turn.`;
    }
    case "runout":
      return current === own
        ? "The other team has no cards: name the next set to call."
        : `One team has no cards: ${who(own, current ?? own)} names the next set to call.`;
    case "over":
      if (view.outcome === "unfinished" || view.winner === null) {
        return "The game stopped at 1,000 asks, with no winner.";
      }
      return view.winner === teamOf(own) ? "Your team won!" : "The other team won.";
  }
}

/** Sets scored by each team: [this seat's team, the other team]. */
export function score(view: View): [number, number] {
  const mine = teamOf(view.seat);
  let ours = 0;
  let theirs = 0;
  for (const team of view.scored_by) {
    if (team === mine) {
      ours += 1;
    } else if (team !== null) {
      theirs += 1;
    }
  }
  return [ours, theirs];
}

const REJECTED: Record<Rejected["reason"], string> = {
  illegal: "That is not allowed now. Choose again.",
  stale: "That set changed before your call arrived. Choose again.",
  malformed: "That could not be sent. Choose again.",
};

/** Why the server did not apply what the player sent. */
export function rejection(rejected: Rejected): string {
  return rejected.discarded
    ? "A call was declared before your action arrived, so it was not made."
    : REJECTED[rejected.reason];
}
