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
| `cohort` | block number | Held-out cohort positions, seeded by the cohort seed, not a game seed | corpus.md §2.1 |

Run-out (R.6.2) uses `priority` with the run-out window's index; it has no stream of its own.

`fish_rules.cohort` (`fish-cohort-v1`) takes the first 3 entries of `shuffled(range(20))`
from stream `cohort` with the block number as the index, sorted: those positions of the block
of sign-ups `20 × block` onward are in the held-out cohort. `tests/vectors/cohort_v1.json`
freezes 17 blocks (seeds 0, 1, 2026 and 2^64 − 1 at blocks 0, 1, 2 and 249, and seed 12345 at
block 2^64 − 1). It was written once by `scripts/make_cohort_vectors.py`, which refuses to
overwrite it, and is checked by the Python tests and by `scripts/verify_rng_vectors.mjs`.

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

**Actions as data.** `fish_rules.codec` writes each action as `{"type": <name>, <field>:
<int or list of ints>}`, named `fish-actions-v1`, and reads it back exactly.

**Game records.** `fish_rules.record.game_record` writes a game as plain data:
`{"ruleset", "action_encoding", "seed", "outcome", "winner", "actions"}`, with the seed as a
decimal string and the outcome and winner None until the game is over. `replay_record`
replays it and checks the ruleset version (R.10.2), the action encoding and the recorded
outcome; it ignores keys it does not know, so the golden replays and the corpus schema (T1.6)
can add their own. The environment's `FishEnv.record()` returns one.

**Golden replays.** `packages/fish-rules/tests/golden/` holds eight complete games, each its
seed, its actions and the state hash after every action, chosen so that together they include
run-out, a seed tie-break, a discarded declaration, a call on a turn, the caller choosing, the
team voting, and each team winning. They were played by `fish_rules.playout.random_game`
under environment mechanics and written once by `scripts/make_golden_games.py`, which
refuses to overwrite them. Every test run replays them. A golden game that stops replaying is
a rule that changed: regenerate (`--regenerate`) only with a new ruleset version or a new
state encoding, and record why in the decision log.

## 9. Action indices

Agents choose among integers rather than action objects. `fish_rules.action_index` gives every
seat action an index in `range(913)`, read from the acting seat's point of view so one policy
serves every seat. Opponent index *i* is the *i*-th seat of the other team and teammate index
*j* the *j*-th seat of the seat's own team (itself included), both ascending.

| Indices | Action |
|---|---|
| 0–161 | `Ask`: 54 × opponent index + card |
| 162–170 | `Call`: 162 + set |
| 171–179 | `Declare`: 171 + set |
| 180 | `Pass` |
| 181–909 | `Assign`: 181 + the six holders' teammate indices as a base-3 number, the set's first card most significant |
| 910–912 | Nominate teammate *j*: `Choose` in the after-call choice, `Vote` in the team vote (R.5.2) |

The layout is named `fish-action-index-v1`. Game records do not use it (they store actions
with `fish-actions-v1`, §8), but trained agents do, so it is frozen like the vectors:
`packages/fish-rules/tests/vectors/action_index_v1.json` lists all 913 indices for seat 1
(team 0) and seat 4 (team 1), written once by `scripts/make_action_index_vectors.py`, which
refuses to overwrite it. `legal_indices` and `legal_mask` are built from
`fish_rules.engine.legal_actions`, so a mask allows exactly the actions the engine accepts.

## 10. Views as data

`fish_rules.view.view_to_data` writes what one seat may know (`fish_rules.view.project`,
T2.4) as plain JSON, named `fish-view-v1`. The server sends it to each client, and the client
renders it.

| Key | Value |
|---|---|
| `encoding` | `"fish-view-v1"` |
| `seat` | the seat this view belongs to |
| `hand` | the seat's own cards, ascending card numbers (§6) |
| `hand_sizes` | six ints, one per seat |
| `scored_by` | nine entries, one per set: the team that scored it, or `null` while in play |
| `phase` | `"turn"`, `"window"`, `"assign"`, `"choose"`, `"vote"`, `"runout"` or `"over"` |
| `current` | the seat whose turn it is, or `null` once the game is over |
| `call` | `{"caller", "set_id"}` while a call is being assigned, else `null` |
| `choice` | `{"team", "candidates", "chooser", "own_vote"}` during an after-call choice, else `null`; `chooser` is `null` when the team votes, `own_vote` is this seat's vote only |
| `window` | `{"own_declaration", "responded"}` while a window is open, else `null`; this seat's answer only |
| `last_event` | the most recent event, `{"type": "AskEvent" \| "CallEvent" \| "ChoiceEvent", ...its fields}`, or `null` before the first |
| `outcome` | `"finished"` or `"unfinished"` once the game is over, else `null` |
| `winner` | the winning team once a finished game is over, else `null` |
| `legal` | the indices of the actions this seat may take now, ascending (§9) |

