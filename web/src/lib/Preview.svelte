<script lang="ts">
  import { forgetClip, previewState, startPreview } from "./preview.svelte";
  import type { Bin } from "./types";

  /**
   * Preview mode: hear the arrangement, coarsely, without committing to a render.
   *
   * It runs the full song length and cuts the sampler steps instead. A short clip is not the
   * opening of the real render -- the model arranges to fit whatever length it is handed -- so only
   * a full-length pass shows what a tag does to the actual arrangement. Two steps tracks the
   * eight-step render closely.
   *
   * Every caption is its own solo graph, and a graph already rendered is reused, so the A of an
   * A/B is rendered once rather than with every tag it is compared against. A batch would share one
   * language-model pass, but the batch node keeps one generator for the whole batch, so a caption's
   * audio depends on what rode along with it -- and a row that cannot be reproduced on its own is a
   * row that cannot be cached.
   *
   * The control sits in the top bar beside the render actions, so it is reachable from every tab.
   * The work itself is the shared queue in `preview.svelte.ts`, because the per-checkbox A/B button
   * in the Builder starts the same preview and shows its clips here.
   *
   * Every preview holds the seed of the last take, so it is a comparison against audio that exists.
   * A render's fresh seed only reaches a preview once a take has been rendered with it; the panel
   * shows the seed it is holding rather than leaving that rule invisible.
   */
  let { bins, ready, seed }: { bins: Bin[]; ready: boolean; seed: number } = $props();

  let menu = $state<HTMLElement | null>(null);

  const bin = $derived(bins.find((entry) => entry.id === previewState.binId) ?? null);
  const options = $derived(bin?.options ?? []);
  const label = $derived(
    previewState.busy
      ? `previewing ${previewState.waited}s`
      : previewState.clips.length
        ? `${previewState.clips.length} preview clip${previewState.clips.length === 1 ? "" : "s"}`
        : "preview",
  );

  /** A click anywhere else closes the panel; the button and the panel itself are the exceptions. */
  $effect(() => {
    const outside = (event: MouseEvent) => {
      if (!previewState.open) return;
      const target = event.target as Node | null;
      if (menu && target && menu.contains(target)) return;
      previewState.open = false;
    };
    // Capture, not bubble: a per-checkbox A/B button is outside this panel, and its own handler has
    // to run after this one so the panel it opened is not closed by the click that opened it.
    document.addEventListener("click", outside, true);
    return () => document.removeEventListener("click", outside, true);
  });
</script>

<svelte:window onkeydown={(event) => event.key === "Escape" && (previewState.open = false)} />

<div class="preview-menu" bind:this={menu}>
  <button
    class:active={previewState.open}
    onclick={() => (previewState.open = !previewState.open)}
    disabled={!ready}
    aria-expanded={previewState.open}
    title="Hear the whole song, coarsely, from ComfyUI's temp directory: the real arrangement at a couple of sampler steps, never saved to output."
  >
    {label}
  </button>

  {#if previewState.open}
    <div class="popover">
      <div class="row" style="justify-content:space-between">
        <strong>Preview</strong>
        <button class="small" onclick={() => (previewState.open = false)}>close</button>
      </div>

      <p class="small muted" style="margin:0">
        The whole song at seed <span class="mono">{seed}</span> and {previewState.steps} sampler
        step{previewState.steps === 1 ? "" : "s"} — the real arrangement, coarsely denoised, so it is
        quick and it is not the final audio. Nothing is saved: it plays from ComfyUI's temp directory
        and is cleaned up there.
      </p>

      <div class="row">
        <label class="row small">
          steps
          <input
            type="number"
            min="1"
            max="8"
            style="width:4rem"
            bind:value={previewState.steps}
            disabled={previewState.busy}
          />
        </label>
        <button onclick={() => startPreview()} disabled={previewState.busy}>preview the caption</button>
        {#if previewState.busy}
          <button onclick={() => (previewState.cancelRequested = true)}>stop waiting</button>
        {/if}
      </div>

      <div class="row">
        <label class="row small">
          compare with
          <select bind:value={previewState.binId} disabled={previewState.busy}>
            <option value="">a tag…</option>
            {#each bins as entry (entry.id)}
              {#if entry.emits_tag !== false}
                <option value={entry.id}>{entry.label}</option>
              {/if}
            {/each}
          </select>
          <select bind:value={previewState.optionId} disabled={previewState.busy || !bin}>
            <option value="">an option…</option>
            {#each options as option (option.id)}
              <option value={option.id}>{option.label}</option>
            {/each}
          </select>
        </label>
        <button
          onclick={() =>
            startPreview({ bin: previewState.binId, option: previewState.optionId })}
          disabled={previewState.busy || !previewState.binId || !previewState.optionId}
        >
          A/B the tag
        </button>
      </div>

      <p class="small muted" style="margin:0">
        A/B toggles the option — on if it is off, off if it is on — and renders the variant beside
        the current caption, sharing seed <span class="mono">{seed}</span>, so what differs is the
        tag. The current caption is rendered once and reused; a clip already rendered says
        <em>cached</em>. The same button sits beside every checkbox in the Builder.
      </p>

      {#if previewState.error}
        <div class="finding error">{previewState.error}</div>
      {/if}

      {#each previewState.clips as clip, i (i)}
        <div class="preview-clip">
          <div class="small">
            <span class="mono">{clip.name}</span>
            {#if clip.cached}
              <span class="chip" title="Already rendered for this caption, seed and target">cached</span>
            {/if}
          </div>
          {#if clip.url}
            <audio
              controls
              src={clip.url}
              preload="auto"
              onerror={() => clip.url && forgetClip(clip.url)}
            ></audio>
          {:else}
            <div class="small muted">rendering… {previewState.waited}s</div>
          {/if}
          <details>
            <summary class="small muted">caption</summary>
            <code>{clip.caption}</code>
          </details>
        </div>
      {/each}

      {#if previewState.clips.length > 1}
        <p class="small muted" style="margin:0">
          Play them back to back: the rows share seed <span class="mono">{seed}</span>, so what
          differs is the tag.
        </p>
      {/if}
    </div>
  {/if}
</div>
