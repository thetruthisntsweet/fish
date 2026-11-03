// What the player can do at the table (T3.4), offered exactly as the server allows: ask for a
// card on their turn (R.3.2), press Call naming a set at any time it is live (R.8.3), assign
// the six cards of their call (R.4.3), choose or vote for who takes the turn (R.5.2), and name
// the next set in run-out (R.6.2). Each action is confirmed before it is sent, and once sent
// the buttons wait for the server's next update, so nothing is sent twice.
import { useState } from "react";
import type { Rejected } from "../generated/Rejected.ts";
import type { Update } from "../generated/Update.ts";
import {
  cardLabel,
  setCards,
  setLabel,
  setOf,
  teammates,
  type Card,
  type Seat,
} from "../game/cards.ts";
import type { ClientMessage, Notice } from "../game/connection.ts";
import { rejection, seatName } from "../game/describe.ts";
import { offered, offers } from "../game/offers.ts";
import { CardFace } from "./CardFace.tsx";

interface Props {
  update: Update;
  rejected: Notice<Rejected> | null;
  send: (message: ClientMessage) => boolean;
}

export function Actions({ update, rejected, send }: Props) {
  // The update and rejection current when the player last sent something: until either
  // changes, the buttons wait.
  const [sentAt, setSentAt] = useState<{ update: Update; rejected: number } | null>(null);
  const rejectedN = rejected?.n ?? 0;
  const waiting = sentAt !== null && sentAt.update === update && sentAt.rejected === rejectedN;
  const shownRejection =
    rejected !== null && sentAt !== null && rejected.n > sentAt.rejected ? rejected.message : null;

  function sendIt(message: ClientMessage) {
    if (send(message)) {
      setSentAt({ update, rejected: rejectedN });
    }
  }
  function act(index: number | null) {
    if (index !== null) {
      sendIt({ type: "act", index });
    }
  }

  const can = offers(update);
  const own = update.view.seat;
  const call = update.view.call;
  const seen = update.view.last_event?.number ?? null;

  return (
    <div className="moves">
      {shownRejection !== null && (
        <p className="problem" role="alert">
          {rejection(shownRejection)}
        </p>
      )}
      {can.asks.size > 0 && (
        <Ask
          key={`ask:${String(seen)}`}
          own={own}
          asks={can.asks}
          disabled={waiting}
          onAsk={(target, card) => {
            act(offered(update, { kind: "ask", target, card }));
          }}
        />
      )}
      {can.assigning && call !== null && call.caller === own && (
        <Assign
          key={`assign:${String(call.set_id)}`}
          own={own}
          set={call.set_id}
          hand={update.view.hand}
          disabled={waiting}
          onAssign={(holders) => {
            act(offered(update, { kind: "assign", holders }));
          }}
        />
      )}
      {can.nominations.length > 0 && (
        <Nominate
          own={own}
          seats={can.nominations}
          vote={update.view.phase === "vote"}
          ownVote={update.view.choice?.own_vote ?? null}
          disabled={waiting}
          onNominate={(seat) => {
            act(offered(update, { kind: "nominate", seat }));
          }}
        />
      )}
      {can.calls.length > 0 && (
        <SetChoice
          key={`call:${String(seen)}`}
          title="Name the set to call"
          sets={can.calls}
          confirm={(set) => `Call ${setLabel(set)}`}
          disabled={waiting}
          onChoose={(set) => {
            act(offered(update, { kind: "call", set }));
          }}
        />
      )}
      {can.pressable.length > 0 && (
        <SetChoice
          key={`press:${String(seen)}`}
          title="Call a set"
          hint="Calling names a set and then puts each of its six cards with the teammate who holds it. Anyone may call at any time."
          sets={can.pressable}
          confirm={(set) => `Call ${setLabel(set)}`}
          collapsed
          disabled={waiting}
          onChoose={(set_id) => {
            sendIt({ type: "press", set_id, seen });
          }}
        />
      )}
    </div>
  );
}

function Ask({
  own,
  asks,
  disabled,
  onAsk,
}: {
  own: Seat;
  asks: ReadonlyMap<Seat, readonly Card[]>;
  disabled: boolean;
  onAsk: (target: Seat, card: Card) => void;
}) {
  const [target, setTarget] = useState<Seat | null>(null);
  const [card, setCard] = useState<Card | null>(null);
  const cards = target === null ? [] : (asks.get(target) ?? []);
  const sets = [...new Set(cards.map(setOf))];
  return (
    <section className="move" aria-label="Ask for a card">
      <h2>Ask for a card</h2>
      <p className="quiet">Whom do you ask?</p>
      <div className="choices">
        {[...asks.keys()].map((seat) => (
          <button
            key={seat}
            type="button"
            aria-pressed={seat === target}
            disabled={disabled}
            onClick={() => {
              setTarget(seat);
              setCard(null);
            }}
          >
            {seatName(own, seat)}
          </button>
        ))}
      </div>
      {target !== null && (
        <>
          <p className="quiet">For which card?</p>
          {sets.map((set) => (
            <div key={set} className="choices" role="group" aria-label={setLabel(set)}>
              {cards
                .filter((c) => setOf(c) === set)
                .map((c) => (
                  <button
                    key={c}
                    type="button"
                    className="card-button"
                    aria-pressed={c === card}
                    disabled={disabled}
                    onClick={() => {
                      setCard(c);
                    }}
                  >
                    <CardFace card={c} />
                  </button>
                ))}
            </div>
          ))}
        </>
      )}
      {target !== null && card !== null && (
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={disabled}
            onClick={() => {
              onAsk(target, card);
            }}
          >
            Ask {seatName(own, target)} for the <CardFace card={card} />
          </button>
        </div>
      )}
    </section>
  );
}

