# Datasheet plan

The released corpus ships with a datasheet (T7.1) in the form of *Datasheets for Datasets*
(Gebru et al., 2021), whose questions fall into seven sections: motivation, composition,
collection, preprocessing, uses, distribution and maintenance. This plan, written before any
data exists (T1.6), says for each question what will answer it and when. Most answers are
fixed by the corpus design ([corpus.md](corpus.md)) and can be written now; counts come from
the frozen export; a few are decisions still to be made, listed in §8.

**When** is one of:

| When | Meaning |
|---|---|
| now | fixed by the design; the text below is the answer, to be copied into the datasheet |
| weekly | tracked from launch by the integrity checks (T4.4) |
| freeze | known when the corpus is frozen and anonymised (T4.5, by 28 February) |
| release | written for the release (T7.1) |

Numbers marked *freeze* are computed from the frozen export, never counted by hand:
`fish_server.corpus_export` gives the games and the reasons games were left out, and
`fish_rules.corpus.analysis_flags` and `response_times` give everything per game. T4.5
writes a script that prints them all; the datasheet quotes its output.

## 1. Motivation

| Question | Answer | When |
|---|---|---|
| Why was the dataset created? What gap does it fill? | To measure how much the way people play Fish reveals about hidden cards beyond what the rules allow (RQ1), how much players leak about their own hands and whether any of it is deliberate (RQ2), and to test agents with and against people (RQ3). No public corpus of Fish games with hands, response times and play conditions exists. | now |
| Who created it, on behalf of whom? | The project team, under Dr. Hany's supervision. | release (§8) |
| Who funded it? | | release (§8) |

## 2. Composition

| Question | Answer | When |
|---|---|---|
| What does an instance represent? | One complete game of Fish played by adults on the project's website, as one `fish-corpus-v1` record ([corpus.md](corpus.md) §7). | now |
| How many instances? | Games exported, and games left out by reason (not ended, abandoned, no person, a person not eligible). Target: 1,000 or more adult games. | freeze |
| All possible instances, or a sample? | Every game played on the site during collection that ended under the rules and in which every person was eligible (corpus.md §6). Not a random sample of Fish players: people chose to take part (§3). | now; counts at freeze |
| What data does each instance consist of? | The seed (which determines every hand), every action in order with its cause and its received and sent times on the server clock, the six seats (a pseudonymous person with a cohort flag and note answer, or a bot with its version and memory setting), handovers, round-trip times, rejected inputs, connections, bot delays, matchmaking, completion, the month played, and the ruleset, encodings and server commit. | now |
| Is there a label or target? | No labels are added. The outcome and winner are part of each game, and every hidden card's holder at every moment follows from the seed and the actions, which is what the belief models are scored against. | now |
| Is any information missing? | Note answers a person did not give (`unanswered`, `declined`); games that never ended or were abandoned are left out; bot-filled and handed-over seats have no human behaviour. All are flagged per game, and their counts are reported. | now; counts at freeze |
| Are relationships between instances explicit? | Yes, through pseudonyms: the same person has the same pseudonym in every game of one release, and different pseudonyms in different releases. | now |
| Are there recommended splits? | Yes. The held-out cohort's games are the cohort test set; all other games are split 70/15/15 into train, validation and test by game, with the split seed published (T1.1 §5.1). | now; seed at freeze |
| Errors, noise or redundancies? | Response times include network delay; round-trip samples are provided to allow for it. Server timestamps are on one monotonic clock per game. No game appears twice. | now |
| Self-contained, or does it rely on external resources? | Self-contained, but replaying a game to recover hands and states needs the rules engine, `fish-rules` (Apache-2.0), at the ruleset version recorded in each game. | now |
| Confidential data? | None: no free text is collected (there is no chat), and contact data never leaves the server. | now |
| Offensive or distressing content? | None: games contain only card-game actions. | now |
| Does it identify subpopulations? | Only the held-out cohort, a random 15% of sign-ups. No demographics are collected beyond confirming each person is 18 or older, and that confirmation is not released. | now |
| Can individuals be identified? | Not from the data: persons appear under per-release random pseudonyms, dates are kept to the month, and no names, emails, ids, wall-clock times or network identifiers are released. Someone who knows a player's games and month could in principle recognise them; the datasheet says so. | now |
| Sensitive data? | None collected. | now |

## 3. Collection process

