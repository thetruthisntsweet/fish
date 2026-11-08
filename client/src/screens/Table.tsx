// The table (T3.4), drawn from the seat's update alone: the six seats, with bots labelled as
// bots and nothing about which kind (Research Plan §5), every hand size, the score and the
// scored sets, this player's own hand by set, the most recent event and nothing older
// (R.2.2), what the game is waiting for, and the running timers, the current player's turn
// timer shown at their seat (R.2.6).
import type { Update } from "../generated/Update.ts";
import {
  NUM_SETS,
  opponents,
  relation,
  setLabel,
  setOf,
  teammates,
  type Card,
  type Seat,
} from "../game/cards.ts";
import { callHolders, eventSentence, phaseSentence, score, seatName } from "../game/describe.ts";
import { keyFor } from "../game/keys.ts";
import type { Rejected } from "../generated/Rejected.ts";
import type { ClientMessage, Notice } from "../game/connection.ts";
import { Actions } from "./Actions.tsx";
import { CardFace } from "./CardFace.tsx";
import { Countdown } from "./Countdown.tsx";

type Timer = Update["timers"][number];

const TIMER_NAMES: Record<Timer["name"], string> = {
  turn: "Turn",
  window: "Call window",
  assignment: "Time to assign the call",
  choice: "Time to choose",
};

interface Props {
  update: Update;
  /** How many updates have arrived, shown as `data-updates` (T3.7; GameState.updates). */
  drawn?: number;
  rejected?: Notice<Rejected> | null;
  send?: (message: ClientMessage) => boolean;
}

export function Table({ update, drawn, rejected = null, send = () => false }: Props) {
  const view = update.view;
  const own = view.seat;
  const [ours, theirs] = score(view);
  const turn = update.timers.find((timer) => timer.name === "turn");
  const others = update.timers.filter((timer) => timer.name !== "turn");

  function seat(at: Seat) {
    const bot = update.bots.includes(at);
    const current = view.current === at && (view.phase === "turn" || view.phase === "runout");
    const size = view.hand_sizes[at] ?? 0;
    return (
      <li
        key={at}
        className={`seat ${relation(own, at)}${current ? " current" : ""}`}
        aria-current={current ? "true" : undefined}
      >
        <span className="seat-name">{seatName(own, at)}</span>
        {bot && <span className="badge">bot</span>}
        <span className="quiet">
          {size} {size === 1 ? "card" : "cards"}
        </span>
        {current && turn !== undefined && (
          <Countdown key={keyFor(update, "turn")} msLeft={turn.ms_left} label={TIMER_NAMES.turn} />
        )}
      </li>
    );
  }

  return (
    <div className="table" data-updates={drawn}>
      <p className="score" aria-label="Score">
        Your team <strong>{ours}</strong> · Other team <strong>{theirs}</strong>
      </p>

      <ul className="seats" aria-label="The other team">
        {opponents(own).map(seat)}
      </ul>
      <ul className="seats" aria-label="Your team">
        {teammates(own).map(seat)}
      </ul>

      <section className="now" aria-label="Now">
        {view.last_event !== null && <LatestEvent own={own} event={view.last_event} />}
        <p className="phase" role="status">
          {phaseSentence(view)}
          {others.map((timer) => (
            <Countdown
              key={keyFor(update, timer.name)}
              msLeft={timer.ms_left}
              label={TIMER_NAMES[timer.name]}
            />
          ))}
        </p>
        {view.window?.own_declaration != null && (
          <p className="quiet">You declared {setLabel(view.window.own_declaration)}.</p>
        )}
      </section>

      <Actions update={update} rejected={rejected} send={send} />
      <Hand cards={view.hand} />
      <Scored view={view} />
    </div>
  );
}

function LatestEvent({
  own,
  event,
}: {
  own: Seat;
  event: NonNullable<Update["view"]["last_event"]>;
}) {
  const holders = callHolders(own, event);
  return (
    <div className="event">
      <p>{eventSentence(own, event)}</p>
      {holders.length > 0 && (
        <ul className="holders" aria-label="Where the cards were">
          {holders.map(({ card, holder }) => (
            <li key={card}>
              {card}: {holder}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Hand({ cards }: { cards: readonly Card[] }) {
  const sets = [...new Set(cards.map(setOf))];
  return (
    <section aria-label="Your hand">
      <h2>Your hand</h2>
      {cards.length === 0 ? (
        <p className="quiet">You have no cards.</p>
      ) : (
        <ul className="hand">
          {sets.map((set) => (
            <li key={set}>
              <span className="set-name">{setLabel(set)}</span>
              <span className="cards">
                {cards
                  .filter((card) => setOf(card) === set)
                  .map((card) => (
                    <CardFace key={card} card={card} />
                  ))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Scored({ view }: { view: Update["view"] }) {
  const mine = view.seat < 3 ? 0 : 1;
  const scored = Array.from({ length: NUM_SETS }, (_, set) => set).filter(
    (set) => view.scored_by[set] != null,
  );
  if (scored.length === 0) {
    return null;
  }
  return (
    <section aria-label="Sets scored">
      <h2>Sets scored</h2>
      <ul className="scored">
        {scored.map((set) => (
          <li key={set}>
            {setLabel(set)}: {view.scored_by[set] === mine ? "your team" : "the other team"}
          </li>
        ))}
      </ul>
    </section>
  );
}
