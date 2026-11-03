// A room's link (T3.4): shared from the room, it opens the lobby with the code filled in,
// and the code leaves the address once used (Consent Screen §1: "a link shared with friends").
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { ClientMessage } from "../game/connection.ts";
import { Lobby } from "./Lobby.tsx";

afterEach(() => {
  vi.unstubAllGlobals();
});

const AWAY = { type: "lobby", waiting: null, code: null, people: 0 } as const;

test("a shared link fills the code in, and joining takes it out of the address", () => {
  window.history.replaceState(null, "", "/?room=k7mp2q");
  const sent: ClientMessage[] = [];
  render(
    <Lobby
      lobby={AWAY}
      error={null}
      send={(message) => {
        sent.push(message);
        return true;
      }}
    />,
  );
  expect(screen.getByPlaceholderText("Room code")).toHaveValue("K7MP2Q");
  expect(sent).toEqual([]); // nothing until the player presses Join
  fireEvent.click(screen.getByRole("button", { name: "Join" }));
  expect(sent).toEqual([{ type: "join_room", code: "K7MP2Q" }]);
  expect(window.location.search).toBe("");
});

test("a room shows its link, and copies it", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const room = { type: "lobby", waiting: "group", code: "K7MP2Q", people: 2 } as const;
  render(<Lobby lobby={room} error={null} send={() => true} />);
  const link = `${window.location.origin}/?room=K7MP2Q`;
  expect(screen.getByLabelText("Room link")).toHaveTextContent(link);
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(writeText).toHaveBeenCalledWith(link);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });
});

test("without a clipboard, the link is there to copy by hand", () => {
  vi.stubGlobal("navigator", {});
  const room = { type: "lobby", waiting: "group", code: "K7MP2Q", people: 2 } as const;
  render(<Lobby lobby={room} error={null} send={() => true} />);
  expect(screen.getByLabelText("Room link")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy link" })).toBeNull();
});
