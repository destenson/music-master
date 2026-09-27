/**
 * Addresses for the page's own files, and the build they belong to.
 *
 * A static host caches everything for minutes at a time and has no way to push a change to a tab it
 * has already served, so two things go wrong without help: a page can refuse to see a new build, and
 * it can load new code against the previous build's cached repository data. Stamping every
 * repository fetch with the build the page booted as turns the second into a cache miss, and gives
 * `update.svelte.ts` a stable name for the first.
 *
 * Nothing here reads the repository, so it is importable from the smoke test under plain Node.
 */

let build = "";

/** The build this page is running. Set once at boot, before anything reads the repository. */
export function setBuild(id: string): void {
  build = id;
}

export function currentBuild(): string {
  return build;
}

/** A URL stamped with the running build, so a new build cannot be served an old cached file. */
export function withBuild(url: string): string {
  if (!build) return url;
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(build)}`;
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
