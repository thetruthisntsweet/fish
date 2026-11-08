// Email addresses in the study texts and the terms, as links that open a new email.
import type { ReactNode } from "react";

const EMAIL = /([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})/;

/** ``text`` with each email address a link that opens a new email; the words are unchanged. */
export function withEmailLinks(text: string): ReactNode[] {
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
