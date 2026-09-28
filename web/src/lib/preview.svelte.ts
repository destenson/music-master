/**
 * The preview queue.
 *
 * It lives outside any panel because a preview can be started from three places: the top-bar
 * control, its bin/option selects, and the small A/B button that appears beside a checkbox. One
 * queue means one take in flight, one set of clips, and one place the results land — which is also
 * why the per-option button does not need a panel of its own.
 *
 * Every caption is rendered as its own solo graph and cached by that graph, so an A/B renders the
 * variant and reuses the A that is already there. The base row of an A/B is the same graph as a
 * plain preview of the caption, so holding it costs nothing and the two can never disagree.
 *
 * Runes in a module are Svelte 5's way of holding state that outlives the component that shows it.
 *
 * Nothing is written to the render output directory: the graph ends in PreviewAudio, which writes
 * to ComfyUI's temp directory, and the page plays it from there.
 */
import { fetchOutcome, submitWorkflow } from "./comfy";
import { renderQueue } from "./render.svelte";
import { splitStereo } from "./stereo";
import type { PreviewRow } from "./types";

export interface PreviewVariant {
  bin: string;
  option: string;
}

/** One caption as the panel shows it: playable once `url` is set. */
export interface PreviewClip {
  name: string;
  caption: string;
  /** ComfyUI's temp URL, or null while the row is still rendering. */
  url: string | null;
  /** True when the clip came from the cache rather than a submission this time. */
  cached: boolean;
}

export interface BuiltPreview {
  rows: PreviewRow[];
}

/**
 * The page's one builder, registered by the app. It closes over the current selections, so a
 * per-option button and the top-bar panel cannot preview two different states.
 */
export type PreviewBuilder = (steps: number, variants: PreviewVariant[]) => BuiltPreview | null;

let builder: PreviewBuilder | null = null;

export function setPreviewBuilder(fn: PreviewBuilder | null): void {
  builder = fn;
}

/**
 * Rendered clips, keyed by the graph that produced them and the service it was rendered on.
 *
 * The graph fixes the caption, the lyrics, the seed, the steps and the length, so an identical
 * graph is the same take and the clip can be reused. The target is part of the key because another
 * service may hold different weights. It lives for the session: the audio itself is in ComfyUI's
 * temp directory, and the renderer may clean that up.
 */
const CACHE_LIMIT = 32;
const cache = new Map<string, PreviewClip>();

/** When the running preview started, so the wait it shows spans every row rather than resetting. */
let beganAt = 0;

function cacheKey(row: PreviewRow): string {
  return `${renderQueue.target.base}\n${JSON.stringify(row.workflow)}`;
}

