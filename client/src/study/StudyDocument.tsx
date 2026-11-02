// One version of the study information, top to bottom (Consent Screen §1). The consent
// screen shows it above its checkboxes; the "Study information" page shows it with the
// confirmations as they were accepted.
import type { ReactNode } from "react";
import { CONFIRMATIONS, type Block, type StudyText } from "./texts.ts";

const EMAIL = /([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})/;

/** ``text`` with each email address a link that opens a new email; the words are unchanged. */
function withEmailLinks(text: string): ReactNode[] {
  // Splitting on a pattern with one capture group puts each address at an odd index.
  return text.split(EMAIL).map((part, i) =>
    i % 2 === 1 ? (
      <a key={i} href={`mailto:${part}`}>
        {part}
      </a>
    ) : (
      part
    ),
  );
}

function Blocks({ blocks }: { blocks: readonly Block[] }) {
  return blocks.map((block, i) =>
    block.kind === "paragraph" ? (
      <p key={i}>{withEmailLinks(block.text)}</p>
    ) : (
      <ul key={i}>
        {block.items.map((item) => (
          <li key={item}>{withEmailLinks(item)}</li>
        ))}
      </ul>
    ),
  );
}

interface Props {
  text: StudyText;
  /** Show the confirmations as a plain list after the text, as on the rereading page. */
  withConfirmations?: boolean;
}

export function StudyDocument({ text, withConfirmations = false }: Props) {
  return (
    <article className="study" aria-labelledby="study-title">
      <h1 id="study-title">{text.title}</h1>
      {text.sections.map((section) => (
        <section key={section.heading}>
          <h2>{section.heading}</h2>
          <Blocks blocks={section.blocks} />
        </section>
      ))}
      {withConfirmations && (
        <section>
          <h2>{text.confirm}</h2>
          <ul>
            {CONFIRMATIONS.map((name) => (
              <li key={name}>{text.confirmations[name]}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
