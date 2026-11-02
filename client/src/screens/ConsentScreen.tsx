// The consent screen (Consent Screen §2): the study information, then its three
// confirmations, which start unticked; Continue stays disabled until all three are ticked.
// Nothing is sent or stored until Continue is pressed; No thanks sends nothing at all.
import { useState, type SyntheticEvent } from "react";
import { acceptance, type Acceptance } from "../api.ts";
import { StudyDocument } from "../study/StudyDocument.tsx";
import { CONFIRMATIONS, type Confirmation, type StudyText } from "../study/texts.ts";

const UNTICKED: Readonly<Record<Confirmation, boolean>> = {
  us_resident_adult: false,
  agrees: false,
  no_outside_communication: false,
};

interface Props {
  text: StudyText;
  /** A signed-in player whose accepted text is no longer the one shown (§2.8). */
  renewing: boolean;
  /** Called with the acceptance; resolves to a message to show, or null if it went through. */
  onContinue: (accepted: Acceptance) => Promise<string | null>;
  onDecline: () => void;
}

export function ConsentScreen({ text, renewing, onContinue, onDecline }: Props) {
  const [ticked, setTicked] = useState(UNTICKED);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const allTicked = CONFIRMATIONS.every((name) => ticked[name]);

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    if (!allTicked || busy) {
      return;
    }
    setBusy(true);
    setProblem(null);
    const message = await onContinue(acceptance(text.version));
    setBusy(false);
    setProblem(message);
  }

  return (
    <>
      {renewing && (
        <p className="notice" role="status">
          The study information has changed. Please read it and confirm again before your next game.
        </p>
      )}
      <StudyDocument text={text} />
      <form
        className="confirmations"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <fieldset>
          <legend>{text.confirm}</legend>
          {CONFIRMATIONS.map((name) => (
            <label key={name} className="check">
              <input
                type="checkbox"
                checked={ticked[name]}
                onChange={(event) => {
                  setTicked({ ...ticked, [name]: event.target.checked });
                }}
              />
              <span>{text.confirmations[name]}</span>
            </label>
          ))}
        </fieldset>
        {problem !== null && (
          <p className="problem" role="alert">
            {problem}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={!allTicked || busy}>
            Continue
          </button>
          <button type="button" onClick={onDecline} disabled={busy}>
            No thanks
          </button>
        </div>
      </form>
    </>
  );
}
