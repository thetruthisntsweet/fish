// The account page (Consent Screen §2.6, §2.7): the version accepted, with a link to reread
// it; "Withdraw from the study", which asks for confirmation and is open until the site's
// last day to withdraw; and signing out.
import { useState } from "react";
import { longDate, signOut, withdraw } from "../api.ts";
import { go } from "../navigation.ts";
import type { Site } from "../site.ts";
import { Link } from "./Link.tsx";

interface Props {
  site: Site;
  /** Something changed on the server (withdrawn, signed out): ask it again. */
  onChange: () => void;
}

export function AccountPage({ site, onChange }: Props) {
  const standing = site.standing;
  if (standing === null) {
    return (
      <section className="panel">
        <h1>Your account</h1>
        <p>You are not signed in.</p>
        <p>
          <Link to="/">Sign in</Link>
        </p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h1>Your account</h1>

      <h2>Study information</h2>
      {standing.accepted === null ? (
        <p>You have not accepted the study information yet.</p>
      ) : (
        <p>
          You accepted version {standing.accepted}. <Link to="/information">Read it again</Link>
        </p>
      )}

      <h2>Withdrawing</h2>
      {standing.withdrawn ? (
        <p>You have withdrawn from the study. You cannot play again.</p>
      ) : site.study.withdrawalOpen ? (
        <Withdraw until={site.study.withdrawUntil} onChange={onChange} />
      ) : (
        <p>
          Withdrawing through the website closed at the end of {longDate(site.study.withdrawUntil)}.
        </p>
      )}

      <h2>Signing out</h2>
      <SignOut onChange={onChange} />
    </section>
  );
}

function Withdraw({ until, onChange }: { until: string; onChange: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setProblem(null);
    const outcome = await withdraw();
    setBusy(false);
    if (outcome.ok) {
      onChange();
    } else {
      setProblem(outcome.detail);
    }
  }

  const consequence =
    "If you withdraw, every game you played is left out of the study, including the other players' moves in those games, and you cannot play again.";

  if (!confirming) {
    return (
      <>
        <p>You can withdraw until {longDate(until)}.</p>
        <div className="actions">
          <button
            type="button"
            onClick={() => {
              setConfirming(true);
            }}
          >
            Withdraw from the study
          </button>
        </div>
      </>
    );
  }
  return (
    <div className="confirm" role="group" aria-labelledby="withdraw-question">
      <p id="withdraw-question">
        <strong>Withdraw from the study?</strong>
      </p>
      <p>{consequence} This cannot be undone.</p>
      {problem !== null && (
        <p className="problem" role="alert">
          {problem}
        </p>
      )}
      <div className="actions">
        <button type="button" className="danger" disabled={busy} onClick={() => void confirm()}>
          Yes, withdraw
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setConfirming(false);
            setProblem(null);
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SignOut({ onChange }: { onChange: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);

  async function leave() {
    const outcome = await signOut();
    if (outcome.ok) {
      go("/");
      onChange();
    } else {
      setProblem(outcome.detail);
    }
  }

  return (
    <>
      {problem !== null && (
        <p className="problem" role="alert">
          {problem}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={() => void leave()}>
          Sign out
        </button>
      </div>
    </>
  );
}
