// Independent check of the frozen RNG vectors (T2.1 subtask 6.6).
// A from-scratch JavaScript implementation of fish-rng-v1, written from docs/determinism.md,
// recomputes every value in rng_v1.json. Run: node scripts/verify_rng_vectors.mjs
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const MASK = (1n << 64n) - 1n;

class SplitMix64 {
  constructor(state) { this.state = state & MASK; }
  next() {
    this.state = (this.state + 0x9e3779b97f4a7c15n) & MASK;
    let z = this.state;
    z = ((z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n) & MASK;
    z = ((z ^ (z >> 27n)) * 0x94d049bb133111ebn) & MASK;
    return z ^ (z >> 31n);
  }
  below(n) {
    const threshold = ((1n << 64n) - n) % n;
    for (;;) { const x = this.next(); if (x >= threshold) return x % n; }
  }
  shuffled(items) {
    const out = [...items];
    for (let i = out.length - 1; i > 0; i--) {
      const j = Number(this.below(BigInt(i + 1)));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  }
}

function u64be(v) { const b = Buffer.alloc(8); b.writeBigUInt64BE(v); return b; }

function stream(seed, name, index = 0n) {
  const nameBytes = Buffer.from(name, "utf8");
  const data = Buffer.concat([
    Buffer.from("fish-rng-v1\0", "latin1"), u64be(seed),
    Buffer.from([nameBytes.length]), nameBytes, u64be(index),
  ]);
  return new SplitMix64(createHash("sha256").update(data).digest().readBigUInt64BE(0));
}

const path = new URL("../packages/fish-rules/tests/vectors/rng_v1.json", import.meta.url);
const v = JSON.parse(readFileSync(path, "utf8"));
let checked = 0;
const eq = (got, want, what) => {
  if (got !== want) throw new Error(`${what}: got ${got}, want ${want}`);
  checked++;
};

eq(v.algorithm, "splitmix64-sha256-v1", "algorithm");
for (const c of v.next_u64.cases) {
  const g = stream(BigInt(c.seed), v.next_u64.stream);
  c.outputs.forEach((o, i) => eq(g.next().toString(), o, `next_u64 seed=${c.seed} #${i}`));
}
for (const c of v.stream_first_output) {
  eq(stream(BigInt(c.seed), c.name, BigInt(c.index)).next().toString(), c.first,
     `stream ${c.name}/${c.index}`);
}
for (const c of v.below.cases) {
  const g = stream(BigInt(v.below.seed), v.below.stream);
  c.outputs.forEach((o, i) => eq(g.below(BigInt(c.n)).toString(), o, `below n=${c.n} #${i}`));
}
for (const c of v.shuffled_range_54.cases) {
  const got = stream(BigInt(c.seed), v.shuffled_range_54.stream).shuffled([...Array(54).keys()]);
  eq(JSON.stringify(got), JSON.stringify(c.order), `shuffle seed=${c.seed}`);
}
console.log(`All ${checked} vector values match.`);
