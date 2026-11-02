// "Study information" (Consent Screen §2.6): the full text of the version the participant
// accepted, always, with the confirmations they gave. Anyone else sees the version this site
// shows.
import type { Site } from "../site.ts";
import { OUT_OF_DATE } from "../site.ts";
import { StudyDocument } from "../study/StudyDocument.tsx";
import { studyText } from "../study/texts.ts";
import { Link } from "./Link.tsx";

export function InformationPage({ site }: { site: Site }) {
  const accepted = site.standing?.accepted ?? null;
  const text = accepted === null ? site.text : studyText(accepted);
  if (text === undefined) {
    return (
      <section className="panel">
        <h1>Study information</h1>
        <p role="alert">{OUT_OF_DATE}</p>
      </section>
    );
  }
  return (
    <>
      <p className="quiet version">
        {accepted === null
          ? `Version ${text.version}, the version this site shows.`
          : `Version ${text.version}, the version you accepted.`}
        {accepted !== null && accepted !== site.study.version
          ? ` This site now shows version ${site.study.version}.`
          : ""}
      </p>
      <StudyDocument text={text} withConfirmations />
      <p>
        <Link to="/">Back to Fish</Link>
      </p>
    </>
  );
}
