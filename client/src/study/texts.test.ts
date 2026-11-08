// The study texts (Consent Screen §1, §4): one per version the server knows, each saying its
// own last day to withdraw, and the pilot differing from the study text in exactly the nine
// parts §4 lists.
import { describe, expect, test } from "vitest";
import { CONFIRMATIONS, TEXTS, studyText, type StudyText } from "./texts.ts";
import versions from "./versions.json";

const study = TEXTS["v1.0"];
const pilot = TEXTS["v1.0-pilot"];
if (study === undefined || pilot === undefined) {
  throw new Error("both texts are needed");
}

/** Every part of a text by where it is, so two texts can be compared part by part. */
function parts(text: StudyText): Map<string, string> {
  const found = new Map([["title", text.title]]);
  for (const section of text.sections) {
    section.blocks.forEach((block, i) => {
      if (block.kind === "paragraph") {
        found.set(`${section.heading} / paragraph ${String(i)}`, block.text);
      } else {
        block.items.forEach((item, j) => {
          found.set(`${section.heading} / list ${String(i)} / item ${String(j)}`, item);
        });
      }
    });
  }
  found.set("confirm", text.confirm);
  for (const name of CONFIRMATIONS) {
    found.set(name, text.confirmations[name]);
  }
  return found;
}

/** "2027-02-14" as the texts write it: "14 February 2027". */
function inWords(day: string): string {
  return new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

describe("every version", () => {
  test("has a text, and only the versions in versions.json do", () => {
    expect(Object.keys(TEXTS).sort()).toEqual(Object.keys(versions).sort());
    for (const [version, text] of Object.entries(TEXTS)) {
      expect(text.version).toBe(version);
      expect(text.withdrawUntil).toBe(versions[version as keyof typeof versions].withdrawUntil);
    }
  });

  test.each(Object.values(TEXTS))("$version says its own last day to withdraw", (text) => {
    const day = inWords(text.withdrawUntil);
    const keyPoints = text.sections[0];
    expect(keyPoints?.heading).toBe("Key points");
    const bullets = keyPoints?.blocks[0];
    expect(bullets?.kind === "list" && bullets.items.at(-1)).toMatch(
      new RegExp(`^You can withdraw (at any time )?until ${day}\\.$`),
    );
    expect(parts(text).get("Withdrawing / paragraph 0")).toMatch(
      new RegExp(`^Until ${day}, you can withdraw through this website`),
    );
  });

  test("is found by version, and nothing else is", () => {
    expect(studyText("v1.0")).toBe(study);
    expect(studyText("v1.0-pilot")).toBe(pilot);
    expect(studyText("v9.9")).toBeUndefined();
    expect(studyText("toString")).toBeUndefined();
  });
});

describe("v1.0", () => {
  test("has every section of Consent Screen §1, in order", () => {
    expect(study.sections.map((section) => section.heading)).toEqual([
      "Key points",
      "Who is running this study",
      "What the study is for",
      "What you will do",
      "Bots",
      "What we record",
      "How your data is kept",
      "Publication",
      "Withdrawing",
      "Possible extra games in March 2027",
      "Risks",
    ]);
  });

  test("ends with the three confirmations", () => {
    expect(study.confirm).toBe("Before you continue, please confirm:");
    expect(CONFIRMATIONS.map((name) => study.confirmations[name])).toEqual([
      "I live in the United States and I am a legal adult where I live: 18 or older (19 or older in Alabama or Nebraska; 21 or older in Mississippi).",
      "I have read this page, and I agree to take part.",
      "While playing, I will not communicate with my teammates about the game outside the game: no texts, calls, voice chat or talking in person.",
    ]);
  });
});

describe("v1.0-pilot", () => {
  test("differs from v1.0 in exactly the nine parts of Consent Screen §4", () => {
    const a = parts(study);
    const b = parts(pilot);
    const changed = [...new Set([...a.keys(), ...b.keys()])].filter((k) => a.get(k) !== b.get(k));
    expect(changed).toEqual([
      "title", // 1
      "Key points / list 0 / item 0", // 2
      "Key points / list 0 / item 3", // 3
      "What the study is for / paragraph 0", // 4, its last sentence
      "How your data is kept / paragraph 0", // 9, its last two sentences removed
      "Publication / paragraph 0", // 5, both paragraphs: one in the pilot
      "Publication / paragraph 1",
      "Withdrawing / paragraph 0", // 6, both paragraphs: one in the pilot
      "Withdrawing / paragraph 1",
      "Possible extra games in March 2027 / paragraph 0", // 7, removed
      "Risks / paragraph 0", // 8, its last sentence
    ]);
    expect(b.has("Publication / paragraph 1")).toBe(false);
    expect(b.has("Withdrawing / paragraph 1")).toBe(false);
    expect(b.has("Possible extra games in March 2027 / paragraph 0")).toBe(false);
  });

  test("keeps how the data is kept, without the laptop copy", () => {
    const study_ = parts(study).get("How your data is kept / paragraph 0") ?? "";
    const pilot_ = parts(pilot).get("How your data is kept / paragraph 0") ?? "";
    expect(study_.startsWith(`${pilot_} As a backup, the researcher also keeps one copy`)).toBe(
      true,
    );
    expect(pilot_).toBe(
      "In a database in the United States that can be reached only from inside our hosting provider's private network. The game server can add records but cannot change or delete them.",
    );
  });

  test.each(["What the study is for / paragraph 0", "Risks / paragraph 0"])(
    "keeps all of %s but the last sentence",
    (where) => {
      const before = parts(study).get(where) ?? "";
      const opening = before.slice(0, before.lastIndexOf(". ") + 1);
      expect(opening.length).toBeGreaterThan(0);
      expect(parts(pilot).get(where)?.startsWith(`${opening} Pilot games are`)).toBe(true);
    },
  );

  test("keeps the three confirmations word for word", () => {
    expect(pilot.confirm).toBe(study.confirm);
    expect(pilot.confirmations).toEqual(study.confirmations);
  });
});
