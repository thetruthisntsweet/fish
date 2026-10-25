# Canonical Ruleset v1.1

The rules of Fish as this project plays them. `fish_rules` implements them exactly; every
game record carries the version it was played under (R.10.2), and `RULESET_VERSION` in
`fish_rules.version` is this document's version. Tests cite the rules they check by number
(`docs/testing.md` §3), and `scripts/check_rule_citations.py` checks that every rule below is
cited by a test or owed by a later task.

Some rules apply only on the project's website (timers, the Call button, bots); the
multi-agent environment has no timers and asks every agent in every declaration window
(R.8.6, R.8.9).

## R.1 Components and setup

- **R.1.1** Six players sit in seats 0 to 5, clockwise. Seats 0, 1 and 2 form one team, and
  seats 3, 4 and 5 the other, so teammates sit together. Seating does not affect turn order;
  call priority alternates between teams (R.8.1).
- **R.1.2** The deck has 54 cards: the 52 standard cards plus a red joker and a black joker,
  which are distinct cards.
- **R.1.3** The deck divides into nine sets of six cards each: the low set of each suit (2-7),
  the high set of each suit (9-A), and the 9th set (the four 8s and both jokers).
- **R.1.4** Every game is generated from a seed, which determines the deal of nine cards to
  each player and the seat of the first turn player.

## R.2 Information

- **R.2.1** Each player sees only their own hand.
- **R.2.2** Every player's hand size, the score, and the most recent event (an ask and its
  answer, a call and its result, or an after-call choice) are public. Earlier events are not
  redisplayed. Which sets have been scored, and by which team, stays displayed.
- **R.2.3** When a Fish call resolves, the true holder of each of its six cards is revealed to
  all players.
- **R.2.4** Asks are resolved automatically rather than answered by players. False answers
  cannot occur.
- **R.2.5** Players see each event as it occurs and may remember it. The platform does not
  redisplay past events, and participants attest that they will not keep written notes.
- **R.2.6** Every player sees how long each other player takes to act. The client shows each
  event the moment the server sends it, without batching or delay, and shows whose turn it is
  with a visible turn timer. Response time is therefore public.

## R.3 Asking

- **R.3.1** The current player must either ask or call. No one else may ask.
- **R.3.2** An ask names one opponent and one card. It is legal only if the opponent holds at
  least one card, the asker holds at least one card of that card's set, and the asker does not
  hold the card itself.
- **R.3.3** If the opponent holds the card, it moves to the asker, who keeps the turn.
  Otherwise the turn passes to the opponent who was asked.

## R.4 Calling

- **R.4.1** A call names one set and assigns each of its six cards to a specific member of the
  caller's team, the caller included.
- **R.4.2** An event is an ask and its answer, a call and its result, or an after-call choice.
  In the environment, a declaration window opens at the start of the game and after every
  event, before the current player acts. On the website, a window opens only when a player
  presses Call (R.8.3). Any player may call in any window, including out of turn and including
  players with no cards (except as in R.6.2). After a call, the after-call choice (R.5) is made
  first; the next declaration window opens once the new current player is set in the
  environment. In the environment, if a window closes with no declaration, the current player
  may ask or call; a call made this way proceeds directly to the 30-second assignment step
  (untimed in the environment).
- **R.4.3** Calling has two steps. During a window, a player declares a call and names the set,
  without yet assigning cards. When the window closes, the declared call with the highest
  priority (R.8.1) proceeds and all others are discarded. Discarded declarations are not shown
  to any player but are recorded in the event log. The caller whose call proceeds then has 30
  seconds to assign the six cards, during which the game is frozen. A caller who does not
  finish in 30 seconds has made an incorrect call. On the website, the current player calls the
  same way: pressing Call opens a window like any other, and a higher-priority declaration in
  that window proceeds instead.
- **R.4.4** A call is correct if every card is held by the teammate it was assigned to. A
  correct call scores the set for the caller's team; an incorrect call scores it for the other
  team.
- **R.4.5** Either way, all six cards leave play, from whichever hands hold them.
- **R.4.6** A call is *valid* if it names one set still in play and assigns all six of its
  cards to members of the caller's team. Invalid calls are rejected at input and never scored.
  Assigning a card to a teammate who holds no cards is valid; it simply makes the call
  incorrect.

## R.5 After a call

- **R.5.1** The team that scored the set chooses which of its players holding cards takes the
  turn. Under R.6.2, no choice is made.
- **R.5.2** If the caller's team is choosing, the caller makes the choice within 15 seconds. If
  the other team is choosing, its members vote, and votes not cast within 15 seconds are
  ignored. If the caller does not choose or no votes are cast, the game seed chooses among the
  scoring team's players holding cards. If the vote ties, it chooses among the tied seats. All
  members of the choosing team vote, including those with no cards. Only the outcome is shown
  to players; individual votes are recorded in the event log.

## R.6 Running out

- **R.6.1** A player with no cards takes no turns and cannot be asked, but may still call.
- **R.6.2** If one team holds no cards, asking ends. The team holding cards then calls the
  remaining sets one at a time, until R.7 ends the game. Before each call, the caller is the
  first member of that team in the R.8.1 priority order, and each such selection counts as a
  declaration window for the window index. The caller names the set and has 30 seconds to
  assign its six cards. Players on the team without cards may no longer call. During run-out,
  Call presses are rejected and recorded in the event log; only the selected caller may call.

