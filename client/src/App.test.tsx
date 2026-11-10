// The website's first screens (Consent Screen §2), against a stand-in server: the consent
// screen first, nothing sent or stored before Continue, the acceptance carried with the
// sign-in link, a new version accepted again, and the screens around them.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.tsx";
import { fakeServer, type FakeServer } from "./test/server.ts";
import { fakeSockets } from "./test/socket.ts";

const ACCEPTED = {
  version: "v1.0",
  terms_version: "v1.0",
  us_resident_adult: true,
  agrees: true,
  no_outside_communication: true,
};

let server: FakeServer;

beforeEach(() => {
  server = fakeServer();
  fakeSockets(); // signed in, the front page opens the game connection
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const boxes = () => screen.getAllByRole<HTMLInputElement>("checkbox");
const button = (name: string) => screen.getByRole<HTMLButtonElement>("button", { name });

function tickAll() {
  for (const box of boxes()) {
    fireEvent.click(box);
  }
}

async function consentScreen(title = "Fish research study: before you play") {
  render(<App />);
  return screen.findByRole("heading", { level: 1, name: title });
}

test("the consent screen comes first, with every box unticked and Continue disabled", async () => {
  await consentScreen();
  expect(screen.getByRole("heading", { name: "Key points" })).toBeInTheDocument();
  expect(boxes()).toHaveLength(3);
  expect(boxes().every((box) => !box.checked)).toBe(true);
  expect(button("Continue")).toBeDisabled();
  expect(screen.queryByRole("status")).toBeNull(); // no "the text has changed" notice
});

test("Continue is enabled only once all three are ticked", async () => {
  await consentScreen();
  const [adult, agrees, quiet] = boxes();
  if (adult === undefined || agrees === undefined || quiet === undefined) {
    throw new Error("three boxes");
  }
  fireEvent.click(adult);
  fireEvent.click(agrees);
  expect(button("Continue")).toBeDisabled();
  fireEvent.click(quiet);
  expect(button("Continue")).toBeEnabled();
  fireEvent.click(agrees);
  expect(button("Continue")).toBeDisabled();
});

test("nothing is sent or stored before Continue", async () => {
  const stored = vi.spyOn(Storage.prototype, "setItem");
  await consentScreen();
  tickAll();
  expect(server.posts()).toEqual([]);
  expect(stored).not.toHaveBeenCalled();
  expect(document.cookie).toBe("");
  expect(server.sent.map((s) => `${s.method} ${s.path}`).sort()).toEqual([
    "GET /auth/me",
    "GET /study",
  ]);
});

test("No thanks leaves with a thank-you, sending nothing", async () => {
  await consentScreen();
  tickAll();
  fireEvent.click(button("No thanks"));
  expect(await screen.findByRole("heading", { name: "Thank you" })).toBeInTheDocument();
  expect(screen.getByText(/nothing about you has been stored/)).toBeInTheDocument();
  expect(server.posts()).toEqual([]);
  fireEvent.click(button("Read the study information again"));
  await consentScreen();
  expect(boxes().every((box) => !box.checked)).toBe(true); // ticked afresh
});

test("Continue asks for an address and sends the link with the acceptance", async () => {
  await consentScreen();
  tickAll();
  fireEvent.click(button("Continue"));
  expect(await screen.findByRole("heading", { name: "Your email address" })).toBeInTheDocument();
  expect(server.posts()).toEqual([]); // the acceptance travels with the link
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "  someone@example.org " },
  });
  fireEvent.click(button("Send sign-in link"));
  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  expect(screen.getByText("someone@example.org")).toBeInTheDocument();
  expect(server.posts()).toEqual([
    {
      method: "POST",
      path: "/auth/link",
      body: { email: "someone@example.org", consent: ACCEPTED },
    },
  ]);
  fireEvent.click(button("Send again or use another address"));
  expect(screen.getByLabelText("Email address")).toHaveValue("someone@example.org");
});

