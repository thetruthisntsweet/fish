// What every page starts from: the text this site shows and where the visitor stands with
// the study, asked of the server once per visit and again after anything changes it.
import { UNREACHABLE, getStanding, getStudy, type Standing, type Study } from "./api.ts";
import { legalTexts, type LegalTexts } from "./legal/legal.ts";
import { studyText, type StudyText } from "./study/texts.ts";

export const OUT_OF_DATE = "This page is out of date. Reload it to get the latest version.";

export interface Site {
  readonly study: Study;
  /** The text this site shows. */
  readonly text: StudyText;
  /** The terms of use and privacy policy this site shows (T3.8). */
  readonly legal: LegalTexts;
  /** Null: no one is signed in. */
  readonly standing: Standing | null;
}

export type Loading =
  | { readonly kind: "loading" }
  | { readonly kind: "problem"; readonly message: string; readonly reload: boolean }
  | { readonly kind: "ready"; readonly site: Site };

export async function loadSite(): Promise<Loading> {
  try {
    const [study, standing] = await Promise.all([getStudy(), getStanding()]);
    const text = studyText(study.version);
    const legal = legalTexts(study.termsVersion);
    if (text === undefined || legal === undefined) {
      return { kind: "problem", message: OUT_OF_DATE, reload: true }; // a newer server
    }
    return { kind: "ready", site: { study, text, legal, standing } };
  } catch {
    return { kind: "problem", message: UNREACHABLE, reload: false };
  }
}
