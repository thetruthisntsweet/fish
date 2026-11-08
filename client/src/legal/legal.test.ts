// The terms of use and privacy policy (Terms and Privacy §1-3; T3.8): one pair per version the
// server knows, and the pilot pair differing from the study's in exactly the parts §3 lists.
import { describe, expect, test } from "vitest";
import { LEGAL, legalTexts, type LegalDocument } from "./legal.ts";
import versions from "./versions.json";

const study = legalTexts("v1.0");
const pilot = legalTexts("v1.0-pilot");
if (study === undefined || pilot === undefined) {
  throw new Error("both versions are needed");
}

/** Every part of a document by where it is, so two can be compared part by part. */
function parts(document: LegalDocument): Map<string, string> {
  const found = new Map([
    ["title", document.title],
    ["effective", document.effective],
  ]);
  const sections = [{ heading: "(intro)", blocks: document.intro }, ...document.sections];
  for (const section of sections) {
    section.blocks.forEach((block, i) => {
      const at = `${section.heading} / ${String(i)}`;
      if (block.kind === "paragraph") {
        found.set(at, block.text);
      } else if (block.kind === "list") {
        block.items.forEach((item, j) => found.set(`${at} / item ${String(j + 1)}`, item));
      } else {
        found.set(`${at} / header`, block.header.join(" | "));
        block.rows.forEach((row, j) => found.set(`${at} / row ${String(j + 1)}`, row.join(" | ")));
      }
    });
  }
  return found;
}

function changed(a: LegalDocument, b: LegalDocument): string[] {
  const x = parts(a);
  const y = parts(b);
  return [...new Set([...x.keys(), ...y.keys()])].filter((k) => x.get(k) !== y.get(k));
}

describe("every version", () => {
  test("has both documents, and only the versions in versions.json do", () => {
    expect(Object.keys(LEGAL)).toEqual(versions); // fish_server.study.TERMS
    for (const [version, texts] of Object.entries(LEGAL)) {
      expect(texts.version).toBe(version);
    }
  });

  test("is found by version, and nothing else is", () => {
    expect(legalTexts("v9.9")).toBeUndefined();
    expect(legalTexts("toString")).toBeUndefined();
  });
});

describe("v1.0", () => {
  test("the terms have every section of §1, in order", () => {
    expect(study.terms.title).toBe("Fish research study: terms of use");
    expect(study.terms.effective).toBe("Version 1.0, effective 30 November 2026.");
    expect(study.terms.sections.map((s) => s.heading)).toEqual([
      "Who runs this website",
      "Who can use it",
      "Playing fairly",
      "Your games",
      "Stopping, withdrawing, and losing access",
      "The website is provided as it is",
      "Changes to these terms",
      "Law",
      "Contact",
    ]);
  });

  test("the privacy policy has every section of §2, in order", () => {
    expect(study.privacy.title).toBe("Fish research study: privacy policy");
    expect(study.privacy.sections.map((s) => s.heading)).toEqual([
      "Who is responsible",
      "What we collect",
      "IP addresses",
      "Cookies",
      "Emails",
      "Who else handles your data",
      "How long it is kept",
      "How it is protected",
      "What you can do",
      "Age",
      "Changes to this policy",
      "Contact",
    ]);
    const collected = parts(study.privacy);
    expect(collected.get("What we collect / 0 / header")).toBe("What | When | Why");
    expect(collected.get("What we collect / 0 / row 8")).toBe(
      "Your withdrawal, if you withdraw | When you withdraw | To remove your games",
    );
  });
});

describe("v1.0-pilot", () => {
  test("the terms differ in exactly their title and Your games (§3)", () => {
    expect(changed(study.terms, pilot.terms)).toEqual(["title", "Your games / 0"]);
    expect(pilot.terms.title).toBe("Fish research study: pilot terms of use");
  });

  test("the privacy policy differs in exactly the parts §3 lists", () => {
    expect(changed(study.privacy, pilot.privacy)).toEqual([
      "title",
      "Who else handles your data / 0 / item 3", // removed
      "How long it is kept / 0 / item 3", // changed
      "How long it is kept / 0 / item 5", // removed: the laptop copy; the logs move up
      "How long it is kept / 0 / item 6",
      "How long it is kept / 0 / item 7", // removed: the published dataset
      "What you can do / 0 / item 2", // changed
    ]);
    const kept = parts(pilot.privacy);
    expect(kept.get("How long it is kept / 0 / item 5")).toBe(
      parts(study.privacy).get("How long it is kept / 0 / item 6"), // the logs, word for word
    );
    expect(kept.has("How long it is kept / 0 / item 6")).toBe(false);
    expect(kept.has("Who else handles your data / 0 / item 3")).toBe(false);
  });
});
