/**
 * Update discovery for a static deployment.
 *
 * A page served from a static host has no idea a new build exists: the tab keeps running the
 * JavaScript it loaded until somebody reloads it, and the host serves even a fresh page from its
 * cache for minutes. This finds out, and does the reloading — the closest a static bundle gets to
 * the dev server's hot reload, since there is no server in the loop to push a change into a page.
 *
 * What makes it work is that the page knows **its own** build id, because it was compiled into the
 * bundle (`paths.currentBuild`). The tempting alternative — ask the host what build is deployed and
 * call that "current" — cannot ever detect a stale page: a page the host served from its cache runs
 * old code, asks the host, is told the new id, and concludes it is up to date. Comparing a compiled
 * id against the published one is what lets a cached page notice, within a second of loading, that
 * it is not the build being served.
 *
 * Everything else supports that: `version.json` names the deployed build and every check is
 * cache-busted and `no-store`, so a cached answer cannot hide a new build; and repository fetches
 * are stamped with the compiled build, so new code is never run against the previous build's data.
 *
 * It is deliberately off in development, where Vite already replaces modules in place.
 */
import { asset, currentBuild, reloadUrl } from "./paths";

/** How often to ask. Short enough to feel immediate, long enough to be invisible. */
const POLL_MS = 10_000;
/** Remembers that this tab already reloaded for a build, so a stale answer cannot loop it. */
const GUARD_KEY = "mm.update.reloadedFor";
/**
 * How long a reload is trusted. A page that landed on a document the host had not replaced yet would
 * otherwise be wedged: it would see the new build, refuse to reload again for it, and never arrive.
 * Expiring the guard lets it try again, while still being far too slow to become a loop.
 */
const GUARD_MS = 30_000;

export const updateState = $state({
  /** The build this page is running, compiled in — never learned from the host. */
  current: currentBuild(),
  /** The newest build the host has offered. */
  latest: "",
  ready: false,
  /** Shown while the page is about to reload itself. */
  notice: null as string | null,
});

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
 * Start watching for a build other than this one.
 *
 * Called at boot, before anything is loaded: a page the host served from its cache is already
 * superseded, and the sooner it says so the less it does before reloading.
 */
export function watchForUpdates(): void {
  if (import.meta.env.DEV || watched) return;
  watched = true;

  const check = async (): Promise<void> => {
    const latest = await fetchBuild();
    if (!latest) return;
    updateState.latest = latest;
    updateState.ready = latest !== updateState.current;
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

/** Whether this tab reloaded for this build recently, and is somehow still being offered it. */
export function reloadedFor(build: string): boolean {
  try {
    const raw = sessionStorage.getItem(GUARD_KEY);
    if (!raw) return false;
    const guard = JSON.parse(raw) as { build?: string; at?: number };
    return guard.build === build && Date.now() - (guard.at ?? 0) < GUARD_MS;
  } catch {
    return false;
  }
}

/** Reload into the new build. The guard survives the reload and stops a mismatch from looping. */
export function reloadNow(): void {
  try {
    sessionStorage.setItem(
      GUARD_KEY,
      JSON.stringify({ build: updateState.latest, at: Date.now() }),
    );
  } catch {
    /* the guard is a safety net, not a requirement */
  }
  // A different URL, not `location.reload()`: the host has the document cached for minutes, so the
  // same URL could reload the build this is trying to leave. `replace` keeps the back button clean.
  window.location.replace(reloadUrl(window.location.href, updateState.latest));
}
