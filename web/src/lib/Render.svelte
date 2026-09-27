<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import { freshSeed, PRESETS, presetFor } from "./comfy";
  import { downloadText } from "./download";
  import { mmss } from "./format";
  import { checkTarget, rememberTarget, renderQueue, startRender } from "./render.svelte";
  import type { Artifacts } from "./types";

  let {
    artifact,
    seed = $bindable(),
    artifactsFor,
  }: {
    artifact: Artifacts | null;
    seed: number;
    /** Built on demand so a render can use a seed the displayed graph does not yet carry. */
    artifactsFor: (seed: number) => Artifacts | null;
  } = $props();

  const preset = $derived(presetFor(renderQueue.target.base));
  const pageOrigin = $derived(typeof window === "undefined" ? "" : window.location.origin);

  const promptSummary = $derived(
    artifact
      ? `sha256 ${artifact.prompt_sha256.slice(0, 12)}… · ${artifact.prompt.form.sections.length} sections · ${mmss(artifact.prompt.metadata.duration_s)}`
      : "waiting for the text tier",
  );

  const comfySummary = $derived(
    renderQueue.error
      ? `failed at ${renderQueue.target.base}`
      : renderQueue.outcome
        ? `${renderQueue.outcome.ok ? "succeeded" : renderQueue.outcome.status} · ${renderQueue.outcome.outputs.length} output(s)`
        : renderQueue.jobId
          ? `${renderQueue.jobId.slice(0, 8)}… · ${renderQueue.waited}s`
          : renderQueue.probeResult
            ? renderQueue.probeResult.ok
              ? `${renderQueue.target.base} · ready`
              : `${renderQueue.target.base} · ${renderQueue.probeResult.detail}`
            : renderQueue.target.base,
  );

  function choosePreset(id: string) {
    const chosen = PRESETS.find((entry) => entry.id === id);
    if (!chosen) return;
    renderQueue.target = { ...renderQueue.target, base: chosen.base, protocol: chosen.protocol };
    rememberTarget();
  }

  function render(fresh: boolean): void {
    void startRender({ seed, fresh, onSeed: (chosen) => (seed = chosen), artifactsFor });
  }
</script>

