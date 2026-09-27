/**
 * The preview queue.
 *
 * It lives outside any panel because a preview can be started from three places: the top-bar
 * control, its bin/option selects, and the small A/B button that appears beside a checkbox. One
 * queue means one take in flight, one set of clips, and one place the results land — which is also
 * why the per-option button does not need a panel of its own.
 *
 * Runes in a module are Svelte 5's way of holding state that outlives the component that shows it.
 *
 * Nothing is written to the render output directory: the graph ends in PreviewAudio, which writes
 * to ComfyUI's temp directory, and the page plays it from there.
 */
import { fetchOutcome, submitWorkflow } from "./comfy";
import { renderQueue } from "./render.svelte";

export interface PreviewVariant {
  bin: string;
  option: string;
}

export interface PreviewClip {
  name: string;
  caption: string;
  url: string;
}

export interface BuiltPreview {
  workflow: unknown;
  captions: string[];
  names: string[];
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
 * A/B of that tag — toggled on if it is off, off if it is on — in the same batched pass.
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
  if (!built) {
    previewState.open = true;
    previewState.error = "the text tier is not ready";
    return;
  }

  previewState.open = true;
  previewState.busy = true;
  previewState.cancelRequested = false;
  previewState.error = null;
  previewState.clips = [];
  previewState.waited = 0;

  try {
    const started = await submitWorkflow(renderQueue.target, built.workflow);
    const began = Date.now();
    while (!previewState.cancelRequested) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      previewState.waited = Math.round((Date.now() - began) / 1000);
      const state = await fetchOutcome(renderQueue.target, started.pollUrl);
      if (state.done) {
        if (!state.ok) {
          previewState.error = `the preview ${state.status}`;
          break;
        }
        previewState.clips = state.outputs
          .map((output, index) => ({
            name: built.names[index] ?? output.name,
            caption: built.captions[index] ?? "",
            url: output.url ?? "",
          }))
          .filter((clip) => clip.url);
        if (!previewState.clips.length) {
          previewState.error = "the preview finished but reported no playable audio";
        }
        break;
      }
      if (previewState.waited > 600) {
        previewState.error = "gave up waiting after 10 minutes";
        break;
      }
    }
  } catch (cause) {
    previewState.error = cause instanceof Error ? cause.message : String(cause);
  } finally {
    previewState.busy = false;
  }
}