function SetChoice({
  title,
  hint,
  sets,
  confirm,
  collapsed = false,
  disabled,
  onChoose,
}: {
  title: string;
  hint?: string;
  sets: readonly number[];
  confirm: (set: number) => string;
  collapsed?: boolean;
  disabled: boolean;
  onChoose: (set: number) => void;
}) {
  const [open, setOpen] = useState(!collapsed);
  const [chosen, setChosen] = useState<number | null>(null);
  if (!open) {
    return (
      <div className="actions">
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            setOpen(true);
          }}
        >
          {title}
        </button>
      </div>
    );
  }
  return (
    <section className="move" aria-label={title}>
      <h2>{title}</h2>
      {hint !== undefined && <p className="quiet">{hint}</p>}
      <div className="choices">
        {sets.map((set) => (
          <button
            key={set}
            type="button"
            aria-pressed={set === chosen}
            disabled={disabled}
            onClick={() => {
              setChosen(set);
            }}
          >
            {setLabel(set)}
          </button>
        ))}
      </div>
      <div className="actions">
        {chosen !== null && (
          <button
            type="button"
            className="primary"
            disabled={disabled}
            onClick={() => {
              onChoose(chosen);
            }}
          >
            {confirm(chosen)}
          </button>
        )}
        {collapsed && (
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setChosen(null);
            }}
          >
            Not now
          </button>
        )}
      </div>
    </section>
  );
}

function Assign({
  own,
  set,
  hand,
  disabled,
  onAssign,
}: {
  own: Seat;
  set: number;
  hand: readonly Card[];
  disabled: boolean;
  onAssign: (holders: Seat[]) => void;
}) {
  const cards = setCards(set);
  const mates = teammates(own);
  // The player's own cards start with them; everyone else's are theirs to place.
  const [holders, setHolders] = useState<(Seat | null)[]>(() =>
    cards.map((card) => (hand.includes(card) ? own : null)),
  );
  const complete = holders.every((holder) => holder !== null);
  return (
    <section className="move" aria-label="Assign your call">
      <h2>Who holds each card of {setLabel(set)}?</h2>
      <div className="assign" role="presentation">
        <div className="assign-row assign-head" aria-hidden="true">
          <span />
          {mates.map((mate) => (
            <span key={mate}>{seatName(own, mate)}</span>
          ))}
        </div>
        {cards.map((card, i) => (
          <div
            key={card}
            className="assign-row"
            role="group"
            aria-label={`Who holds the ${cardLabel(card)}`}
          >
            <CardFace card={card} />
            {mates.map((mate) => (
              <button
                key={mate}
                type="button"
                aria-label={seatName(own, mate)}
                aria-pressed={holders[i] === mate}
                disabled={disabled}
                onClick={() => {
                  setHolders(holders.map((h, j) => (j === i ? mate : h)));
                }}
              >
                {holders[i] === mate ? "●" : ""}
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={disabled || !complete}
          onClick={() => {
            if (holders.every((holder): holder is Seat => holder !== null)) {
              onAssign(holders);
            }
          }}
        >
          Make the call
        </button>
      </div>
    </section>
  );
}

function Nominate({
  own,
  seats,
  vote,
  ownVote,
  disabled,
  onNominate,
}: {
  own: Seat;
  seats: readonly Seat[];
  vote: boolean;
  ownVote: Seat | null;
  disabled: boolean;
  onNominate: (seat: Seat) => void;
}) {
  return (
    <section className="move" aria-label={vote ? "Vote" : "Choose"}>
      <h2>{vote ? "Vote for who takes the turn" : "Who takes the turn?"}</h2>
      {ownVote !== null && <p className="quiet">You voted for {seatName(own, ownVote)}.</p>}
      <div className="choices">
        {seats.map((seat) => (
          <button
            key={seat}
            type="button"
            aria-pressed={seat === ownVote}
            disabled={disabled}
            onClick={() => {
              onNominate(seat);
            }}
          >
            {seatName(own, seat)}
          </button>
        ))}
      </div>
    </section>
  );
}
