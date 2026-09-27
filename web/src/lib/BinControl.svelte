<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import * as S from "./selection";
  import type { Bin, BinSelection } from "./types";

  let {
    bin,
    selection,
    onchange,
  }: {
    bin: Bin;
    selection: BinSelection | undefined;
    onchange: (next: BinSelection) => void;
  } = $props();

  // A bin can be metadata-only (tempo, key): it shapes the request but never the caption. Saying so
  // on the control is the difference between a form and a form that explains itself.
  const metadataOnly = $derived(bin.emits_tag === false);
  const subtracts = $derived(bin.polarity === "negative");
  const count = $derived(S.chosen(selection).length);
  const atCap = $derived(bin.max_selections !== undefined && count >= bin.max_selections);
</script>

<Collapsible
  title={bin.label}
  summary={S.labels(bin, selection).join(", ")}
  storageKey={`mm.bin.${bin.id}`}
  avoid={subtracts}
  defaultOpen
>
  {#snippet badges()}
    {#if subtracts}<span class="chip negative">never a tag</span>{/if}
    {#if metadataOnly}<span class="chip meta">not in caption</span>{/if}
    {#if bin.max_selections}<span class="chip">{count} / {bin.max_selections}</span>{/if}
    {#if bin.caution}<span class="chip warn">{bin.caution}</span>{/if}
  {/snippet}

  {#if bin.help}
    <p class="small muted" style="margin:0">{bin.help}</p>
  {/if}

  {#if bin.control === "multi_select"}
    <div class="options">
      {#each bin.options ?? [] as option (option.id)}
        {@const on = S.has(selection, option.id)}
        <label class="option" class:disabled={!on && atCap}>
          <input
            type="checkbox"
            checked={on}
            disabled={!on && atCap}
            onchange={() => onchange(S.toggle(selection, option.id, bin.max_selections))}
          />
          {option.label}
        </label>
      {/each}
    </div>
  {:else if bin.control === "single_select"}
    <select
      value={S.chosen(selection)[0] ?? ""}
      onchange={(event) => onchange(S.setSingle(selection, event.currentTarget.value))}
    >
      <option value="">—</option>
      {#each bin.options ?? [] as option (option.id)}
        <option value={option.id}>{option.label}</option>
      {/each}
    </select>
  {:else if bin.control === "numeric_with_descriptor"}
    <div class="row">
      <input
        type="range"
        min={bin.range?.min}
        max={bin.range?.max}
        step={bin.range?.step}
        value={selection?.value ?? bin.range?.min ?? 0}
        oninput={(event) => onchange(S.setValue(selection, Number(event.currentTarget.value)))}
      />
      <input
        type="number"
        style="width:5.5rem"
        min={bin.range?.min}
        max={bin.range?.max}
        step={bin.range?.step}
        value={selection?.value ?? ""}
        oninput={(event) => onchange(S.setValue(selection, Number(event.currentTarget.value)))}
      />
      <span class="muted small">{bin.unit}</span>
    </div>
    {#if bin.descriptor_options?.length}
      <p class="small muted" style="margin:0">
        {bin.descriptor_options.length} descriptor options are declared for this bin, but the renderer
        emits a bin's <code>options</code> and this bin declares none — so they are not offered here
        rather than offered and silently dropped.
      </p>
    {/if}
  {:else if bin.control === "key_mode"}
    <div class="row">
      <select
        value={selection?.key ?? ""}
        onchange={(event) =>
          onchange(S.setKeyMode(selection, event.currentTarget.value || null, selection?.mode ?? null))}
      >
        <option value="">key</option>
        {#each bin.key_options ?? [] as key (key)}
          <option value={key}>{key}</option>
        {/each}
      </select>
      <select
        value={selection?.mode ?? ""}
        onchange={(event) =>
          onchange(S.setKeyMode(selection, selection?.key ?? null, event.currentTarget.value || null))}
      >
        <option value="">mode</option>
        {#each bin.mode_options ?? [] as mode (mode)}
          <option value={mode}>{mode}</option>
        {/each}
      </select>
    </div>
  {:else if bin.control === "combo_free"}
    <div class="row">
      <select
        value={S.chosen(selection)[0] ?? ""}
        onchange={(event) => onchange(S.setSingle(selection, event.currentTarget.value))}
      >
        <option value="">—</option>
        {#each bin.options ?? [] as option (option.id)}
          <option value={option.id}>{option.label}</option>
        {/each}
      </select>
      <input
        type="text"
        placeholder="or type your own"
        value={selection?.text ?? ""}
        oninput={(event) => onchange(S.setText(selection, event.currentTarget.value))}
      />
    </div>
  {/if}
</Collapsible>
