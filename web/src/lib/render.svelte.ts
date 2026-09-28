/**
 * The render queue.
 *
 * It lives outside any panel because a render can be started from anywhere: the top bar has a quick
 * render button, the Render tab has the full controls, and both drive this one queue. Two would mean
 * two takes in flight and two different meanings of "busy".
 *
 * Runes in a module are Svelte 5's way of holding state that outlives the component that shows it.
 */
import {
  fetchOutcome,
  freshSeed,
  loadTarget,
  probe as probeService,
  saveTarget,
  submitWorkflow,
  type ComfyTarget,
  type Probe,
  type RenderOutcome,
} from "./comfy";
import type { Artifacts } from "./types";

/**
 * The seed of the last take, remembered across reloads.
 *
 * It is what a preview and an A/B hold, so the take a preview explains survives a page reload even
 * though the queue itself does not. A reload otherwise restores the seed from the draft, which a
 * hand-typed seed would have overwritten without ever producing a take.
 */
const USED_SEED_KEY = "mm.render.seed";

function loadUsedSeed(): number | null {
  try {
    const raw = localStorage.getItem(USED_SEED_KEY);
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

function saveUsedSeed(seed: number | null): void {
  try {
    if (seed === null) localStorage.removeItem(USED_SEED_KEY);
    else localStorage.setItem(USED_SEED_KEY, String(seed));
  } catch {
    /* not remembering is an acceptable outcome */
  }
}

export const renderQueue = $state({
  target: loadTarget() as ComfyTarget,
  probing: false,
  probeResult: null as Probe | null,
  busy: false,
  error: null as string | null,
  jobId: null as string | null,
  outcome: null as RenderOutcome | null,
  waited: 0,
  /** The seed the last renderer submission carried, and so the arrangement a preview holds. */
  usedSeed: loadUsedSeed() as number | null,
  cancelRequested: false,
  /**
   * The Render panel's preference for its own button, and nothing else's: the top bar carries both
   * actions as two explicit buttons, so neither of them consults this.
   *
   * On: hold the seed, so the arrangement stays put while everything else varies — the only way to
   * hear what a caption change actually did. Off: every render is a new take. The same seed with the
   * same inputs reproduces the same take, so holding it is a deliberate act rather than a default.
   */
  keepSeed: false,
});

export function rememberTarget(): void {
  saveTarget(renderQueue.target);
}

/**
 * A new song has no take yet, so there is no previous seed to hold: forget the last one rather than
 * let a preview of the blank song render the arrangement of the song before it.
 */
export function forgetUsedSeed(): void {
  renderQueue.usedSeed = null;
  saveUsedSeed(null);
}

/** Whether anything is listening, and whether it will take this key. */
export async function checkTarget(): Promise<void> {
  renderQueue.probing = true;
  try {
    renderQueue.probeResult = await probeService(renderQueue.target);
  } catch (cause) {
    renderQueue.probeResult = {
      ok: false,
      detail: cause instanceof Error ? cause.message : String(cause),
    };
  } finally {
    renderQueue.probing = false;
  }
}

export interface StartOptions {
  /** The seed to re-send when reproducing a take. */
  seed: number;
  /**
   * True for a new take, false to re-send `seed`.
   *
   * A parameter rather than a stored mode, so the two buttons in the top bar are independent of the
   * panel's checkbox. A global button whose meaning depended on a checkbox in a panel you might not
   * have open is what made this confusing in the first place.
   */
  fresh: boolean;
  /** Given the seed actually used, so the caller can show it and the take stays reproducible. */
  onSeed: (seed: number) => void;
  artifactsFor: (seed: number) => Artifacts | null;
}

export async function startRender({ seed, fresh, onSeed, artifactsFor }: StartOptions): Promise<void> {
  if (renderQueue.busy) return;

  const chosen = fresh ? freshSeed() : seed;
  const built = artifactsFor(chosen);
  if (!built) return;
  if (fresh) onSeed(chosen);

  renderQueue.usedSeed = chosen;
  saveUsedSeed(chosen);
  renderQueue.busy = true;
  renderQueue.cancelRequested = false;
  renderQueue.error = null;
  renderQueue.outcome = null;
  renderQueue.jobId = null;
  renderQueue.waited = 0;

  try {
    const started = await submitWorkflow(renderQueue.target, built.workflow);
    renderQueue.jobId = started.jobId;
    const began = Date.now();
    // Poll rather than guess: a surface answers only once it has recorded the render.
    while (!renderQueue.cancelRequested) {
      await new Promise((resolve) => setTimeout(resolve, 4000));
      renderQueue.waited = Math.round((Date.now() - began) / 1000);
      const state = await fetchOutcome(renderQueue.target, started.pollUrl);
      if (state.done) {
        renderQueue.outcome = state;
        break;
      }
      if (renderQueue.waited > 900) {
        renderQueue.error = "gave up waiting after 15 minutes; it may still be rendering";
        break;
      }
    }
  } catch (cause) {
    renderQueue.error = cause instanceof Error ? cause.message : String(cause);
  } finally {
    renderQueue.busy = false;
  }
}
