// The website (T3.3): the front page with the consent screen (screens/Home.tsx), "Study
// information" and the account page, with the footer that links them (Consent Screen §2).
// Signed in, the front page is the game (screens/Play.tsx). The client holds no rules logic of
// its own (Plan §3): it shows what the server sends and offers what the server allows.
import { useEffect, useState } from "react";
import { AccountPage } from "./screens/AccountPage.tsx";
import { Home } from "./screens/Home.tsx";
import { InformationPage } from "./screens/InformationPage.tsx";
import { Link } from "./screens/Link.tsx";
import { Problem } from "./screens/Messages.tsx";
import { loadSite, type Loading } from "./site.ts";

export default function App() {
  const [loading, setLoading] = useState<Loading>({ kind: "loading" });
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    let showing = true;
    void loadSite().then((next) => {
      if (showing) {
        setLoading(next);
      }
    });
    const moved = () => {
      setPath(window.location.pathname);
    };
    window.addEventListener("popstate", moved);
    return () => {
      showing = false;
      window.removeEventListener("popstate", moved);
    };
  }, []);

  /** Ask the server again after something changed there, keeping the page as it is. */
  function refresh() {
    void loadSite().then(setLoading);
  }

  function page() {
    switch (loading.kind) {
      case "loading":
        return <p className="quiet">Loading…</p>;
      case "problem":
        return (
          <Problem
            message={loading.message}
            onRetry={() => {
              if (loading.reload) {
                window.location.reload();
              } else {
                setLoading({ kind: "loading" });
                refresh();
              }
            }}
          />
        );
      case "ready":
        switch (path) {
          case "/information":
            return <InformationPage site={loading.site} />;
          case "/account":
            return <AccountPage site={loading.site} onChange={refresh} />;
          default:
            // A new standing starts the front page afresh.
            return (
              <Home
                key={JSON.stringify(loading.site.standing)}
                site={loading.site}
                onChange={refresh}
              />
            );
        }
    }
  }

  const signedIn = loading.kind === "ready" && loading.site.standing !== null;
  return (
    <div className="site">
      <main>{page()}</main>
      <footer className="footer">
        <Link to="/">Fish</Link>
        <Link to="/information">Study information</Link>
        {signedIn && <Link to="/account">Your account</Link>}
      </footer>
    </div>
  );
}
