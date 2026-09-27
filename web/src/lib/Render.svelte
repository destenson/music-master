<script lang="ts">
  import { untrack } from "svelte";
  import Collapsible from "./Collapsible.svelte";
  import {
    fetchOutcome,
    loadTarget,
    PRESETS,
    probe,
    presetFor,
    saveTarget,
    submitWorkflow,
    type ComfyTarget,
    type Probe,
    type RenderOutcome,
  } from "./comfy";
  import { downloadText } from "./download";
  import { mmss } from "./format";
  import type { Artifacts } from "./types";

  let { artifact }: { artifact: Artifacts | null } = $props();

  let target = $state<ComfyTarget>(loadTarget());
  let probing = $state(false);
  let probeResult = $state<Probe | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let jobId = $state<string | null>(null);
  let outcome = $state<RenderOutcome | null>(null);
  let waited = $state(0);
  let stop = false;

  const preset = $derived(presetFor(target.base));
  const pageOrigin = $derived(typeof window === "undefined" ? "" : window.location.origin);

  const promptSummary = $derived(
    artifact
      ? `sha256 ${artifact.prompt_sha256.slice(0, 12)}… · ${artifact.prompt.form.sections.length} sections · ${mmss(artifact.prompt.metadata.duration_s)}`
      : "waiting for the text tier",
  );

  const comfySummary = $derived(
    error
      ? `failed at ${target.base}`
      : outcome
        ? `${outcome.ok ? "succeeded" : outcome.status} · ${outcome.outputs.length} output(s)`
        : jobId
          ? `${jobId.slice(0, 8)}… · ${waited}s`
          : probeResult
            ? probeResult.ok
              ? `${target.base} · ready`
              : `${target.base} · ${probeResult.detail}`
            : target.base,
  );

  async function check() {
    probing = true;
    try {
      probeResult = await probe(target);
    } catch (cause) {
      probeResult = {
        ok: false,
        detail: cause instanceof Error ? cause.message : String(cause),
      };
    } finally {
      probing = false;
    }
  }

  // Remember the target, and re-check it shortly after it stops changing.
  $effect(() => {
    const snapshot = { base: target.base, protocol: target.protocol, key: target.key };
    saveTarget(snapshot);
    const timer = setTimeout(() => untrack(() => void check()), 500);
    return () => clearTimeout(timer);
  });

  function choosePreset(id: string) {
    const chosen = PRESETS.find((entry) => entry.id === id);
    if (!chosen) return;
    target = { ...target, base: chosen.base, protocol: chosen.protocol };
  }

  async function queue() {
    if (!artifact || busy) return;
    busy = true;
    error = null;
    outcome = null;
    jobId = null;
    waited = 0;
    stop = false;
    try {
      const queued = await submitWorkflow(target, artifact.workflow);
      jobId = queued.jobId;
      const started = Date.now();
      while (!stop) {
        await new Promise((resolve) => setTimeout(resolve, 4000));
        waited = Math.round((Date.now() - started) / 1000);
        const state = await fetchOutcome(target, queued.pollUrl);
        if (state.done) {
          outcome = state;
          break;
        }
        if (waited > 900) {
          error = "gave up waiting after 15 minutes; it may still be rendering";
          break;
        }
      }
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }
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
      {#if probeResult && !probeResult.ok && !outcome}<span class="chip warn">unreachable</span>{/if}
      {#if outcome?.ok}<span class="chip">{outcome.outputs.length} output(s)</span>{/if}
    {/snippet}

    <div class="row">
      <label class="row small">
        target
        <select
          value={preset?.id ?? "custom"}
          onchange={(event) => choosePreset(event.currentTarget.value)}
          disabled={busy}
        >
          {#each PRESETS as entry (entry.id)}
            <option value={entry.id}>{entry.label}</option>
          {/each}
        </select>
      </label>
      <label class="row small">
        address
        <input type="text" style="width:12rem" bind:value={target.base} disabled={busy} />
      </label>
      <label class="row small">
        protocol
        <select bind:value={target.protocol} disabled={busy}>
          <option value="native">native</option>
          <option value="v2">v2</option>
        </select>
      </label>
    </div>

    {#if target.protocol === "v2"}
      <label class="row small">
        API key
        <input
          type="password"
          style="width:16rem"
          placeholder="Bearer token — v2 surfaces only"
          bind:value={target.key}
          disabled={busy}
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
      <button onclick={queue} disabled={busy || !artifact}>render</button>
      {#if busy}<button onclick={() => (stop = true)}>stop waiting</button>{/if}
      <button onclick={check} disabled={probing || busy}>check</button>
      <span class="small muted">
        {#if probing}checking…
        {:else if probeResult}<span class={probeResult.ok ? "" : "finding error"}>{probeResult.detail}</span>{/if}
      </span>
    </div>

    {#if jobId}
      <div class="small row">
        <span class="muted">job</span>
        <span class="mono">{jobId}</span>
        {#if busy}<span class="muted">· waiting {waited}s</span>{/if}
      </div>
    {/if}

    {#if outcome}
      <div class="small">
        <div class="row">
          <span class="muted">status</span>
          <span class={outcome.ok ? "" : "finding error"}>{outcome.status}</span>
        </div>
        {#each outcome.outputs as output, i (i)}
          <div class="row mono">{output.name}</div>
        {/each}
        {#if !outcome.outputs.length}
          <p class="small muted" style="margin:4px 0 0">
            No files reported. The render may have written elsewhere — check the service's own output
            directory.
          </p>
        {/if}
        {#each outcome.messages as message, i (i)}
          <div class="finding error">{message}</div>
        {/each}
      </div>
    {/if}

    {#if error}
      <pre class="finding error" style="white-space:pre-wrap; margin:0">{error}</pre>
      {#if !probeResult?.ok}
        <div class="small">
          <p style="margin:0">
            Nothing answered at <code>{target.base}</code>. A page on another origin is refused
            unless the service allows it:
          </p>
          {#if target.protocol === "v2"}
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
