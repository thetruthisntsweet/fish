// The frozen vectors the Python packages are checked against (packages/fish-rules/tests/
// vectors), read for the client's tests, so the client and fish-rules can never name a card
// or an action differently. Read with import.meta.glob, not a plain import, so that the
// image's client build, which has only client/, never needs them.
const FOUND = import.meta.glob<unknown>("../../../packages/fish-rules/tests/vectors/*.json", {
  eager: true,
  import: "default",
});

/** The vector file `name` (e.g. `deal_v1.json`); throws if it is not there. */
export function vector(name: string): unknown {
  const key = Object.keys(FOUND).find((path) => path.endsWith(`/${name}`));
  if (key === undefined) {
    throw new Error(`no vector file ${name}`);
  }
  return FOUND[key];
}
