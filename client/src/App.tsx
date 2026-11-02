// The website (T3.3). The consent screen comes first for anyone not signed in (Consent
// Screen §2.1); a signed-in player whose accepted text is out of date sees it again (§2.8).
// The client holds no rules logic of its own (Plan §3): the game screens arrive in T3.4.
import { useEffect, useState } from "react";
import {
  UNREACHABLE,
  acceptConsent,
  getStanding,
  getStudy,
  requestLink,
  type Acceptance,
  type Standing,
} from "./api.ts";
import { ConsentScreen } from "./screens/ConsentScreen.tsx";
import { EmailScreen } from "./screens/EmailScreen.tsx";
import { Declined, LinkSent, Problem, SignedIn, Withdrawn } from "./screens/Messages.tsx";
import { studyText, type StudyText } from "./study/texts.ts";

const OUT_OF_DATE = "This page is out of date. Reload it to get the latest version.";

type View =
  | { readonly kind: "loading" }
  | { readonly kind: "problem"; readonly message: string; readonly reload: boolean }
  | { readonly kind: "consent"; readonly text: StudyText; readonly renewing: boolean }
  | { readonly kind: "declined"; readonly text: StudyText; readonly renewing: boolean }
  | { readonly kind: "email"; readonly acceptance: Acceptance; readonly email: string }
  | { readonly kind: "sent"; readonly acceptance: Acceptance; readonly email: string }
  | { readonly kind: "signed-in" }
  | { readonly kind: "withdrawn" };

/** Where someone starts, from where they stand with the study (null: not signed in). */
function start(text: StudyText, standing: Standing | null): View {
  if (standing === null) {
    return { kind: "consent", text, renewing: false };
  }
  if (standing.withdrawn) {
    return { kind: "withdrawn" };
  }
  return standing.mayPlay ? { kind: "signed-in" } : { kind: "consent", text, renewing: true };
}

/** Ask the server which text it shows and who is signed in, and pick the screen. */
async function arrive(): Promise<View> {
  try {
    const [study, standing] = await Promise.all([getStudy(), getStanding()]);
    const text = studyText(study.version);
    if (text === undefined) {
      return { kind: "problem", message: OUT_OF_DATE, reload: true }; // a newer server
    }
    return start(text, standing);
  } catch {
    return { kind: "problem", message: UNREACHABLE, reload: false };
  }
}

export default function App() {
  const [view, setView] = useState<View>({ kind: "loading" });

  useEffect(() => {
    let showing = true;
    void arrive().then((next) => {
      if (showing) {
        setView(next);
      }
    });
    return () => {
      showing = false;
    };
  }, []);

  /** Continue on the consent screen: a new person goes on to the email field, carrying the
   * acceptance; a signed-in player's acceptance is recorded now. */
  async function continueWith(renewing: boolean, accepted: Acceptance): Promise<string | null> {
    if (!renewing) {
      setView({ kind: "email", acceptance: accepted, email: "" });
      return null;
    }
    const outcome = await acceptConsent(accepted);
    if (outcome.ok) {
      setView(await arrive());
      return null;
    }
    switch (outcome.status) {
      case 401: // the session ran out: sign in again, with this acceptance
        setView({ kind: "email", acceptance: accepted, email: "" });
        return null;
      case 409:
        setView({ kind: "withdrawn" });
        return null;
      default:
        return outcome.detail;
    }
  }

  async function send(accepted: Acceptance, email: string): Promise<string | null> {
    const outcome = await requestLink(email, accepted);
    if (!outcome.ok) {
      return outcome.detail;
    }
    setView({ kind: "sent", acceptance: accepted, email });
    return null;
  }

  function screen() {
    switch (view.kind) {
      case "loading":
        return <p className="quiet">Loading…</p>;
      case "problem":
        return (
          <Problem
            message={view.message}
            onRetry={() => {
              if (view.reload) {
                window.location.reload();
              } else {
                setView({ kind: "loading" });
                void arrive().then(setView);
              }
            }}
          />
        );
      case "consent":
        return (
          <ConsentScreen
            text={view.text}
            renewing={view.renewing}
            onContinue={(accepted) => continueWith(view.renewing, accepted)}
            onDecline={() => {
              setView({ kind: "declined", text: view.text, renewing: view.renewing });
            }}
          />
        );
      case "declined":
        return (
          <Declined
            onReread={() => {
              setView({ kind: "consent", text: view.text, renewing: view.renewing });
            }}
          />
        );
      case "email":
        return (
          <EmailScreen initial={view.email} onSend={(email) => send(view.acceptance, email)} />
        );
      case "sent":
        return (
          <LinkSent
            email={view.email}
            onAgain={() => {
              setView({ kind: "email", acceptance: view.acceptance, email: view.email });
            }}
          />
        );
      case "signed-in":
        return <SignedIn />;
      case "withdrawn":
        return <Withdrawn />;
    }
  }

  return (
    <div className="site">
      <main>{screen()}</main>
    </div>
  );
}
