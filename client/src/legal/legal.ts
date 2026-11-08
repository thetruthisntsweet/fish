// The terms of use and the privacy policy, word for word (Terms and Privacy §1-3; T3.8).
//
// One entry per version, as for the study information (study/texts.ts): the server names the
// version a site shows (GET /study, fish_server.study.TERMS), and an old text is never
// changed. The two documents share a version. The pilot versions are built from the same
// sentences with exactly the parts §3 lists changed, and legal.test.ts checks that only those
// differ.

export type LegalBlock =
  | { readonly kind: "paragraph"; readonly text: string }
  | { readonly kind: "list"; readonly items: readonly string[] }
  | {
      readonly kind: "table";
      readonly header: readonly string[];
      readonly rows: readonly (readonly string[])[];
    };

export interface LegalSection {
  readonly heading: string;
  readonly blocks: readonly LegalBlock[];
}

export interface LegalDocument {
  readonly title: string;
  /** "Version 1.0, effective 30 November 2026." */
  readonly effective: string;
  /** Paragraphs before the first heading. */
  readonly intro: readonly LegalBlock[];
  readonly sections: readonly LegalSection[];
}

export interface LegalTexts {
  readonly version: string;
  readonly terms: LegalDocument;
  readonly privacy: LegalDocument;
}

const paragraph = (text: string): LegalBlock => ({ kind: "paragraph", text });
const list = (...items: string[]): LegalBlock => ({ kind: "list", items });

const EFFECTIVE = "Version 1.0, effective 30 November 2026.";

const CONTACT_CONCERN =
  "To raise a concern with someone other than the researcher, contact Dr. Hany Eldeib at hkeldeib@fcps.edu.";

// ---------------------------------------------------------------- terms of use v1.0

const RUNS: LegalSection = {
  heading: "Who runs this website",
  blocks: [
    paragraph(
      'This website is run for the Fish research study by Sanjeev Kumar, a student researcher, supervised by Dr. Hany Eldeib ("we", "us"). These terms cover your use of the website and its games. How your data is recorded, used and published is set out in the study information, which you accept before you play, and in our Privacy Policy.',
    ),
  ],
};

const WHO_CAN: LegalSection = {
  heading: "Who can use it",
  blocks: [
    paragraph(
      "You may use this website only if you live in the United States and are a legal adult where you live (18 or older; 19 or older in Alabama or Nebraska; 21 or older in Mississippi), and only after accepting the study information. Use only your own email address, and sign up only once.",
    ),
  ],
};

const FAIRLY: LegalSection = {
  heading: "Playing fairly",
  blocks: [
    paragraph("While you use this website, you agree:"),
    list(
      "not to communicate with your teammates about a game outside the game, by any means, as you confirm before you play;",
      "not to let a program play for you, or use any tool that reads or plays the game for you;",
      "not to play from more than one account, or let anyone else use yours;",
      "not to try to see cards or anything else the game does not show you, to interfere with the website or with other players' games, or to get around any limit the website sets;",
      "not to use the website for anything other than taking part in the study.",
    ),
  ],
};

const YOUR_GAMES = "Your games";

const STOPPING: LegalSection = {
  heading: "Stopping, withdrawing, and losing access",
  blocks: [
    paragraph(
      "You can stop playing at any time, and withdraw from the study as the study information describes. We may end or limit your access if you break these terms, or if we must to protect the study or the website. If we do, we tell you by email where we can. What happens to the games you have already played is set out in the study information.",
    ),
  ],
};

const AS_IT_IS: LegalSection = {
  heading: "The website is provided as it is",
  blocks: [
    paragraph(
      'The website is a research tool run by a student. It may change, be unavailable or end at any time, and a game can be interrupted, for example when a player disconnects or the server restarts. To the extent the law allows, we provide it "as is", without warranties of any kind, and we are not liable for any loss that comes from using it. Nothing in these terms takes away rights that the law does not allow to be taken away.',
    ),
  ],
};

const TERMS_CHANGES: LegalSection = {
  heading: "Changes to these terms",
  blocks: [
    paragraph(
      "If these terms change in any way that matters to you, they get a new version, and you see and accept it before your next game. Typo fixes keep the version.",
    ),
  ],
};

const LAW: LegalSection = {
  heading: "Law",
  blocks: [
    paragraph(
      "These terms are governed by the laws of the Commonwealth of Virginia, United States.",
    ),
  ],
};

const TERMS_CONTACT: LegalSection = {
  heading: "Contact",
  blocks: [paragraph(`Questions: 821sanjeevkumar@gmail.com. ${CONTACT_CONCERN}`)],
};

const TERMS: LegalDocument = {
  title: "Fish research study: terms of use",
  effective: EFFECTIVE,
  intro: [],
  sections: [
    RUNS,
    WHO_CAN,
    FAIRLY,
    {
      heading: YOUR_GAMES,
      blocks: [
        paragraph(
          "Your games are recorded as the study information describes. In March 2027 they are published as an anonymised dataset under the Creative Commons Attribution 4.0 licence (CC BY 4.0), unless you withdraw by 14 February 2027. To the extent you have any rights in the record of your play, you allow us to use it for the study and to publish it under that licence.",
        ),
      ],
    },
    STOPPING,
    AS_IT_IS,
    TERMS_CHANGES,
    LAW,
    TERMS_CONTACT,
  ],
};