An event's fields are those of `fish_rules.events`: an ask's `number`, `asker`, `target`,
`card` and `success`; a call's `number`, `caller`, `set_id`, `source`, `assignment` (`null`
if the caller ran out of time), `holders` (the true holder of each card, R.2.3), `correct`
and `scored_by`; a choice's `number`, `team` and `seat`.

`packages/fish-rules/tests/vectors/view_v1.json` freezes 124 views: from each golden game,
the first state in each phase and the first after each kind of event, for seats 0 and 4. It
was written once by `scripts/make_view_vectors.py`, which refuses to overwrite it.

## 11. Observations for agents

`fish_rules.observation.encode` turns a seat's view (§10, `fish_rules.view`) into 648 bits,
named `fish-obs-v1`, so an agent observes exactly what the projection allows. Seats appear as
*seat slots* relative to the observer, matching the action layout (§9): slots 0–2 are the
observer's team in ascending seat order (the observer included; `me` says which), slots 3–5
the other team in ascending order. "Mine" and "theirs" are the observer's team and the other.
A one-hot block with no bit set means "none" or "not applicable".

| Bits | Block | Contents |
|---|---|---|
| 0–53 | `hand` | own cards: bit *c* is card *c* (§6) |
| 54–56 | `me` | one-hot: which own-team slot (0–2) is this seat |
| 57–386 | `hand_sizes` | per seat slot, one-hot over 0–54 cards: bit 55 × slot + size |
| 387–413 | `sets` | per set, one-hot: 3 × set + 0 in play, 1 scored by mine, 2 scored by theirs |
| 414–420 | `phase` | one-hot: turn, window, assign, choose, vote, runout, over |
| 421–426 | `current` | one-hot seat slot whose turn it is; none once the game is over |
| 427–432 | `call_caller` | while a call is assigned: the caller's seat slot |
| 433–441 | `call_set` | and its set |
| 442–443 | `choice_team` | during an after-call choice, one-hot: mine, theirs |
| 444–449 | `choice_candidates` | flags: the seat slots that may be chosen |
| 450–455 | `choice_chooser` | one-hot: the caller, when the caller chooses; none in a vote |
| 456–461 | `own_vote` | one-hot: this seat's vote, once cast |
| 462–470 | `own_declaration` | one-hot: this seat's declaration in the open window |
| 471 | `responded` | this seat has answered the open window |
| 472–474 | `event` | most recent event, one-hot: ask, call, choice; none before the first |
| 475–480 | `ask_asker` | ask: asker's seat slot |
| 481–486 | `ask_target` | ask: target's seat slot |
| 487–540 | `ask_card` | ask: the card |
| 541 | `ask_success` | ask: the target held it |
| 542–547 | `call_event_caller` | call: caller's seat slot |
| 548–556 | `call_event_set` | call: the set |
| 557–559 | `call_event_source` | call, one-hot: window, turn, runout |
| 560–595 | `call_event_assignment` | call: per card *i* of the set, bit 6 × *i* + the assigned seat slot |
| 596 | `call_event_timed_out` | call: no assignment (the caller ran out of time; website only) |
| 597–632 | `call_event_holders` | call: per card *i*, bit 6 × *i* + the true holder's seat slot (R.2.3) |
| 633 | `call_event_correct` | call: it was correct |
| 634–635 | `call_event_scored_by` | call, one-hot: scored by mine, theirs |
| 636–637 | `choice_event_team` | choice, one-hot: mine, theirs |
| 638–643 | `choice_event_seat` | choice: the chosen seat slot |
| 644–645 | `outcome` | once over, one-hot: finished, unfinished |
| 646–647 | `winner` | once a finished game is over, one-hot: mine, theirs |

`packages/fish-rules/tests/vectors/obs_v1.json` freezes the observations of the 124 views in
`view_v1.json`, as the indices of the bits set. It was written once by
`scripts/make_obs_vectors.py`, which refuses to overwrite it.

## 12. Replay digest

`scripts/replay_digest.py` plays 100 games of each of three kinds from seeds 0–99:
`fish_rules.playout.random_game` under environment mechanics, six B0 agents (b0-v1) in the
environment, and website mechanics (Call presses on any turn, windows closed whoever has
answered, assignment and choice timeouts, random legal seat actions). Each game goes through
its log: its record (§8) is written to JSON text, read back and replayed, and the replay must
give the same records and states as playing did. A game's digest is the SHA-256 of its
record's JSON (sorted keys, compact) and the state hash after every action, one per line;
each kind's digest covers its games' digests in seed order, and the overall digest covers the
three kinds. The encoding is named `fish-replay-digest-v1`.

`packages/fish-agents/tests/vectors/replay_digest_v1.json` freezes the result. CI's
determinism job recomputes it under `PYTHONHASHSEED` 0 and 4242, checks both against the
frozen file and compares the two outputs byte for byte. The script refuses to overwrite a
file; the frozen digest changes only with the ruleset, the action or state encoding, or B0's
version, together with the golden replays (§8) and a decision log entry.
