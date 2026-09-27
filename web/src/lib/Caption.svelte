<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import type { RenderResult } from "./types";

  let { rendered, selected }: { rendered: RenderResult | null; selected: number } = $props();

  const used = $derived(rendered?.tags.length ?? 0);
  const budget = $derived(rendered?.budget ?? 0);
  const percent = $derived(budget ? Math.min(100, (used / budget) * 100) : 0);
  const summary = $derived(
    rendered
      ? `${used} / ${budget} tags · ${selected} selected · ${rendered.profile}`
      : "waiting for the text tier",
  );
</script>

<Collapsible title="Live caption" {summary} storageKey="mm.panel.caption" defaultOpen>
  {#snippet badges()}
    {#if used > budget}<span class="chip warn">over budget</span>{/if}
    {#if rendered?.problems?.length}
      <span class="chip warn">{rendered.problems.length} coherence</span>
    {/if}
    {#if rendered?.omitted?.length}
      <span class="chip">{rendered.omitted.length} dropped</span>
    {/if}
  {/snippet}

  <div class="meter" class:over={used > budget}>
    <span style={`width:${percent}%`}></span>
  </div>

  <div class="caption">
    {rendered?.string || "nothing selected yet"}
  </div>

  {#if rendered?.omitted?.length}
    <div>
      <h3 class="small muted">dropped by the budget — lowest priority first</h3>
      <div class="tag-list">
        {#each rendered.omitted as tag (tag)}
          <span class="tag omitted">{tag}</span>
        {/each}
      </div>
    </div>
  {/if}

  {#if rendered?.negatives?.length}
    <div>
      <h3 class="small muted">must not appear — negative conditioning, never tags</h3>
      <div class="tag-list">
        {#each rendered.negatives as tag (tag)}
          <span class="tag negative">{tag}</span>
        {/each}
      </div>
    </div>
  {/if}

  {#if rendered?.problems?.length}
    <div>
      <h3 class="small muted">coherence</h3>
      {#each rendered.problems as problem (problem)}
        <div class="finding error">{problem}</div>
      {/each}
    </div>
  {/if}
</Collapsible>
