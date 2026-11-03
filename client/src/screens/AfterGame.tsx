// After a game (T3.4): how it ended, then the note-taking question, asked of each person
// still in the game once the rules end it (Research Plan §4; docs/corpus.md §4.2), in the
// server's own words, with three answers. Then the lobby.
import type { NoteAnswer } from "../generated/NoteAnswer.ts";
import type { NoteQuestion } from "../generated/NoteQuestion.ts";
import type { Ended } from "../game/connection.ts";
import { endingSentence } from "../game/describe.ts";

export function Ending({ ended }: { ended: Ended }) {
  const over = ended.update.view.phase === "over";
  return (
    <section className="now ending" aria-label="Your last game">
      <h2>{over ? "Game over" : "You left the game"}</h2>
      <p>{endingSentence(ended)}</p>
    </section>
  );
}

const ANSWERS: { answer: NoteAnswer["answer"]; label: string }[] = [
  { answer: "yes", label: "Yes" },
  { answer: "no", label: "No" },
  { answer: "declined", label: "Prefer not to say" },
];

export function Question({
  question,
  onAnswer,
}: {
  question: NoteQuestion;
  onAnswer: (answer: NoteAnswer["answer"]) => void;
}) {
  return (
    <section className="move" aria-label="One question">
      <h2>{question.text}</h2>
      <p className="quiet">Your answer is kept with this game. Any answer is fine.</p>
      <div className="actions">
        {ANSWERS.map(({ answer, label }) => (
          <button
            key={answer}
            type="button"
            onClick={() => {
              onAnswer(answer);
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}
