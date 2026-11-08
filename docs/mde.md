# Minimum detectable effects (T4.2)

Research Questions §5.4: "A minimum detectable effect for each primary metric is computed from
the pilot (T4.2) and recorded before launch." Dr. Hany decided that this is enough, with no
target sample size (§6). This page records how they are computed, and, from the pilot, what
they are. The figures go in §3 before the study opens on 8 December 2026, and are not changed
afterwards. Recomputing them once B2 and B3 exist (§4) adds a section; it does not replace
this one.

## 1. What an MDE is here

The smallest true effect that the planned analysis would find with **80% power** in a
**two-sided test at 5%**: `MDE = (z(0.975) + z(0.80)) x SE = 2.80 x SE`, where SE is the
standard error of the primary metric over the games analysed. The SE is a **game-level
bootstrap** (10,000 resamples, seed 20261208), the same resampling the analysis uses (§5.4),
measured over the pilot's corpus games and scaled to `n` games by `sqrt(pilot games / n)`.
That scaling assumes the study's games vary as much as the pilot's.

Each MDE is given for two sizes:
- **150 games**, about one test set's primary-set games. RQ1's information gain is computed on
  each test set, the held-out cohort's and the in-population one (§5.1), each about 15% of
  the corpus. So this is the size that matters for RQ1's headline.
- **1,000 games**, the corpus's target, for comparison and for metrics computed over the whole
  corpus.

## 2. The proxies

The primary metrics need B2 (T5.3) and B3 (T5.5), which don't exist before launch. Each is
stood in for by a quantity computed from the same games. Only its spread from game to game is
used: its level means nothing for the real metric.

| Question | Primary metric | Proxy | Why it is a fair stand-in |
|---|---|---|---|
| RQ1 | information gain, B2 − B3 log loss, bits per card | Layer 1's log loss: every seat's belief after every event (T1.1 §1), each card it doesn't hold whose place isn't public, with the possible holders weighted equally (the floor model) | the same cards, decision points and pooling as the real metric. The real metric is a paired difference on those cards, which should vary less than one model's loss does, so this MDE is on the cautious side |
| RQ2 | mean leakage, bits per action | a hand-count policy (asks for a set in proportion to how many of its cards the asker holds), comparing the asker's true counts with the counts the public view expects (Layer 1's public deduction, possible holders weighted equally). People's asks only | the robustness model of §3.1 in its simplest form, on the same actions. Calls and choices are left out |
| RQ3 | cross-play gap, a difference of win rates | the pilot's share of finished games won by team 0 | the gap is a difference between two win rates. Its MDE is for two arms of `n` finished games each, at the pilot's win rate. Common seeds (§5.2) would only make it smaller |

`python -m fish_server.mde` computes all three on the pilot site, from the corpus records of
games started on or after `--since`, and prints the table in §3. It names no game or player.

## 3. From the pilot

To be filled in from `python -m fish_server.mde --since 2026-12-01` in `fish-staging`'s Shell,
on 6 or 7 December ([runbooks/pilot.md](runbooks/pilot.md) §4 step 4).

Pilot games used:

| Primary metric | Proxy | Pilot value (SE) | MDE at 150 games | MDE at 1,000 games |
|---|---|---|---|---|
| RQ1 information gain | Layer 1 log loss | | | |
| RQ2 mean leakage | hand-count policy, asks | | | |
| RQ3 cross-play gap | win rate, team 0 | | | |

## 4. When B2 and B3 exist

T6.4 and T6.5 recompute each MDE with the real metric on the training split's games, by the
same method, and add them here as a new section, with the date. The figures in §3 stay as they
were recorded before launch.
