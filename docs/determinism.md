# Determinism: fish-rng-v1

Every Fish game is recorded as a **seed plus an ordered event log**. Replaying that record
must reproduce the same deal, first player, call-priority orders and tie-breaks, forever,
on any machine and in any language. This page specifies the random-number scheme, the card
numbering, the deal, call priority and event numbering exactly enough to reimplement them
from scratch; `scripts/verify_rng_vectors.mjs` is such a reimplementation, in JavaScript.

The algorithm is named `splitmix64-sha256-v1` (`fish_rules.rng.RNG_ALGORITHM`). It is
recorded in every game next to the ruleset version. **It is frozen:** any change, however
small, needs a new name and a new ruleset version (Canonical Ruleset R.10).

All arithmetic is on unsigned 64-bit integers. "mod 2^64" means keep the low 64 bits.

## 1. Generator: SplitMix64

State: one 64-bit integer `s`. Each call:

```
s = (s + 0x9E3779B97F4A7C15) mod 2^64
z = s
z = ((z XOR (z >> 30)) * 0xBF58476D1CE4E5B9) mod 2^64
z = ((z XOR (z >> 27)) * 0x94D049BB133111EB) mod 2^64
return z XOR (z >> 31)
```

Check: starting from `s = 1234567`, the first five outputs are
6457827717110365317, 3203168211198807973, 9817491932198370423, 4593380528125082431,
16408922859458223821.

## 2. Streams

Each use of randomness in a game has its own generator, so adding a draw in one place never
shifts another. A stream is identified by the game seed, a name and an index.

| Name | Index | Used for | Rule |
|---|---|---|---|
| `deal` | 0 | Dealing the 54 cards | R.1.4 |
| `first_player` | 0 | Seat of the first turn | R.1.4 |
| `priority` | window index | Call priority in a declaration window | R.8.1 |
| `tiebreak` | event number | Seat chosen when the caller does not choose or a vote ties | R.5.2 |
| `bot_delay` | event number × 6 + seat | Website bot delays | R.8.8 |
| `bot_policy` | event number × 6 + seat | Random choices made by bots | — |

Run-out (R.6.2) uses `priority` with the run-out window's index; it has no stream of its own.

The stream's starting state is the first 8 bytes, read big-endian, of SHA-256 over these
bytes in order:

| Bytes | Content |
|---|---|
| 12 | ASCII `fish-rng-v1` followed by one zero byte |
| 8 | game seed, unsigned, big-endian |
| 1 | length of the name in bytes |
| *length* | the name, UTF-8 |
| 8 | index, unsigned, big-endian |

Game seeds and indices are integers in [0, 2^64).

## 3. Integers in a range: `below(n)`

Returns a uniform integer in [0, n), for 1 ≤ n ≤ 2^64, with no modulo bias:

```
threshold = (2^64 - n) mod n
repeat:
    x = next()
    if x >= threshold: return x mod n
```

It always draws at least once, even when n = 1.

`between(lo, hi)` is `lo + below(hi - lo + 1)`. `choice(items)` is `items[below(len(items))]`.

## 4. Shuffle

Fisher–Yates on a copy of the input, in this exact order:

```
for i from n-1 down to 1:
    j = below(i + 1)
    swap items[i] and items[j]
```

A shuffle of n items makes exactly n−1 calls to `below`.

## 5. Test vectors

`packages/fish-rules/tests/vectors/rng_v1.json` holds 223 frozen values: 20 outputs for three
seeds, the first output of every stream name at two indices, 20 `below` results for seven
values of n, and ten full shuffles of 0–53. 64-bit values are stored as decimal strings.
A reimplementation is correct when it reproduces all of them.

The file was written once by `scripts/make_rng_vectors.py`, which refuses to overwrite it,
and is checked on every run of `scripts/check.sh` by both the Python tests and the
independent JavaScript implementation.

## 6. Cards and the deal

Every card has a fixed number, 0 to 53, and the event log names cards by number, so the
numbering is frozen along with the generator (`fish_rules.cards`).

**Card number = 6 × set + position.** Sets, by number:

| Set | Name | Cards, by position 0–5 |
|---|---|---|
| 0–3 | `low-C`, `low-D`, `low-H`, `low-S` | 2, 3, 4, 5, 6, 7 of that suit |
| 4–7 | `high-C`, `high-D`, `high-H`, `high-S` | 9, 10, J, Q, K, A of that suit |
| 8 | `eights` | 8C, 8D, 8H, 8S, red joker (`RJ`), black joker (`BJ`) |

Suits are always in the order clubs, diamonds, hearts, spades. So `2C` is 0, `10H` is 37,
`RJ` is 52 and `BJ` is 53.

**Deal (R.1.4).** Shuffle the list 0, 1, …, 53 (§4) with stream `deal`, index 0. Seat *k*
receives positions 9*k* to 9*k* + 8 of the shuffled list. Each hand is then sorted ascending.

**First player (R.1.4).** `below(6)` on stream `first_player`, index 0.

`packages/fish-rules/tests/vectors/deal_v1.json` freezes the card names, the set names, and
the deal and first player for ten seeds (0–8 and 2^64 − 1). It was written once by
`scripts/make_deal_vectors.py`, which refuses to overwrite it, and is checked by the Python
tests and by `scripts/verify_rng_vectors.mjs`.

## 7. Call priority

When a declaration window closes, the declared call that comes first in the window's
priority order proceeds (R.4.3, R.8.1). The order depends only on the game seed and the
window's index (the number of windows opened earlier in the game, from 0), and is computed
by `fish_rules.priority`.

**Draws.** From stream `priority` with the window index as its index, always all three and
always in this order:

1. `below(2)`: the team that goes first (0 or 1);
2. `below(3)`: the starting seat of team 0 (0, 1 or 2);
3. `below(3)`: the starting seat of team 1 (3 + the draw).

**Order.** Start with the first team's starting seat, then the other team's. After each pair,
move each team on to its next seat clockwise, wrapping within the team (0 → 1 → 2 → 0 and
3 → 4 → 5 → 3). Six seats result, alternating teams. For example, team 0 first with starts
1 and 4 gives 1, 4, 2, 5, 0, 3.

**Run-out (R.6.2).** The caller is the first seat of the team holding cards in the order of
the run-out window, computed the same way. Each run-out selection counts as a window.

`packages/fish-rules/tests/vectors/priority_v1.json` freezes 53 orders: seeds 0–4 at window
indices 0–9, plus (42, 2^64 − 1), (2^64 − 1, 0) and (2^64 − 1, 2^64 − 1). It was written once
by `scripts/make_priority_vectors.py`, which refuses to overwrite it, and is checked by the
Python tests and by `scripts/verify_rng_vectors.mjs`.

## 8. Event numbers and replay

**A game record is the seed plus the ordered list of actions** (`fish_rules.events`).
Applying the actions to `new_game(seed)` reproduces every state and every record.

**Event numbers.** An *event* is an ask and its answer, a call and its result, or an
after-call choice (R.4.2). Events are numbered 0, 1, 2, … in the order they happen. Nothing
else advances the number: window openings, declarations, discarded declarations, votes,
run-out selections and the end of the game are recorded but not numbered, and neither are
the server's own log rows (round-trip times, rejected presses). Streams indexed by event
number (§2) therefore come out the same on the website and in the environment.

**Tie-break (R.5.2, ruleset v1.1).** When the game seed chooses who takes the turn after a
call, it uses `choice` over the seats it chooses among, in ascending order, from stream
`tiebreak` with the *call's* event number as the index. It chooses among the tied seats if a
vote ties, and among all of the scoring team's players holding cards if the caller does not
choose or no votes are cast (website only; R.8.6).

`packages/fish-rules/tests/vectors/tiebreak_v1.json` freezes 65 choices: seeds 0–3 at call
event numbers 0, 1, 7 and 99, each with the seats (3, 4, 5), (0, 2), (1, 2) and (4), plus
seed and event 2^64 − 1 with seats (0, 1, 2). It was written once by
`scripts/make_tiebreak_vectors.py`, which refuses to overwrite it, and is checked by the
Python tests and by `scripts/verify_rng_vectors.mjs`.

**State hash.** Golden replays check `fish_rules.state.state_hash` after every action: the
SHA-256 of the state's canonical encoding (fixed keys, plain values, compact JSON with sorted
keys), named `fish-state-v1`. A hash is a test aid, not part of the game record, so the
encoding may change, but only under a new name and with the golden replays regenerated.
