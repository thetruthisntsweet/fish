// Room codes (docs/server.md §3): six letters and digits a group shares to sit together.

/** The letters and digits of a room code: none that look alike (no I, O, 0 or 1). */
export const ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
export const ROOM_CODE_LENGTH = 6;
/** fish_server.protocol.ROOM_CODE_PATTERN. */
export const ROOM_CODE_PATTERN = `^[${ROOM_CODE_ALPHABET}]{${String(ROOM_CODE_LENGTH)}}$`;

/** What someone typed, as a code: upper case, without spaces or dashes. */
export function asCode(typed: string): string {
  return typed.toUpperCase().replace(/[\s-]/g, "");
}

/** The link to share for room `code`: the front page, which fills the code in. */
export function roomLink(code: string, origin: string = window.location.origin): string {
  return `${origin}/?room=${code}`;
}

/** The room code a shared link carries, if it carries a real one. */
export function roomFromLink(search: string = window.location.search): string | null {
  const code = asCode(new URLSearchParams(search).get("room") ?? "");
  return new RegExp(ROOM_CODE_PATTERN).test(code) ? code : null;
}

/** Take the room code out of the address once it has been used, so a reload does not reuse
 * it. */
export function forgetRoomLink(): void {
  const url = new URL(window.location.href);
  if (url.searchParams.has("room")) {
    url.searchParams.delete("room");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }
}