function remember(row: PreviewRow, url: string): void {
  cache.set(cacheKey(row), { name: row.name, caption: row.caption, url, cached: false });
  if (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
}

/**
 * Forget a clip whose temp file the renderer has cleaned up. The URL, not the graph, is what the
 * player knows about, so a failed load drops every entry that points at it and the next preview of
 * that caption renders it again rather than replaying a dead link.
 */
export function forgetClip(url: string): void {
  for (const [key, clip] of cache) {
    if (clip.url === url) cache.delete(key);
  }
  // The merged track was built from that clip, so it points at the same dead link.
  if (splitState.built.includes(url)) dropSplit();
}

/**
 * The simultaneous A/B: one stereo track with the current caption on the left and the variant on
 * the right, both downmixed to mono first. It is built from the two clips the panel already has, so
 * it costs no render — only a fetch, a decode and a WAV encode in the page.
 */
export const splitState = $state({
  /** Whether the mode is on. It is a preference, so it stays on across previews in a session. */
  on: false,
  busy: false,
  error: null as string | null,
  url: null as string | null,
  /** The two clip URLs the track was built from, so it is rebuilt when either changes. */
  built: [] as string[],
});

let splitToken = 0;

/**
 * Build the merged track, or drop it, to match the mode and the clips that are ready.
 *
 * Called when the mode is toggled and whenever a clip lands, rather than from an effect: the work is
 * async and cancellable, and a stale build has to lose to the newer one instead of overwriting it.
 */
export async function refreshSplit(): Promise<void> {
  const ready = previewState.clips.filter((clip) => clip.url);
  if (!splitState.on || ready.length !== 2) {
    dropSplit();
    return;
  }
  const [a, b] = ready;
  if (splitState.url && splitState.built[0] === a.url && splitState.built[1] === b.url) return;

  const token = ++splitToken;
  splitState.busy = true;
  splitState.error = null;
  try {
    const url = await splitStereo(a.url as string, b.url as string);
    if (token !== splitToken) {
      URL.revokeObjectURL(url);
      return;
    }
    releaseSplit();
    splitState.url = url;
    splitState.built = [a.url as string, b.url as string];
  } catch (cause) {
    if (token === splitToken) {
      splitState.error = cause instanceof Error ? cause.message : String(cause);
    }
  } finally {
    if (token === splitToken) splitState.busy = false;
  }
}

/** Drop the merged track. An in-flight build is invalidated so it cannot land after this. */
export function dropSplit(): void {
  splitToken++;
  releaseSplit();
  splitState.busy = false;
  splitState.error = null;
}

function releaseSplit(): void {
  if (splitState.url) URL.revokeObjectURL(splitState.url);
  splitState.url = null;
  splitState.built = [];
}

export const previewState = $state({
  open: false,
  steps: 2,
  /** The top-bar panel's own A/B choice; the per-option buttons do not touch it. */
  binId: "",
  optionId: "",
  busy: false,
  error: null as string | null,
  waited: 0,
  cancelRequested: false,
  clips: [] as PreviewClip[],
});

/**
 * Build and render a preview. With no `variant` it is the current caption alone; with one it is an
 * A/B of that tag — toggled on if it is off, off if it is on. A row already rendered for the same
 * graph and target is reused rather than sent again, so the A of an A/B is rendered once.
 *
 * The panel is opened on every start, because a preview begun from a checkbox has no panel open and
 * the clips have to land somewhere the user can reach.
 */
export async function startPreview(variant?: PreviewVariant): Promise<void> {
  if (previewState.busy) return;
  if (!builder) {
    previewState.open = true;
    previewState.error = "the text tier is not ready";
    return;
  }

  const built = builder(previewState.steps, variant ? [variant] : []);
  if (!built || !built.rows.length) {
    previewState.open = true;
    previewState.error = "the text tier is not ready";
    return;
  }

  previewState.open = true;
  previewState.busy = true;
  previewState.cancelRequested = false;
  previewState.error = null;
  previewState.waited = 0;
  beganAt = Date.now();
  // A cached row shows at once; the rest show as still rendering while their submissions run.
  previewState.clips = built.rows.map((row) => {
    const hit = cache.get(cacheKey(row));
    return hit
      ? { name: row.name, caption: row.caption, url: hit.url, cached: true }
      : { name: row.name, caption: row.caption, url: null, cached: false };
  });
  void refreshSplit();

  try {
    for (const [index, row] of built.rows.entries()) {
      const clip = previewState.clips[index];
      if (clip.url || previewState.cancelRequested) continue;
      await renderRow(row, clip);
      // An A/B can be merged as soon as its second clip lands, not only when both were cached.
      void refreshSplit();
    }
  } catch (cause) {
    previewState.error = cause instanceof Error ? cause.message : String(cause);
  } finally {
    previewState.busy = false;
  }
}

/** Submit one solo row and poll it, landing the clip on `clip` and in the cache. */
async function renderRow(row: PreviewRow, clip: PreviewClip): Promise<void> {
  const started = await submitWorkflow(renderQueue.target, row.workflow);
  while (!previewState.cancelRequested) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    // The whole preview's clock, not this row's: an A/B renders two rows and the wait is the pair.
    previewState.waited = Math.round((Date.now() - beganAt) / 1000);
    const state = await fetchOutcome(renderQueue.target, started.pollUrl);
    if (!state.done) {
      if (previewState.waited > 600) throw new Error("gave up waiting after 10 minutes");
      continue;
    }
    if (!state.ok) throw new Error(`the preview ${state.status}`);
    const output = state.outputs.find((entry) => entry.url);
    if (!output?.url) throw new Error("the preview finished but reported no playable audio");
    clip.url = output.url;
    clip.cached = false;
    remember(row, output.url);
    return;
  }
}
