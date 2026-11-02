// Runs before every test file: adds DOM matchers such as toBeInTheDocument().
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom does not scroll; pages ask to start at the top when moving between them.
window.scrollTo = () => undefined;

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});
