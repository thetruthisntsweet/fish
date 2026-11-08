// The study information, word for word (Consent Screen §1, §4; T3.3).
//
// One entry per version. A site shows the version the server names (GET /study), and anyone
// can reread the version they accepted, so an old text is never changed: a new text is a new
// version, here, in versions.json and in fish_server/study.py. Typo fixes keep the version
// (Consent Screen §2.8).
//
// The pilot text is the study text with exactly nine parts changed (§4). It is built from
// the same sentences below, so everything else is word for word by construction, and
// texts.test.ts checks that exactly those nine parts differ.

import versions from "./versions.json";

/** The three confirmations, named as the server records them (fish_server.consent). */
export const CONFIRMATIONS = ["us_resident_adult", "agrees", "no_outside_communication"] as const;
export type Confirmation = (typeof CONFIRMATIONS)[number];

export type Block =
  | { readonly kind: "paragraph"; readonly text: string }
  | { readonly kind: "list"; readonly items: readonly string[] };

export interface Section {
  readonly heading: string;
  readonly blocks: readonly Block[];
}

export interface StudyText {
  readonly version: string;
  /** The last day to withdraw on the website, as the text says it (versions.json). */
  readonly withdrawUntil: string;
  readonly title: string;
  /** Top to bottom; the first is the key points. */
  readonly sections: readonly Section[];
  /** The line above the confirmations. */
  readonly confirm: string;
  readonly confirmations: Readonly<Record<Confirmation, string>>;
}

const paragraph = (text: string): Block => ({ kind: "paragraph", text });
const list = (...items: string[]): Block => ({ kind: "list", items });

// ---------------------------------------------------------------- v1.0

const KEY_POINTS = "Key points";
const KEY_STUDY =
  "This is a research study. You play an online card game, Fish. Your games are recorded and, once anonymised, published for anyone to use.";
const KEY_VOLUNTARY =
  "Taking part is voluntary and unpaid. Play as many or as few games as you like, and stop at any time, even in the middle of a game.";
const KEY_EMAIL =
  "We keep your email address, to sign you in and to contact you about this study, and what happens in your games. We never collect your name, your age or any chat.";
const KEY_WITHDRAW = "You can withdraw until 14 February 2027.";

const WHO: Section = {
  heading: "Who is running this study",
  blocks: [
    paragraph(
      "Sanjeev Kumar, a student researcher, supervised by Dr. Hany Eldeib, a professor of computer science. Questions or concerns: 821sanjeevkumar@gmail.com. To raise a concern with someone other than the researcher, contact Dr. Hany Eldeib at hkeldeib@fcps.edu.",
    ),
  ],
};

const FOR_HEADING = "What the study is for";
const FOR_OPENING =
  "In Fish, every signal you send your teammates is also seen by your opponents. This study measures how much players' actions reveal about hidden cards, and whether players signal on purpose.";
const FOR_AGENTS = "The games will also be used to build and test AI agents that play Fish.";

const WHAT_YOU_DO: Section = {
  heading: "What you will do",
  blocks: [
    paragraph(
      'After this page, you enter your email address and receive a sign-in link; there is no password. You then play games of six players in two teams of three, on this website, for as long as you like. After each game we ask one question: "Did you take notes during this game?"',
    ),
    paragraph(
      "When you sign up, you may be placed at random in a group whose members play only with each other. This changes nothing about how you play.",
    ),
  ],
};

const BOTS: Section = {
  heading: "Bots",
  blocks: [
    paragraph(
      'Some seats may be played by computer programs. They are always labelled "bot". If you are disconnected for 30 seconds, or do not act within your 60-second turn, a bot finishes the game in your seat, and you cannot rejoin that game.',
    ),
  ],
};

const RECORDED: Section = {
  heading: "What we record",
  blocks: [
    list(
      "Your email address, used only to sign you in and to contact you about this study, kept in a separate table from all game data",
      "A random player ID, which links your games without naming you",
      "Your answers to the three confirmations at the bottom of this page",
      "Every card dealt and every action in your games, the time of each action, and your connection speed",
      "Whether you joined a game through a link shared with friends, and your answer to the note-taking question",
    ),
    paragraph(
      "We do not collect your name, age, birth date, location or any chat. There is nothing to type during a game. Our server sees your IP address in order to deliver the website, but does not store it with game data.",
    ),
  ],
};

const KEPT_HEADING = "How your data is kept";
const KEPT_DATABASE =
  "In a database in the United States that can be reached only from inside our hosting provider's private network. The game server can add records but cannot change or delete them.";
const KEPT: Section = {
  heading: KEPT_HEADING,
  blocks: [
    paragraph(
      `${KEPT_DATABASE} As a backup, the researcher also keeps one copy of the games that count for the study, under random IDs and without email addresses, on a laptop with an encrypted disk. It is replaced every week, so withdrawn games leave it within a week, and it is deleted by 30 June 2027.`,
    ),
  ],
};

const PUBLICATION = "Publication";
const PUBLISHED: Section = {
  heading: PUBLICATION,
  blocks: [
    paragraph(
      "In March 2027, the games are published as a dataset under the Creative Commons Attribution 4.0 licence (CC BY 4.0). Anyone may copy and use it, including for commercial purposes, as long as they credit the study. Everything in the list above except your email address is included.",
    ),
    paragraph(
      "Before publication, every player ID is replaced with a new random one, and no link between the old and new IDs is kept. We delete the email list on 31 March 2027. Until then, we could in principle match a published game to your email address. After that date, no one can.",
    ),
  ],
};