<div class="stack">
  <Collapsible title="Prompt &amp; graph" summary={promptSummary} storageKey="mm.panel.prompt" defaultOpen>
    {#if artifact}
      <div class="small">
        <div class="row">
          <span class="muted">prompt_sha256</span>
          <span class="mono">{artifact.prompt_sha256}</span>
        </div>
        <div class="row" style="margin-top:4px">
          <span class="muted">seed</span>
          <span class="mono">{artifact.prompt.seed}</span>
          <span class="muted">
            · key {artifact.prompt.metadata.key ?? "unset"} {artifact.prompt.metadata.mode ?? ""}
          </span>
          <span class="muted">· {artifact.prompt.style.rendered_tags.length} tags</span>
        </div>
        <div class="row" style="margin-top:4px">
          <span class="muted">excluded</span>
          <span>
            {artifact.prompt.negative.artist_references.length
              ? artifact.prompt.negative.artist_references.join(", ")
              : "nothing recorded"}
          </span>
        </div>
      </div>

      <div class="row">
        <button onclick={() => downloadText("prompt.json", artifact.prompt_text)}>
          download prompt.json
        </button>
        <button onclick={() => downloadText("workflow.json", artifact.workflow_text)}>
          download workflow.json
        </button>
        <button onclick={() => downloadText("composition.json", artifact.composition_text)}>
          download composition.json
        </button>
      </div>
      <p class="small muted" style="margin:0">
        These are the exact bytes the hashes are taken over. Drop them into
        <code>songs/&lt;id&gt;/</code> to make them the record — a page cannot write there itself.
      </p>
    {:else}
      <p class="small muted" style="margin:0">building…</p>
    {/if}
  </Collapsible>

  <Collapsible title="Renderer" summary={comfySummary} storageKey="mm.panel.comfy" defaultOpen>
    {#snippet badges()}
      {#if renderQueue.probeResult && !renderQueue.probeResult.ok && !renderQueue.outcome}
        <span class="chip warn">unreachable</span>
      {/if}
      {#if renderQueue.outcome?.ok}
        <span class="chip">{renderQueue.outcome.outputs.length} output(s)</span>
      {/if}
    {/snippet}

    <div class="row">
      <label class="row small">
        target
        <select
          value={preset?.id ?? "custom"}
          onchange={(event) => choosePreset(event.currentTarget.value)}
          disabled={renderQueue.busy}
        >
          {#each PRESETS as entry (entry.id)}
            <option value={entry.id}>{entry.label}</option>
          {/each}
        </select>
      </label>
      <label class="row small">
        address
        <input
          type="text"
          style="width:12rem"
          bind:value={renderQueue.target.base}
          onchange={rememberTarget}
          disabled={renderQueue.busy}
        />
      </label>
      <label class="row small">
        protocol
        <select bind:value={renderQueue.target.protocol} onchange={rememberTarget} disabled={renderQueue.busy}>
          <option value="native">native</option>
          <option value="v2">v2</option>
        </select>
      </label>
    </div>

    {#if renderQueue.target.protocol === "v2"}
      <label class="row small">
        API key
        <input
          type="password"
          style="width:16rem"
          placeholder="Bearer token — v2 surfaces only"
          bind:value={renderQueue.target.key}
          onchange={rememberTarget}
          disabled={renderQueue.busy}
        />
      </label>
      <p class="small muted" style="margin:0">
        A page cannot keep a secret, so this is held in this tab's session storage rather than saved,
        and it is gone when the tab closes. Comfy Cloud needs a paid subscription; the graph leaves
        this machine.
      </p>
    {/if}

    {#if preset?.note}
      <p class="small muted" style="margin:0">{preset.note}</p>
    {/if}

    <div class="row">
      <label class="row small">
        seed
        <!-- Disabled while the seed is not kept: it is then a record of the last take, not a control,
             and a field that silently ignores what you type is worse than one that says so. -->
        <input
          type="number"
          style="width:8rem"
          bind:value={seed}
          disabled={renderQueue.busy || !renderQueue.keepSeed}
          title={renderQueue.keepSeed ? "The seed every render will send" : "The seed of the last take"}
        />
      </label>
      <button
        onclick={() => (seed = freshSeed())}
        disabled={renderQueue.busy || !renderQueue.keepSeed}
      >
        new seed
      </button>
    </div>

    <div class="row">
      <button onclick={() => render(!renderQueue.keepSeed)} disabled={renderQueue.busy || !artifact}>
        {renderQueue.keepSeed ? `re-render seed ${seed}` : "render a new take"}
      </button>
      {#if renderQueue.busy}
        <button onclick={() => (renderQueue.cancelRequested = true)}>stop waiting</button>
      {/if}
      <label class="row small" title="Hold the seed so the arrangement stays put and you hear what the caption changed">
        <input type="checkbox" bind:checked={renderQueue.keepSeed} disabled={renderQueue.busy} />
        keep the seed
      </label>
      <button onclick={() => void checkTarget()} disabled={renderQueue.probing || renderQueue.busy}>
        check
      </button>
      <span class="small muted">
        {#if renderQueue.probing}checking…
        {:else if renderQueue.probeResult}
          <span class={renderQueue.probeResult.ok ? "" : "finding error"}>
            {renderQueue.probeResult.detail}
          </span>
        {/if}
      </span>
    </div>

    <p class="small muted" style="margin:0">
      {#if renderQueue.keepSeed}
        Holding seed {seed}: the arrangement stays put, so a caption change is the only thing that
        varies and you can hear what it did. Rendering twice with nothing changed reproduces the same
        take, down to the bytes.
      {:else}
        Each render generates a seed, so the arrangement varies too. Tick <em>keep the seed</em> to
        hold it — that is the setting for comparing captions rather than collecting takes.
      {/if}
    </p>

    {#if renderQueue.jobId}
      <div class="small row">
        <span class="muted">job</span>
        <span class="mono">{renderQueue.jobId}</span>
        <span class="muted">· seed {renderQueue.usedSeed}</span>
        {#if renderQueue.busy}<span class="muted">· waiting {renderQueue.waited}s</span>{/if}
      </div>
    {/if}

    {#if renderQueue.outcome}
      <div class="small">
        <div class="row">
          <span class="muted">seed</span>
          <span class="mono">{renderQueue.usedSeed}</span>
          <span class="muted">status</span>
          <span class={renderQueue.outcome.ok ? "" : "finding error"}>{renderQueue.outcome.status}</span>
        </div>
        {#each renderQueue.outcome.outputs as output, i (i)}
          <div class="row mono">{output.name}</div>
        {/each}
        {#if !renderQueue.outcome.outputs.length}
          <p class="small muted" style="margin:4px 0 0">
            No files reported. The render may have written elsewhere — check the service's own output
            directory.
          </p>
        {/if}
        {#each renderQueue.outcome.messages as message, i (i)}
          <div class="finding {message.kind === "error" ? "error" : "note"}">{message.text}</div>
        {/each}
      </div>
    {/if}

    {#if renderQueue.error}
      <pre class="finding error" style="white-space:pre-wrap; margin:0">{renderQueue.error}</pre>
      {#if !renderQueue.probeResult?.ok}
        <div class="small">
          <p style="margin:0">
            Nothing answered at <code>{renderQueue.target.base}</code>. A page on another origin is
            refused unless the service allows it:
          </p>
          {#if renderQueue.target.protocol === "v2"}
            <p class="muted" style="margin:6px 0 0">
              Check the address and the key. A v2 surface answers <code>401</code> for a missing or
              invalid key, and <code>429</code> when the subscription is inactive or the queue is
              full.
            </p>
          {:else}
            <p style="margin:0">
              If it is running on your own machine, note that ComfyUI refuses a POST to a loopback
              address whose <code>Origin</code> does not match its <code>Host</code> — its guard
              against a random site queueing renders through <code>127.0.0.1</code>. The dev server
              proxies <code>:8288</code> and <code>:8188</code> so that does not arise; a page served
              from elsewhere has to reach ComfyUI at a non-loopback address, with the header below.
            </p>
            <pre class="brief">python main.py --enable-cors-header {pageOrigin}</pre>
          {/if}
          <p class="muted" style="margin:6px 0 0">
            The render path does not need any of it: the graph above is built here, in the page, and
            can be downloaded and run by hand.
          </p>
        </div>
      {/if}
    {:else}
      <p class="small muted" style="margin:0">
        The dev server proxies ports 8288 and 8188 on loopback, so a local render needs nothing
        special. Anything else — including Comfy Cloud — is called directly and must allow this page.
      </p>
    {/if}
  </Collapsible>
</div>
