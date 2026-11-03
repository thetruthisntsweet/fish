// The site's front page (Consent Screen §2.1-§2.5, §2.8). The consent screen comes first for
// anyone not signed in; a signed-in player whose accepted text is out of date sees it again.
import { useState } from "react";
import { acceptConsent, requestLink, type Acceptance, type Standing } from "../api.ts";
import type { Site } from "../site.ts";
import type { StudyText } from "../study/texts.ts";
import { ConsentScreen } from "./ConsentScreen.tsx";
import { EmailScreen } from "./EmailScreen.tsx";
import { Declined, LinkSent, Withdrawn } from "./Messages.tsx";
import { Play } from "./Play.tsx";

type View =
  | { readonly kind: "consent"; readonly renewing: boolean }
  | { readonly kind: "declined"; readonly renewing: boolean }
  | { readonly kind: "email"; readonly acceptance: Acceptance; readonly email: string }
  | { readonly kind: "sent"; readonly acceptance: Acceptance; readonly email: string }
  | { readonly kind: "signed-in" }
  | { readonly kind: "withdrawn" };

/** Where someone starts, from where they stand with the study (null: not signed in). */
function start(standing: Standing | null): View {
  if (standing === null) {
    return { kind: "consent", renewing: false };
  }
  if (standing.withdrawn) {
    return { kind: "withdrawn" };
  }
  return standing.mayPlay ? { kind: "signed-in" } : { kind: "consent", renewing: true };
}

interface Props {
  site: Site;
  /** Something changed on the server (an acceptance recorded): ask it again. */
  onChange: () => void;
}

export function Home({ site, onChange }: Props) {
  const [view, setView] = useState<View>(() => start(site.standing));
  const text: StudyText = site.text;

  /** Continue: a new person goes on to the email field, carrying the acceptance; a signed-in
   * player's acceptance is recorded now. */
  async function continueWith(renewing: boolean, accepted: Acceptance): Promise<string | null> {
    if (!renewing) {
      setView({ kind: "email", acceptance: accepted, email: "" });
      return null;
    }
    const outcome = await acceptConsent(accepted);
    if (outcome.ok || outcome.status === 409) {
      onChange(); // accepted, or withdrawn meanwhile: either way the server now says which
      return null;
    }
    if (outcome.status === 401) {
      setView({ kind: "email", acceptance: accepted, email: "" }); // the session ran out
      return null;
    }
    return outcome.detail;
  }

  async function send(accepted: Acceptance, email: string): Promise<string | null> {
    const outcome = await requestLink(email, accepted);
    if (!outcome.ok) {
      return outcome.detail;
    }
    setView({ kind: "sent", acceptance: accepted, email });
    return null;
  }

  switch (view.kind) {
    case "consent":
      return (
        <ConsentScreen
          text={text}
          renewing={view.renewing}
          onContinue={(accepted) => continueWith(view.renewing, accepted)}
          onDecline={() => {
            setView({ kind: "declined", renewing: view.renewing });
          }}
        />
      );
    case "declined":
      return (
        <Declined
          onReread={() => {
            setView({ kind: "consent", renewing: view.renewing });
          }}
        />
      );
    case "email":
      return <EmailScreen initial={view.email} onSend={(email) => send(view.acceptance, email)} />;
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
      return <Play onSignedOut={onChange} />;
    case "withdrawn":
      return <Withdrawn />;
  }
}