const WITHDRAWING = "Withdrawing";
const WITHDRAWAL: Section = {
  heading: WITHDRAWING,
  blocks: [
    paragraph(
      "Until 14 February 2027, you can withdraw through this website or by emailing 821sanjeevkumar@gmail.com. Every game you played is then removed from the study. A game cannot be replayed with a seat missing, so the other players' moves in those games are removed too; in the same way, if another player in one of your games withdraws, that game is removed.",
    ),
    paragraph(
      "Removed games are never used or published. They are kept until the study database is deleted on 30 June 2027, and cannot be linked to anyone once the email list is deleted. After 14 February 2027, the data is frozen and anonymised, and games can no longer be removed.",
    ),
  ],
};

const EXTRA_GAMES: Section = {
  heading: "Possible extra games in March 2027",
  blocks: [
    paragraph(
      "If one of the study's AI agents passes a test at the end of February, you may be invited to play some extra games with it. Those games are kept separate, published the same way, and can be withdrawn until 31 March 2027.",
    ),
  ],
};

const RISKS = "Risks";
const RISKS_OPENING =
  "The risks are minimal: you are playing a card game, for as long as you choose.";
const RISKS_TRACED =
  "The main risk is that a published game could be traced back to you; the steps above are there to prevent it.";

const CONFIRM = "Before you continue, please confirm:";
const CONFIRMED: Readonly<Record<Confirmation, string>> = {
  us_resident_adult:
    "I live in the United States and I am a legal adult where I live: 18 or older (19 or older in Alabama or Nebraska; 21 or older in Mississippi).",
  agrees: "I have read this page, and I agree to take part.",
  no_outside_communication:
    "While playing, I will not communicate with my teammates about the game outside the game: no texts, calls, voice chat or talking in person.",
};

const STUDY: StudyText = {
  version: "v1.0",
  withdrawUntil: versions["v1.0"].withdrawUntil,
  title: "Fish research study: before you play",
  sections: [
    { heading: KEY_POINTS, blocks: [list(KEY_STUDY, KEY_VOLUNTARY, KEY_EMAIL, KEY_WITHDRAW)] },
    WHO,
    { heading: FOR_HEADING, blocks: [paragraph(`${FOR_OPENING} ${FOR_AGENTS}`)] },
    WHAT_YOU_DO,
    BOTS,
    RECORDED,
    KEPT,
    PUBLISHED,
    WITHDRAWAL,
    EXTRA_GAMES,
    { heading: RISKS, blocks: [paragraph(`${RISKS_OPENING} ${RISKS_TRACED}`)] },
  ],
  confirm: CONFIRM,
  confirmations: CONFIRMED,
};

// ---------------------------------------------------------------- v1.0-pilot (§4)

const PILOT_USES =
  "Pilot games are used only to time games, set the bots’ timing and plan the study’s statistics";

const PILOT: StudyText = {
  version: "v1.0-pilot",
  withdrawUntil: versions["v1.0-pilot"].withdrawUntil,
  // 1. Title
  title: "Fish research study: pilot games",
  sections: [
    {
      heading: KEY_POINTS,
      blocks: [
        list(
          // 2. Key points, first bullet
          "This is the pilot of a research study. You play an online card game, Fish, so we can time games and set up the study. Pilot games are never published.",
          KEY_VOLUNTARY,
          KEY_EMAIL,
          // 3. Key points, last bullet
          "You can withdraw at any time until 31 March 2027.",
        ),
      ],
    },
    WHO,
    {
      heading: FOR_HEADING,
      // 4. What the study is for, last sentence
      blocks: [
        paragraph(`${FOR_OPENING} ${PILOT_USES}; they are not used to build or test AI agents.`),
      ],
    },
    WHAT_YOU_DO,
    BOTS,
    RECORDED,
    // 9. How your data is kept, last two sentences: removed (pilot games are never copied)
    { heading: KEPT_HEADING, blocks: [paragraph(KEPT_DATABASE)] },
    {
      heading: PUBLICATION,
      // 5. Publication, both paragraphs
      blocks: [
        paragraph(
          `${PILOT_USES}. They are never published, and they are deleted, with the email list, on 31 March 2027.`,
        ),
      ],
    },
    {
      heading: WITHDRAWING,
      // 6. Withdrawing, both paragraphs
      blocks: [
        paragraph(
          "Until 31 March 2027, you can withdraw through this website or by emailing 821sanjeevkumar@gmail.com. Every pilot game you played is then excluded from any further use, including the other players' moves in those games, and deleted with the rest on 31 March 2027.",
        ),
      ],
    },
    // 7. Possible extra games in March 2027: removed
    {
      heading: RISKS,
      // 8. Risks, last sentence
      blocks: [
        paragraph(
          `${RISKS_OPENING} Pilot games are never published, so the main risk is a data breach before they are deleted on 31 March 2027; the steps above are there to prevent it.`,
        ),
      ],
    },
  ],
  confirm: CONFIRM,
  confirmations: CONFIRMED,
};

/** Every text the site has, by version. */
export const TEXTS: Readonly<Record<string, StudyText>> = {
  [STUDY.version]: STUDY,
  [PILOT.version]: PILOT,
};

/** The text of ``version``, or undefined if this client does not have it. */
export function studyText(version: string): StudyText | undefined {
  return Object.hasOwn(TEXTS, version) ? TEXTS[version] : undefined;
}