## R.7 End of game

- **R.7.1** The game ends when a team claims five or more sets. With nine sets a tie is
  impossible.
- **R.7.2** If a call brings a team to five sets, the game ends immediately; no after-call
  choice is made.

## R.8 Platform specifics

- **R.8.1** Each declaration window resolves calls according to a deterministic priority order
  that alternates between teams. The game's seed and the window's index choose which team goes
  first and a starting player on each team; priority then alternates team by team, moving to
  the next teammate clockwise within each team each time. For example, starting with seat 1
  against seat 4: 1, 4, 2, 5, 0, 3. The website collects declared calls during the window and
  lets the first one in that order proceed when the window closes (R.4.3). A window's index is
  the number of declaration windows opened earlier in the same game, starting from 0. In the
  environment, a window opens after every event; on the website, only when a player presses
  Call (R.8.3), so the same game state can carry different indices on the two platforms.
- **R.8.2** The engine ends any game that reaches 1,000 asks as unfinished. Unfinished games
  are excluded from all analysis.
- **R.8.3** The Call button is always live on the website. No window is held open unless
  someone presses it: the first press opens a 1-second declaration window, during which other
  players may also declare, and R.8.1 then decides which call proceeds. An action submitted
  while a window is open is discarded; the newly chosen current player acts once the
  after-call choice is made. The player whose action was discarded is told so on screen and
  acts again if the turn is still theirs. When a window opens, players see that a call has been
  declared, but not who declared it or which set. When it closes, the caller whose call
  proceeds and the set they named are shown to all players for the 30-second assignment.
  Declarations discarded under R.8.1 are not shown (R.4.3). Call presses made during a call
  assignment or an after-call choice are rejected and recorded in the event log.
- **R.8.4** The current player has 60 seconds to act. A player who disconnects has 30 seconds
  to reconnect and resume their seat; their turn timer keeps running. A player who does not
  act in time, or does not reconnect in time, is replaced by a B1 bot for the rest of the game.
  The handover is recorded in the event log, and the player does not reclaim the seat. The
  turn timer pauses during declaration windows, call assignments and after-call choices. Every
  new turn starts a fresh 60-second timer, including a turn kept after a successful ask and one
  that begins after an after-call choice.
- **R.8.5** Every timer in this ruleset runs on the server clock.
- **R.8.6** The environment has no timers. Agents always act when asked, so no call times
  out, no vote goes uncast, and no seat is handed to a bot. The 1-second window, the 30-, 15-
  and 60-second limits, bot delays, reconnection and bot handover apply only on the website.
- **R.8.7** The server applies presses and actions in the order it receives them. Every Call
  press carries the number of the last event the player had seen. If a newer event has already
  been applied, the press is rejected only if that event scored the named set or moved one of
  its cards; otherwise it is accepted against the current state. A rejected press is not a
  declaration: the player is shown the new state and may press again. Rejected presses are
  recorded in the event log. The server measures each player's round-trip time every 5 seconds
  and records it in the event log, so analyses of call races can control for connection
  speed. An illegal action is rejected; the player is shown the current state and acts again.
- **R.8.8** Bots on the website wait before every action and every Call press. The delay is
  drawn at random, seeded by the game's seed, from 1.5 to 4 seconds until pilot data exists,
  and afterwards from the response-time distribution observed in the pilot (T4.2). Bot delays
  are recorded in the event log, and bot actions remain excluded from response-time analysis.
  After every event, each bot decides whether to declare a call. If it does, it presses Call
  once its delay has passed, provided no window is open and no call assignment or after-call
  choice is in progress at that moment; otherwise its decision is dropped, and it decides
  afresh after the next event. A bot does not declare in a window opened by another player.
- **R.8.9** The website and environment resolve call races differently, by design. In the
  environment every agent is asked in every window, so R.8.1 always decides. On the website a
  window opens only on a press and lasts 1 second, so in practice the first player to press
  usually proceeds, with R.8.1 deciding only among presses inside that second. Corpus games are
  played under the website mechanics and benchmark games under the environment mechanics;
  results are reported with that difference noted.

## R.9 Consistency

R.9 is one rule for citations; its points are not numbered.

- **R.9** The turn should never fall to a player without cards. A successful ask only adds
  cards to the asker, a failed ask passes the turn to someone who must have held cards to be
  asked, and every call is followed by a choice among players holding cards (except under
  R.6.2, or when the call ends the game).
- Calls are bounded. At most nine calls occur. A player with cards always has a valid call
  available, so the current player can always act: if no legal ask exists, they must call.
- Cards are conserved. Cards in hands plus cards in scored sets always total 54.
- A correct out-of-turn call seizes the initiative, because the caller's team then chooses who
  moves next.

## R.10 Versioning

- **R.10.1** This is ruleset v1.1. Any change to a rule creates a new version with a dated
  changelog entry below.
- **R.10.2** Every game record carries the ruleset version it was played under. Games played
  under different versions are analysed separately unless the change cannot affect play.

### Changelog

- v1.0 (Oct 2026): first canonical version.
- v1.1 (Oct 2026): R.5.2 states which seats the game seed chooses among. No games were played
  under v1.0.
