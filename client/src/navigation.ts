// Moving between the site's pages without reloading. The server answers each of them with
// the client (fish_server.pages.PAGES), so an address typed or bookmarked works too.

/** Every page the client has; the same as fish_server.pages.PAGES. */
export const PAGES = ["/", "/account", "/information", "/terms", "/privacy"] as const;

/** Go to ``to``, as a link would, and start at the top of the page. */
export function go(to: string): void {
  if (to !== window.location.pathname) {
    window.history.pushState(null, "", to);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}
