<script lang="ts">
  import { onMount, untrack } from "svelte";
  import Collapsible from "./Collapsible.svelte";
  import { generate, listModels, ollamaBase, setOllamaBase, type OllamaModel } from "./ollama";

  let {
    buildPrompt,
    onDraft,
    onFinal,
  }: {
    /** The parent owns the brief and the caption, so it owns the prompt. */
    buildPrompt: (theme: string) => string;
    /** Called with the whole draft so far, on every streamed chunk. */
    onDraft: (text: string) => void;
    /**
     * Called once with the finished text, after the model stops.
     *
     * The streamed draft is shown as it arrives, because watching the lyric appear is the point of
     * streaming; the finished one is what gets repaired and kept, so a brief line the model copied
     * is dropped once rather than flickering in and out as each chunk completes it.
     */
    onFinal?: (text: string) => void;
  } = $props();

  const MODEL_KEY = "mm.ollama.model";

  let models = $state<OllamaModel[]>([]);
  let model = $state("");
  let base = $state(ollamaBase());
  let theme = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let controller: AbortController | null = null;

  const chosen = $derived(models.find((entry) => entry.name === model));
  const cloud = $derived(models.filter((entry) => entry.cloud));
  const local = $derived(models.filter((entry) => !entry.cloud));
  const pageOrigin = $derived(typeof window === "undefined" ? "" : window.location.origin);

  const serverSummary = $derived(
    error
      ? `unreachable at ${base}`
      : models.length
        ? `${base} · ${models.length} models, ${cloud.length} cloud`
        : `${base} · looking…`,
  );

  async function refresh(at: string) {
    error = null;
    try {
      const found = await listModels(at);
      models = found;
      const remembered = localStorage.getItem(MODEL_KEY);
      model = found.some((entry) => entry.name === model)
        ? model
        : (found.find((entry) => entry.name === remembered)?.name ??
          found.find((entry) => entry.cloud)?.name ??
          found[0]?.name ??
          "");
    } catch (cause) {
      models = [];
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  onMount(() => {
    void refresh(base);
  });

  // Re-list when the address changes, without tracking the state that refresh writes.
  $effect(() => {
    const at = base;
    untrack(() => void refresh(at));
  });

  $effect(() => {
    if (!model) return;
    try {
      localStorage.setItem(MODEL_KEY, model);
    } catch {
      /* not remembering is an acceptable outcome */
    }
  });

  async function start() {
    if (!model || busy) return;
    busy = true;
    error = null;
    controller = new AbortController();
    try {
      const text = await generate({
        model,
        base,
        prompt: buildPrompt(theme),
        signal: controller.signal,
        onText: onDraft,
      });
      onFinal?.(text);
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) {
        error = cause instanceof Error ? cause.message : String(cause);
      }
    } finally {
      busy = false;
      controller = null;
    }
  }
</script>

<div class="generate">
  <div class="row">
    <label class="row small">
      model
      <select bind:value={model} disabled={busy || models.length === 0}>
        {#if cloud.length}
          <optgroup label="cloud — via ollama.com">
            {#each cloud as entry (entry.name)}
              <option value={entry.name}>{entry.name}</option>
            {/each}
          </optgroup>
        {/if}
        {#if local.length}
          <optgroup label="local — uses this machine's GPU">
            {#each local as entry (entry.name)}
              <option value={entry.name}>{entry.name}</option>
            {/each}
          </optgroup>
        {/if}
      </select>
    </label>

    <button onclick={start} disabled={busy || !model}>Generate</button>
    {#if busy}<button onclick={() => controller?.abort()}>Stop</button>{/if}

    <label class="row small">
      theme
      <input
        type="text"
        style="flex:1; min-width:10rem"
        placeholder="what should it be about?"
        bind:value={theme}
        disabled={busy}
      />
    </label>
  </div>

  {#if error}
    <p class="finding error" style="margin:0">{error}</p>
  {/if}

  {#if chosen?.cloud}
    <p class="small muted" style="margin:0">
      <strong>{chosen.name}</strong> runs on ollama.com, so the brief, the caption and your theme are
      sent off this machine. Pick a local model to keep them here; that one competes for the GPU
      ComfyUI renders on.
    </p>
  {:else if chosen}
    <p class="small muted" style="margin:0">
      <strong>{chosen.name}</strong> runs here, on the GPU ComfyUI also renders on — expect it to be
      slow or to wait while a render is in flight. A cloud model avoids the queue and writes better.
    </p>
  {/if}

  <Collapsible title="Model server" summary={serverSummary} storageKey="mm.panel.server">
    {#snippet badges()}
      {#if error}<span class="chip warn">unreachable</span>{/if}
    {/snippet}

    <div class="row">
      <label class="row small">
        address
        <input
          type="text"
          style="width:14rem"
          bind:value={base}
          onchange={() => setOllamaBase(base)}
          disabled={busy}
        />
      </label>
      <button onclick={() => refresh(base)} disabled={busy}>reconnect</button>
      {#if base !== ""}
        <button
          onclick={() => {
            setOllamaBase("");
            base = ollamaBase();
          }}
          disabled={busy}
        >
          reset
        </button>
      {/if}
    </div>

    {#if error}
      <div class="small">
        <p style="margin:0">
          Nothing answered at <code>{base}</code>. If ollama is running on your own machine, the usual
          reason a deployed page cannot reach it is that ollama refuses the request's origin — its
          default allow-list is localhost and a few app schemes, and <code>{pageOrigin}</code> is not
          on it.
        </p>
        <p style="margin:6px 0 0">
          Restart it allowing this page:
        </p>
        <pre class="brief">OLLAMA_ORIGINS={pageOrigin} ollama serve</pre>
        <p class="muted" style="margin:6px 0 0">
          Chrome may also ask permission for a public page to reach a local address. If you would
          rather not open that up, point the address above at a server you control instead — or use
          the brief with a model in another window.
        </p>
      </div>
    {:else}
      <p class="small muted" style="margin:0">
        The default is the daemon on this machine. A page served from elsewhere — GitHub Pages, say —
        reaches it over CORS, so the machine running ollama has to allow this page's origin.
      </p>
    {/if}
  </Collapsible>
</div>
