import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { StudyDocument } from "./StudyDocument.tsx";
import { CONFIRMATIONS, TEXTS } from "./texts.ts";

const study = TEXTS["v1.0"];
if (study === undefined) {
  throw new Error("v1.0 is needed");
}

test("shows the title, then every section under its heading, in order", () => {
  render(<StudyDocument text={study} />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(study.title);
  const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
  expect(headings).toEqual(study.sections.map((s) => s.heading));
  expect(headings[0]).toBe("Key points");
});

test("shows every word of the text, unchanged", () => {
  render(<StudyDocument text={study} />);
  const shown = screen.getByRole("article").textContent;
  for (const section of study.sections) {
    for (const block of section.blocks) {
      for (const words of block.kind === "paragraph" ? [block.text] : block.items) {
        expect(shown).toContain(words);
      }
    }
  }
});

test("makes each email address a link that opens a new email", () => {
  render(<StudyDocument text={study} />);
  const links = screen.getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]);
  expect(links).toEqual([
    ["821sanjeevkumar@gmail.com", "mailto:821sanjeevkumar@gmail.com"],
    ["hkeldeib@fcps.edu", "mailto:hkeldeib@fcps.edu"],
    ["821sanjeevkumar@gmail.com", "mailto:821sanjeevkumar@gmail.com"],
  ]);
});

test("shows the confirmations only when asked, as a plain list", () => {
  const { unmount } = render(<StudyDocument text={study} />);
  expect(screen.queryByText(study.confirm)).toBeNull();
  unmount();
  render(<StudyDocument text={study} withConfirmations />);
  const confirm = screen.getByRole("heading", { name: study.confirm });
  const section = confirm.closest("section");
  if (section === null) {
    throw new Error("the confirmations are a section");
  }
  const items = within(section)
    .getAllByRole("listitem")
    .map((li) => li.textContent);
  expect(items).toEqual(CONFIRMATIONS.map((name) => study.confirmations[name]));
  expect(screen.queryByRole("checkbox")).toBeNull();
});
