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
