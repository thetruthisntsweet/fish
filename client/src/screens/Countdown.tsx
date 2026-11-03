// A timer counting down (R.2.6, R.8.5): from how long the server said it had left when the
// update was sent, ticking on this device's clock. Each update draws a new one (its key
// changes), so the count always starts from the server's latest figure.
import { useEffect, useState } from "react";

interface Props {
  /** Milliseconds left when the update arrived. */
  msLeft: number;
  label: string;
}

export function Countdown({ msLeft, label }: Props) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = performance.now();
    const tick = setInterval(() => {
      setElapsed(performance.now() - started);
    }, 250);
    return () => {
      clearInterval(tick);
    };
  }, []);
  const seconds = Math.ceil(Math.max(0, msLeft - elapsed) / 1000);
  return (
    <span className={seconds <= 10 ? "countdown low" : "countdown"} role="timer" aria-label={label}>
      {seconds}s
    </span>
  );
}
