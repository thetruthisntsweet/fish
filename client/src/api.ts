// The server's study and sign-in endpoints, as the client uses them (fish_server.auth;
// docs/server.md §2). Same origin: the server serves the client (fish_server.pages), so the
// session cookie goes with every request on its own.
import type { Confirmation } from "./study/texts.ts";

/** GET /study: the text this site shows, and until when its participants can withdraw. */
export interface Study {
  readonly version: string;
  readonly withdrawUntil: string;
  readonly withdrawalOpen: boolean;
}

/** Where a signed-in player stands with the study (GET /auth/me). */
export interface Standing {
  readonly current: string;
  readonly accepted: string | null;
  readonly withdrawn: boolean;
  readonly mayPlay: boolean;
}

/** What Continue sends: the version shown, every confirmation ticked (fish_server.consent). */
export type Acceptance = { readonly version: string } & Readonly<Record<Confirmation, true>>;

export type Outcome =
  { readonly ok: true } | { readonly ok: false; readonly status: number; readonly detail: string };

export const UNREACHABLE = "The server could not be reached. Check your connection and try again.";

/** How long a sign-in link works (fish_server.signin.LINK_LIFETIME). */
export const LINK_MINUTES = 15;

/** The server answered something the client does not understand. */
export class UnexpectedAnswer extends Error {}

export function acceptance(version: string): Acceptance {
  return { version, us_resident_adult: true, agrees: true, no_outside_communication: true };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function getJson(path: string): Promise<{ status: number; body: unknown }> {
  const response = await fetch(path, { headers: { accept: "application/json" } });
  return { status: response.status, body: (await response.json()) as unknown };
}

/** The study this site runs. Throws if the server cannot be reached or answers oddly. */
export async function getStudy(): Promise<Study> {
  const { status, body } = await getJson("/study");
  if (
    status !== 200 ||
    !isRecord(body) ||
    typeof body.version !== "string" ||
    typeof body.withdraw_until !== "string" ||
    typeof body.withdrawal_open !== "boolean"
  ) {
    throw new UnexpectedAnswer(`GET /study answered ${String(status)}`);
  }
  return {
    version: body.version,
    withdrawUntil: body.withdraw_until,
    withdrawalOpen: body.withdrawal_open,
  };
}

/** Where the signed-in player stands, or null if no one is signed in. */
export async function getStanding(): Promise<Standing | null> {
  const { status, body } = await getJson("/auth/me");
  if (status === 401) {
    return null;
  }
  const study = isRecord(body) ? body.study : undefined;
  if (
    status !== 200 ||
    !isRecord(study) ||
    typeof study.current !== "string" ||
    !(typeof study.accepted === "string" || study.accepted === null) ||
    typeof study.withdrawn !== "boolean" ||
    typeof study.may_play !== "boolean"
  ) {
    throw new UnexpectedAnswer(`GET /auth/me answered ${String(status)}`);
  }
  return {
    current: study.current,
    accepted: study.accepted,
    withdrawn: study.withdrawn,
    mayPlay: study.may_play,
  };
}

async function post(path: string, body: unknown): Promise<Outcome> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, detail: UNREACHABLE };
  }
  if (response.ok) {
    return { ok: true };
  }
  let detail = `Something went wrong (${String(response.status)}). Try again.`;
  try {
    const answer = (await response.json()) as unknown;
    if (isRecord(answer) && typeof answer.detail === "string") {
      detail = answer.detail; // the server's own words, written for people
    }
  } catch {
    // not JSON: keep the general message
  }
  return { ok: false, status: response.status, detail };
}

/** Email a sign-in link, carrying the acceptance just made on the consent screen. */
export function requestLink(email: string, consent: Acceptance): Promise<Outcome> {
  return post("/auth/link", { email, consent });
}

/** A signed-in player accepts the text shown now. */
export function acceptConsent(consent: Acceptance): Promise<Outcome> {
  return post("/consent", consent);
}
