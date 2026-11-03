// "Study information" and the account page (Consent Screen §2.6, §2.7), and the footer that
// links them, against a stand-in server.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.tsx";
import { PAGES } from "./navigation.ts";
import { fakeServer, type FakeServer } from "./test/server.ts";
import { fakeSockets } from "./test/socket.ts";

let server: FakeServer;

beforeEach(() => {
  server = fakeServer();
  fakeSockets(); // signed in, the front page opens the game connection
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function visit(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}

const button = (name: string) => screen.getByRole("button", { name });
const footer = () => within(screen.getByRole("contentinfo"));

test("the client has a page for exactly the paths the server serves it on", () => {
  expect(PAGES).toEqual(["/", "/account", "/information"]); // fish_server.pages.PAGES
});

test("every page's footer links to the study information; the account once signed in", async () => {
  visit("/");
  await screen.findAllByRole("checkbox");
  expect(footer().getByRole("link", { name: "Study information" })).toHaveAttribute(
    "href",
    "/information",
  );
  expect(footer().queryByRole("link", { name: "Your account" })).toBeNull();
});

test("the footer moves between pages without reloading", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/");
  await screen.findByRole("heading", { name: "Play Fish" });
  fireEvent.click(footer().getByRole("link", { name: "Study information" }));
  expect(window.location.pathname).toBe("/information");
  expect(
    screen.getByRole("heading", { level: 1, name: "Fish research study: before you play" }),
  ).toBeInTheDocument();
  fireEvent.click(footer().getByRole("link", { name: "Your account" }));
  expect(screen.getByRole("heading", { level: 1, name: "Your account" })).toBeInTheDocument();
  expect(server.sent.filter((s) => s.path === "/study")).toHaveLength(1); // asked once
});

test("the study information shows the site's text, with its confirmations, to anyone", async () => {
  visit("/information");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Fish research study: before you play" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Version v1.0, the version this site shows.")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Before you continue, please confirm:" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).toBeNull();
});

test("a participant always rereads the version they accepted", async () => {
  server.version = "v1.0-pilot"; // the site moved on since they accepted
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/information");
  expect(
    await screen.findByRole("heading", { level: 1, name: "Fish research study: before you play" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Version v1.0, the version you accepted. This site now shows version v1.0-pilot.",
    ),
  ).toBeInTheDocument();
});

test("the account page needs someone signed in", async () => {
  visit("/account");
  expect(await screen.findByText("You are not signed in.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Withdraw from the study" })).toBeNull();
});

test("the account page shows the version accepted, with a link to reread it", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/account");
  expect(await screen.findByText(/You accepted version v1\.0\./)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Read it again" }));
  expect(window.location.pathname).toBe("/information");
});

test("withdrawing asks for confirmation; Cancel sends nothing", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/account");
  expect(await screen.findByText("You can withdraw until 14 February 2027.")).toBeInTheDocument();
  fireEvent.click(button("Withdraw from the study"));
  expect(screen.getByText(/This cannot be undone\./)).toBeInTheDocument();
  fireEvent.click(button("Cancel"));
  expect(button("Withdraw from the study")).toBeInTheDocument();
  expect(server.posts()).toEqual([]);
});

test("a confirmed withdrawal is recorded, and then the site says so everywhere", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/account");
  fireEvent.click(await screen.findByRole("button", { name: "Withdraw from the study" }));
  fireEvent.click(button("Yes, withdraw"));
  expect(
    await screen.findByText("You have withdrawn from the study. You cannot play again."),
  ).toBeInTheDocument();
  expect(server.posts()).toEqual([{ method: "POST", path: "/withdraw", body: { confirm: true } }]);
  expect(screen.queryByRole("button", { name: "Withdraw from the study" })).toBeNull();
  fireEvent.click(footer().getByRole("link", { name: "Fish" }));
  expect(
    screen.getByRole("heading", { name: "You have withdrawn from the study" }),
  ).toBeInTheDocument();
});

test("after the last day there is no button, only when it closed", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  server.withdrawalOpen = false;
  visit("/account");
  expect(
    await screen.findByText(
      "Withdrawing through the website closed at the end of 14 February 2027.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Withdraw from the study" })).toBeNull();
});

test("a withdrawal the server refuses shows its reason", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/account");
  fireEvent.click(await screen.findByRole("button", { name: "Withdraw from the study" }));
  server.withdrawalOpen = false; // the day ended while the page was open
  fireEvent.click(button("Yes, withdraw"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Withdrawing closed at the end of 14 February 2027.",
  );
});

test("signing out goes back to the consent screen", async () => {
  server.standing = { accepted: "v1.0", withdrawn: false };
  visit("/account");
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() => {
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });
  expect(window.location.pathname).toBe("/");
  expect(server.posts()).toEqual([{ method: "POST", path: "/auth/sign-out", body: undefined }]);
  expect(footer().queryByRole("link", { name: "Your account" })).toBeNull();
});
