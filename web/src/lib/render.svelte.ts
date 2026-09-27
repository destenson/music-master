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

export const renderQueue = $state({
  target: loadTarget() as ComfyTarget,
  probing: false,
  probeResult: null as Probe | null,
  busy: false,
  error: null as string | null,
  jobId: null as string | null,
  outcome: null as RenderOutcome | null,
  waited: 0,
  usedSeed: null as number | null,
  cancelRequested: false,
  /**
   * Off by default: every render is a new take, because the same seed with the same inputs reproduces
   * the same take rather than making another one.
   *
   * Turned on, the seed is held so the underlying arrangement stays put while everything else varies
   * — which is the only way to hear what a caption change actually did, rather than hearing it mixed
   * with whatever a different seed would have produced anyway.
   */
  keepSeed: false,
});

export function rememberTarget(): void {
  saveTarget(renderQueue.target);
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
  /** The seed to send when one is pinned rather than generated. */
  seed: number;
  /** Given the seed actually used, so the caller can show it and the take stays reproducible. */
  onSeed: (seed: number) => void;
  artifactsFor: (seed: number) => Artifacts | null;
}

export async function startRender({ seed, onSeed, artifactsFor }: StartOptions): Promise<void> {
  if (renderQueue.busy) return;

  const chosen = renderQueue.keepSeed ? seed : freshSeed();
  const built = artifactsFor(chosen);
  if (!built) return;
  if (!renderQueue.keepSeed) onSeed(chosen);

  renderQueue.usedSeed = chosen;
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