test("the server's reason is shown when a link cannot be sent", async () => {
  server.next.set("POST /auth/link", {
    status: 429,
    body: { detail: "Too many sign-in emails. Try later." },
  });
  await consentScreen();
  tickAll();
  fireEvent.click(button("Continue"));
  fireEvent.change(await screen.findByLabelText("Email address"), {
    target: { value: "someone@example.org" },
  });
  fireEvent.click(button("Send sign-in link"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Too many sign-in emails. Try later.");
  expect(screen.getByRole("heading", { name: "Your email address" })).toBeInTheDocument();
});

test("the pilot site shows the pilot text and sends its version", async () => {
  server.version = "v1.0-pilot";
  await consentScreen("Fish research study: pilot games");
  expect(screen.queryByRole("heading", { name: "Possible extra games in March 2027" })).toBeNull();
  tickAll();
  fireEvent.click(button("Continue"));
  fireEvent.change(await screen.findByLabelText("Email address"), {
    target: { value: "pilot@example.org" },
  });
  fireEvent.click(button("Send sign-in link"));
  await screen.findByRole("heading", { name: "Check your email" });
  expect(server.posts()[0]?.body).toEqual({
    email: "pilot@example.org",
    consent: { ...ACCEPTED, version: "v1.0-pilot", terms_version: "v1.0-pilot" },
  });
});

test("a signed-in player who accepted the text shown is not asked again", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Play Fish" })).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("a signed-in player on a site taking no tables is told why, with no way to a table", async () => {
  const latest = fakeSockets();
  server.standing = { accepted: "v1.0", withdrawn: false };
  server.tables = {
    reason: "not_open",
    message: "The study opens on Tuesday 8 December 2026. Until then, no games can be played here.",
    link: null,
  };
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Play Fish" })).toBeInTheDocument();
  act(() => {
    latest().hello();
    latest().push({ type: "lobby", waiting: null, code: null, people: 0 });
  });
  expect(screen.getByRole("status")).toHaveTextContent("The study opens on Tuesday 8 December");
  expect(screen.queryByRole("button", { name: "Find a table" })).toBeNull();
});

test("a new version is read and accepted again before the next game", async () => {
  server.version = "v1.0-pilot"; // the text changed since this player accepted
  server.standing = { accepted: "v1.0", withdrawn: false };
  await consentScreen("Fish research study: pilot games");
  expect(screen.getByRole("status")).toHaveTextContent("The study information has changed.");
  tickAll();
  fireEvent.click(button("Continue"));
  expect(await screen.findByRole("heading", { name: "Play Fish" })).toBeInTheDocument();
  expect(server.posts()).toEqual([
    {
      method: "POST",
      path: "/consent",
      body: { ...ACCEPTED, version: "v1.0-pilot", terms_version: "v1.0-pilot" },
    },
  ]);
});

test("terms not yet accepted bring the consent screen back, saying so, and are sent", async () => {
  // Accepted before there were terms (T3.8): the same as new terms alone.
  server.standing = { accepted: "v1.0", termsAccepted: null, withdrawn: false };
  await consentScreen();
  expect(screen.getByRole("status")).toHaveTextContent(
    "The terms of use and privacy policy have changed.",
  );
  tickAll();
  fireEvent.click(button("Continue"));
  expect(await screen.findByRole("heading", { name: "Play Fish" })).toBeInTheDocument();
  expect(server.posts()).toEqual([{ method: "POST", path: "/consent", body: ACCEPTED }]);
});

test("Continue says it agrees to the terms, and links them in a new tab", async () => {
  await consentScreen();
  const line = screen.getByText(/By continuing you agree to the/);
  expect(line).toHaveTextContent(
    "By continuing you agree to the Terms of Use and have read the Privacy Policy.",
  );
  for (const [name, href] of [
    ["Terms of Use", "/terms"],
    ["Privacy Policy", "/privacy"],
  ]) {
    const link = within(line).getByRole("link", { name });
    expect(link).toHaveAttribute("href", href);
    expect(link).toHaveAttribute("target", "_blank"); // the ticks stay where they are
  }
});

test("a player whose session ran out signs in again with the new acceptance", async () => {
  server.standing = { accepted: null, withdrawn: false };
  server.next.set("POST /consent", { status: 401, body: { detail: "Sign in first." } });
  await consentScreen();
  tickAll();
  fireEvent.click(button("Continue"));
  expect(await screen.findByRole("heading", { name: "Your email address" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "back@example.org" },
  });
  fireEvent.click(button("Send sign-in link"));
  await screen.findByRole("heading", { name: "Check your email" });
  expect(server.posts().at(-1)?.body).toEqual({ email: "back@example.org", consent: ACCEPTED });
});

test("a player who has withdrawn is told so, and not asked to accept anything", async () => {
  server.standing = { accepted: "v1.0", withdrawn: true };
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "You have withdrawn from the study" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("a server showing a text this page does not have asks for a reload", async () => {
  server.version = "v9.9";
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("This page is out of date.");
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("an unreachable server says so, and trying again works", async () => {
  server.reachable = false;
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");
  server.reachable = true;
  fireEvent.click(button("Try again"));
  await waitFor(() => {
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });
});
