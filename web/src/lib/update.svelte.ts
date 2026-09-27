/**
 * Update discovery for a static deployment.
 *
 * A page served from a static host has no idea a new build exists: the tab keeps running the
 * JavaScript it loaded until somebody reloads it, and the host caches even the fresh files for
 * minutes. This finds out that a new build is live, and does the reloading — which is the closest a
 * static bundle gets to the dev server's hot reload, since there is no server in the loop to push a
 * change into a running page.
 *
 * Three things make it work rather than race:
 *
 * * the build publishes a `version.json` naming itself, so the page has something small and
 *   unambiguous to watch;
 * * every check is cache-busted and `no-store`, so a cached answer cannot hide a new build;
 * * repository fetches are stamped with the build this page booted as (`paths.withBuild`), so new
 *   code is never run against the previous build's cached data.
 *
 * It is deliberately off in development, where Vite already replaces modules in place, and it never
 * reloads while a render or a station is running — the app decides that, because only the app knows
 * what a reload would throw away.
 */
import { asset, reloadUrl, setBuild } from "./paths";

/** How often to ask. Short enough to feel immediate, long enough to be invisible. */
const POLL_MS = 10_000;
/** Remembers that this tab already reloaded for a build, so a stale answer cannot loop it. */
const GUARD_KEY = "mm.update.reloadedFor";

export const updateState = $state({
  /** The build this page is running. */
  current: "",
  /** The newest build the host has offered. */
  latest: "",
  ready: false,
  /** Shown while the page is about to reload itself. */
  notice: null as string | null,
});

let discovery: Promise<string> | null = null;
let watched = false;

/** One uncached read of the published build id. Empty means "could not tell", never "changed". */
async function fetchBuild(): Promise<string> {
  try {
    // A unique query defeats the host's cache for this one request; `no-store` keeps the browser
    // from storing the answer either.
    const response = await fetch(asset(`version.json?t=${Date.now()}`), { cache: "no-store" });
    if (!response.ok) return "";
    const data = (await response.json()) as { build?: unknown };
    return typeof data.build === "string" ? data.build : "";
  } catch {
    return "";
  }
}

/**
 * Learn and remember the build this page booted as. Called once, before anything reads the
 * repository, because every later repository fetch is stamped with what this returns.
 */
export function discoverBuild(): Promise<string> {
  if (!discovery) {
    discovery = fetchBuild().then((id) => {
      setBuild(id);
      updateState.current = id;
      updateState.latest = id;
      return id;
    });
  }
  return discovery;
}

/** Start watching for a newer build. Called once, after the app has booted. */
export function watchForUpdates(): void {
  if (import.meta.env.DEV || watched) return;
  watched = true;

  const check = async (): Promise<void> => {
    const latest = await fetchBuild();
    if (!latest) return;
    updateState.latest = latest;
    updateState.ready = Boolean(updateState.current) && latest !== updateState.current;
  };

  window.setInterval(() => void check(), POLL_MS);
  // A tab that has been in the background has almost certainly missed a deploy, and it is the
  // cheapest moment to act on one: the user is not watching.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void check();
  });
  window.addEventListener("focus", () => void check());
  void check();
}

/** Whether this tab already reloaded for a build and is somehow still being offered it. */
export function reloadedFor(build: string): boolean {
  try {
    return sessionStorage.getItem(GUARD_KEY) === build;
  } catch {
    return false;
  }
}

/** Reload into the new build. The guard survives the reload and stops a mismatch from looping. */
export function reloadNow(): void {
  try {
    sessionStorage.setItem(GUARD_KEY, updateState.latest);
  } catch {
    /* the guard is a safety net, not a requirement */
  }
  // A different URL, not `location.reload()`: the host has the document cached for minutes, so the
  // same URL could reload the build this is trying to leave. `replace` keeps the back button clean.
  window.location.replace(reloadUrl(window.location.href, updateState.latest));
}
