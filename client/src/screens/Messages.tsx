// The short screens around the consent screen: the link sent, No thanks, withdrawn, and
// something gone wrong.
import { LINK_MINUTES } from "../api.ts";

export function LinkSent({ email, onAgain }: { email: string; onAgain: () => void }) {
  return (
    <section className="panel">
      <h1>Check your email</h1>
      <p>
        We sent a sign-in link to <strong>{email}</strong>. It works once, within {LINK_MINUTES}{" "}
        minutes. Open it on this device or any other.
      </p>
      <p className="quiet">Nothing there? Look in your spam folder, or send it again.</p>
      <div className="actions">
        <button type="button" onClick={onAgain}>
          Send again or use another address
        </button>
      </div>
    </section>
  );
}

export function Declined({ onReread }: { onReread: () => void }) {
  return (
    <section className="panel">
      <h1>Thank you</h1>
      <p>You have not joined the study, and nothing about you has been stored.</p>
      <div className="actions">
        <button type="button" onClick={onReread}>
          Read the study information again
        </button>
      </div>
    </section>
  );
}

export function Withdrawn() {
  return (
    <section className="panel">
      <h1>You have withdrawn from the study</h1>
      <p>You cannot play again. Thank you for taking part.</p>
    </section>
  );
}

export function Problem({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="panel">
      <h1>Something went wrong</h1>
      <p role="alert">{message}</p>
      <div className="actions">
        <button type="button" className="primary" onClick={onRetry}>
          Try again
        </button>
      </div>
    </section>
  );
}
