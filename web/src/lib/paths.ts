/**
 * Addresses for the page's own files, and the build this page is running.
 *
 * The build id is compiled into the bundle rather than fetched. That is the whole point: a page has
 * to know which build *it* is, and asking the host which build is deployed tells a page served from
 * the host's cache that it is already current — which is exactly the page that most needs to reload.
 * `update.svelte.ts` compares this with the published `version.json`; every repository fetch is
 * stamped with it, so a new build cannot be handed the previous build's cached data.
 *
 * Nothing here reads the repository, so it is importable from the smoke test under plain Node.
 */

// `typeof` rather than a bare read: under plain Node the build-time constant does not exist, and
// this stays importable there rather than throwing on load.
const build = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "";

/** The build this page is running, as compiled into it. */
export function currentBuild(): string {
  return build;
}

/** Stamp a URL with a build id, so a new build is a cache miss rather than a stale hit. */
export function stamp(url: string, build: string): string {
  if (!build) return url;
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(build)}`;
}

/** The same, for the build this page is running. */
export function withBuild(url: string): string {
  return stamp(url, build);
}

/**
 * The URL to reload the document through, past the host's cache.
 *
 * `location.reload()` re-requests the same URL, which the host has cached for minutes, so it can
 * hand back the document it is trying to replace. A different URL cannot come from the cache — and a
 * static host ignores the query and serves the same document — so a new value in it is a reload that
 * actually arrives.
 */
export function reloadUrl(href: string, build: string): string {
  const url = new URL(href);
  url.searchParams.set("u", build || String(Date.now()));
  return url.toString();
}

/**
 * Resolve a repository or runtime path against the page, not against this module.
 *
 * `import.meta.env.BASE_URL` is relative ("/") in dev but "./" in a build, and a relative specifier
 * inside a module is resolved against *that module's* URL — so `import("./pyodide/pyodide.mjs")`
 * from `/assets/index-*.js` looks in `/assets/pyodide/`, which is a 404. Resolving against
 * `document.baseURI` gives one absolute URL that is right in dev, at a domain root, and under a
 * subpath alike.
 */
export function asset(path: string): string {
  return new URL(path, document.baseURI).href;
}