// ---------------------------------------------------------------- privacy policy v1.0

const INTRO =
  "This policy explains what this website collects, why, who else handles it, how long it is kept, and what you can do about it. It says the same as the study information you accept before you play, which tells you more about the research.";

const RESPONSIBLE: LegalSection = {
  heading: "Who is responsible",
  blocks: [
    paragraph(
      "Sanjeev Kumar, a student researcher, supervised by Dr. Hany Eldeib. Contact: 821sanjeevkumar@gmail.com.",
    ),
  ],
};

const COLLECT: LegalSection = {
  heading: "What we collect",
  blocks: [
    {
      kind: "table",
      header: ["What", "When", "Why"],
      rows: [
        [
          "Your email address",
          "When you ask for a sign-in link",
          "To sign you in, to act on a withdrawal, and to contact you about this study",
        ],
        ["A random player ID", "When you first sign in", "To link your games without naming you"],
        [
          "Your answers to the three confirmations, which versions of the study information and of these terms you accepted, and when",
          "When you press Continue",
          "To decide which games may be used, and to show what you agreed to",
        ],
        [
          "Whether you were placed in a group that plays only with each other",
          "When you first sign in",
          "To keep that group's games apart",
        ],
        [
          "Every card dealt and every action in your games, the time of each action, your connection speed, and when you connect and disconnect during a game",
          "While you play",
          "For the study's analyses and the published dataset",
        ],
        [
          "Whether you joined a game through a shared link, and your answer to the note-taking question",
          "After each game",
          "For the study's analyses",
        ],
        [
          "A scrambled (hashed) copy of each sign-in link and sign-in, and when they were used and ended",
          "Each time you sign in",
          "To keep you signed in, and so that a link works only once",
        ],
        ["Your withdrawal, if you withdraw", "When you withdraw", "To remove your games"],
      ],
    },
    paragraph(
      "We do not collect your name, age, birth date, location, chat or any other text. There is nothing to type during a game.",
    ),
  ],
};

const IP: LegalSection = {
  heading: "IP addresses",
  blocks: [
    paragraph(
      "Our server sees your IP address in order to deliver the website. We do not store it. It is held in memory for up to an hour, only to limit how many sign-in emails can be asked for from one address, and it is never written to our logs or our database. Our hosting provider, Render, also handles it to carry your connection to our server.",
    ),
  ],
};

const COOKIES: LegalSection = {
  heading: "Cookies",
  blocks: [
    paragraph(
      'The website sets one cookie, fish_session, which keeps you signed in. It lasts 30 days or until you sign out, the page\'s scripts cannot read it, and it is sent only to this website. There are no analytics, advertising or tracking cookies. The website loads no scripts, fonts or images from other websites, and stores nothing else in your browser. Because nothing tracks you from site to site, a "Do Not Track" setting changes nothing here.',
    ),
  ],
};

const EMAILS: LegalSection = {
  heading: "Emails",
  blocks: [
    paragraph(
      "We send sign-in links and study emails, such as invitations to game nights, through Resend. We do not track whether you open our emails or click their links. Every study email has a link to stop study emails; sign-in links are sent only when you ask for one.",
    ),
  ],
};

const OTHERS_HEADING = "Who else handles your data";
const OTHERS_RENDER =
  "Render, in the United States (Virginia), runs the website and stores its database.";
const OTHERS_RESEND =
  "Resend sends our emails, and keeps your email address on our list until we delete it on 31 March 2027.";
const OTHERS_PUBLIC =
  "Anyone can use the published dataset. It contains no email addresses, and every player ID in it is replaced with a new random one.";
const OTHERS_NOT_SOLD =
  "We do not sell your data, use it for advertising, or give it to anyone else, unless the law requires us to.";

const KEPT_HEADING = "How long it is kept";
const KEPT_EMAIL = "Your email address, in our database and at Resend: deleted on 31 March 2027.";
const KEPT_SIGN_IN =
  "Sign-in links stop working after 15 minutes, and a sign-in lasts at most 30 days.";
const KEPT_BACKUPS =
  "Our host's backups of the database cover the last 3 days, so anything deleted is gone from them 3 days later.";
const KEPT_LOGS =
  "The server's logs, which contain no IP addresses, email addresses or sign-in links, are kept by Render for 7 days.";

const PROTECTED: LegalSection = {
  heading: "How it is protected",
  blocks: [
    paragraph(
      "The database can be reached only from inside our host's private network, and the game server can add records but cannot change or delete them. Sign-in links and sign-ins are stored only in scrambled form. Every connection to the website is encrypted. No system is perfectly secure; if we learn of a breach that affects you, we tell you by email.",
    ),
  ],
};

const CAN_DO_HEADING = "What you can do";
const CAN_STOP = "Stop playing at any time.";
const CAN_ASK =
  "Ask us what we hold about you, or ask us to correct your email address. Email us; we answer within 30 days.";