| Question | Answer | When |
|---|---|---|
| How was the data acquired? | Directly: every action is logged by the game server as it happens (T3.1, T3.2), under the website mechanics of the Canonical Ruleset v1.1 (R.8.3 to R.8.8). | now |
| What mechanisms were used? | The project's website and game server; the rules engine validates every action. The pipeline is tested to reproduce every game exactly (corpus.md §1, §7). | now |
| Sampling strategy? | Adult volunteers, recruited starting with the Gov School group (T4.1). Players are matched solo by default; groups may join together, and those games are flagged. 15% of sign-ups, chosen at random in blocks of 20, play only with each other. | now; recruitment at release |
| Who was involved in collection, and how were they compensated? | | release (§8) |
| Over what timeframe? | From launch (13 December) to the freeze (by 28 February); the exact first and last months are in the data. | now; dates at freeze |
| Ethical review? | The research plan and consent screen were reviewed and approved by Dr. Hany, including ethics review (T1.4). | release (§8) |
| Collected from individuals directly or via third parties? | Directly, from their play on the site. | now |
| Were individuals notified, and did they consent? | Yes: every person passes an opt-in consent screen (T1.5) before playing, which states the CC BY 4.0 release, and confirms three things: they live in the United States and are a legal adult there, they agree to take part, and they will not communicate with teammates outside the game. The version of the text each person agreed to is stored, and copied onto each of their seats when a game starts. Whether they took notes is asked after each game instead. | now |
| Can consent be revoked? | Yes. A withdrawal is recorded as a record of its own (through the website or by email), and every later export leaves out every game the person played, whole. | now |
| Has an impact analysis been done? | | release (§8) |

## 4. Preprocessing and cleaning

| Question | Answer | When |
|---|---|---|
| What preprocessing was done? | Anonymisation only (T4.5): random pseudonyms per release, dates coarsened to the month, contact data and internal ids dropped. Games are not edited, filtered by quality or relabelled; games are left out only by the membership rules. | now |
| Is the raw data saved? | Yes, on the project's server, in append-only tables with point-in-time backups (D14), and not released. | now |
| Is the software available? | Yes: `fish_server.corpus_export` produces the release, and `fish_rules.corpus` reads, checks and replays it, both in the public repository. | now |

## 5. Uses

| Question | Answer | When |
|---|---|---|
| Has it been used already? | For RQ1 and RQ2 (T6.4, T6.5), and to fine-tune and evaluate the learned belief model B3 (T5.5). | release |
| Is there a list of papers using it? | The project's paper (T7.5) and the repository's README. | release |
| What else could it be used for? | Modelling belief and deception in team games with hidden information, studying response times in decision making, and training or evaluating Fish agents. | now |
| Could its composition affect future uses? | Players are adult volunteers, not a representative sample of Fish players; website games resolve call races differently from environment games (R.8.9), so results on one do not transfer unchanged to the other. Analyses should use the analysis-set flags (corpus.md §6) rather than all games. | now |
| Are there uses it should not be put to? | Attempting to identify players. | now |

## 6. Distribution

| Question | Answer | When |
|---|---|---|
| Will it be distributed to third parties? | Yes, publicly. | now |
| How? | One JSON Lines file of records, with this datasheet and a checksum. | now; host at release (§8) |
| When? | With the release candidate (M6, 28 March). | release |
| Licence? | CC BY 4.0 (D18), as stated on the consent screen; the software is Apache-2.0. | now |
| Third-party restrictions or export controls? | None. | now |

## 7. Maintenance

| Question | Answer | When |
|---|---|---|
| Who maintains it, and how can they be contacted? | | release (§8) |
| Is there an erratum? | Corrections are published as new versions with a changelog in the repository. | release |
| Will it be updated? | Only by re-exporting: after the freeze, a later version can only remove games (after withdrawals); recorded games are never edited. Every version names its export date and checksum, and every reported result names the version it used (T1.1 §5.5). | now |
| Limits on retention? | | release (§8) |
| Will older versions remain available? | | release (§8) |
| Can others contribute? | Not to the corpus itself; the software accepts contributions under its licence. | release |

## 8. Still to decide

These answers depend on decisions outside the design, to be settled by T7.1 at the latest:

- who is named as creator and maintainer, and the contact address;
- funding, and whether collection involved anyone paid, with any compensation for players;
- the reference for the ethics approval (T1.4), and whether an impact analysis is written;
- where the release is hosted, and whether it gets a DOI;
- whether older versions stay available after a later version removes withdrawn games (a
  withdrawal argues for removing them; reproducibility argues for keeping them), and how long
  the raw data is kept on the server.
