<script lang="ts">
  import BinControl from "./BinControl.svelte";
  import Collapsible from "./Collapsible.svelte";
  import * as S from "./selection";
  import type { Bin, Selections } from "./types";

  let { bins, selections }: { bins: Bin[]; selections: Selections } = $props();

  // Group order comes from the data, not from a list here.
  const groups = $derived(S.byGroup(bins));
</script>

<div class="stack">
  {#each groups as group (group.group)}
    {@const summary = S.summarise(group.bins, selections)}
    <Collapsible
      title={group.group}
      summary={summary}
      storageKey={`mm.group.${group.group}`}
    >
      {#snippet badges()}
        <span class="chip">{S.setCount(group.bins, selections)} / {group.bins.length}</span>
      {/snippet}

      {#each group.bins as bin (bin.id)}
        <BinControl
          {bin}
          selection={selections[bin.id]}
          onchange={(next) => (selections[bin.id] = next)}
        />
      {/each}
    </Collapsible>
  {/each}
</div>
