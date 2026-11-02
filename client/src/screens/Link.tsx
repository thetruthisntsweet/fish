// A link to one of the site's pages. A plain click moves within the site; a click with a
// modifier key, or a middle click, opens a new tab as any link does.
import type { MouseEvent, ReactNode } from "react";
import { go } from "../navigation.ts";

export function Link({ to, children }: { to: string; children: ReactNode }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    go(to);
  }
  return (
    <a href={to} onClick={follow}>
      {children}
    </a>
  );
}
