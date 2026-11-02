// After Continue: the email field, which sends the sign-in link (Consent Screen §2.5).
import { useState, type SyntheticEvent } from "react";

interface Props {
  /** The address to start with, when coming back to send again. */
  initial: string;
  /** Called with the address; resolves to a message to show, or null once the link is sent. */
  onSend: (email: string) => Promise<string | null>;
}

export function EmailScreen({ initial, onSend }: Props) {
  const [email, setEmail] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(event: SyntheticEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    const message = await onSend(email.trim());
    setBusy(false);
    setProblem(message);
  }

  return (
    <section className="panel">
      <h1>Your email address</h1>
      <p>We will email you a link to sign in with. There is no password.</p>
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label className="field">
          <span>Email address</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            autoFocus
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </label>
        {problem !== null && (
          <p className="problem" role="alert">
            {problem}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>
            Send sign-in link
          </button>
        </div>
      </form>
    </section>
  );
}
