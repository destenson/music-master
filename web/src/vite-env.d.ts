/// <reference types="svelte" />
/// <reference types="vite/client" />

/**
 * The build id, replaced at build time by `vite.config.ts`.
 *
 * It is compiled into the bundle on purpose: a page has to know which build *it* is, not which build
 * the host is currently serving. Asking the host makes a page the host served from its cache believe
 * it is already up to date, which is the one page that most needs to reload.
 */
declare const __BUILD_ID__: string;