const CAN_DELETE =
  "Ask us to delete your email address before 31 March 2027. You can then no longer sign in or hear from us, and we can no longer link a withdrawal to your games, so withdraw first if you want to.";
const CAN_UNSUBSCRIBE = "Stop study emails with the link in any of them.";

const AGE: LegalSection = {
  heading: "Age",
  blocks: [
    paragraph(
      "This website is only for legal adults: 18 or older (19 or older in Alabama or Nebraska; 21 or older in Mississippi). If we learn that a player was younger, we remove their games as if they had withdrawn, and delete their email address.",
    ),
  ],
};

const POLICY_CHANGES: LegalSection = {
  heading: "Changes to this policy",
  blocks: [
    paragraph(
      "If this policy changes in any way that matters to you, it gets a new version, and you see it before your next game. Typo fixes keep the version.",
    ),
  ],
};

const POLICY_CONTACT: LegalSection = {
  heading: "Contact",
  blocks: [paragraph(`Questions or requests: 821sanjeevkumar@gmail.com. ${CONTACT_CONCERN}`)],
};

const PRIVACY: LegalDocument = {
  title: "Fish research study: privacy policy",
  effective: EFFECTIVE,
  intro: [paragraph(INTRO)],
  sections: [
    RESPONSIBLE,
    COLLECT,
    IP,
    COOKIES,
    EMAILS,
    {
      heading: OTHERS_HEADING,
      blocks: [list(OTHERS_RENDER, OTHERS_RESEND, OTHERS_PUBLIC), paragraph(OTHERS_NOT_SOLD)],
    },
    {
      heading: KEPT_HEADING,
      blocks: [
        list(
          KEPT_EMAIL,
          KEPT_SIGN_IN,
          "Everything else in the study database, including withdrawn games: deleted on 30 June 2027.",
          KEPT_BACKUPS,
          "Each week, the researcher keeps one copy of the games that count for the study, under random IDs and without email addresses, on a laptop with an encrypted disk. Each week's copy replaces the last, and it is deleted by 30 June 2027.",
          KEPT_LOGS,
          "The published dataset is permanent.",
        ),
      ],
    },
    PROTECTED,
    {
      heading: CAN_DO_HEADING,
      blocks: [
        list(
          CAN_STOP,
          "Withdraw until 14 February 2027, on your account page or by emailing us. Your games are then removed from the study, as the study information describes.",
          CAN_ASK,
          CAN_DELETE,
          CAN_UNSUBSCRIBE,
        ),
      ],
    },
    AGE,
    POLICY_CHANGES,
    POLICY_CONTACT,
  ],
};

// ---------------------------------------------------------------- the pilot site (§3)

const PILOT_TERMS: LegalDocument = {
  ...TERMS,
  // Terms: title
  title: "Fish research study: pilot terms of use",
  sections: TERMS.sections.map((section) =>
    section.heading === YOUR_GAMES
      ? {
          heading: YOUR_GAMES,
          // Terms: Your games
          blocks: [
            paragraph(
              "Your pilot games are recorded as the study information describes. They are used only to time games, set the bots' timing and plan the study's statistics. They are never published, and they are deleted, with the email list, on 31 March 2027.",
            ),
          ],
        }
      : section,
  ),
};

const PILOT_PRIVACY: LegalDocument = {
  ...PRIVACY,
  // Privacy: title
  title: "Fish research study: privacy policy for the pilot",
  sections: PRIVACY.sections.map((section) => {
    switch (section.heading) {
      case OTHERS_HEADING:
        // Who else handles your data, last bullet: removed
        return {
          heading: OTHERS_HEADING,
          blocks: [list(OTHERS_RENDER, OTHERS_RESEND), paragraph(OTHERS_NOT_SOLD)],
        };
      case KEPT_HEADING:
        // How long it is kept: the third bullet changed; the fifth and seventh removed
        return {
          heading: KEPT_HEADING,
          blocks: [
            list(
              KEPT_EMAIL,
              KEPT_SIGN_IN,
              "Everything else, including withdrawn games: deleted on 31 March 2027.",
              KEPT_BACKUPS,
              KEPT_LOGS,
            ),
          ],
        };
      case CAN_DO_HEADING:
        // What you can do, second bullet
        return {
          heading: CAN_DO_HEADING,
          blocks: [
            list(
              CAN_STOP,
              "Withdraw until 31 March 2027, on your account page or by emailing us. Every pilot game you played is then excluded from any further use, as the study information describes.",
              CAN_ASK,
              CAN_DELETE,
              CAN_UNSUBSCRIBE,
            ),
          ],
        };
      default:
        return section;
    }
  }),
};

export const LEGAL: Readonly<Record<string, LegalTexts>> = {
  "v1.0": { version: "v1.0", terms: TERMS, privacy: PRIVACY },
  "v1.0-pilot": { version: "v1.0-pilot", terms: PILOT_TERMS, privacy: PILOT_PRIVACY },
};

/** The terms and privacy policy of ``version``, or undefined if this client has none. */
export function legalTexts(version: string): LegalTexts | undefined {
  return Object.hasOwn(LEGAL, version) ? LEGAL[version] : undefined;
}
