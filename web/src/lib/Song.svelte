<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import type { StructureTemplate } from "./types";

  let {
    songId = $bindable(),
    templateId = $bindable(),
    bpm = $bindable(),
    artists = $bindable(),
    brief = $bindable(),
    templates,
    onNewSong,
  }: {
    songId: string;
    templateId: string;
    bpm: number;
    artists: string;
    brief: string;
    templates: StructureTemplate[];
    onNewSong: () => void;
  } = $props();
</script>

<Collapsible
  title="Song"
  summary={`${songId} · ${bpm} BPM`}
  storageKey="mm.panel.song"
  defaultOpen
>
  <div class="row">
    <label class="row small">
      id
      <input type="text" style="width:12rem" bind:value={songId} />
    </label>
    <label class="row small">
      template
      <select bind:value={templateId}>
        {#each templates as entry (entry.id)}
          <option value={entry.id}>{entry.name}</option>
        {/each}
      </select>
    </label>
    <label class="row small">
      tempo
      <input type="number" style="width:4.5rem" min="40" max="220" bind:value={bpm} />
      BPM
    </label>
  </div>

  <label class="row small">
    artist references
    <input
      type="text"
      style="flex:1; min-width:12rem"
      placeholder="comma separated; recorded as exclusions, never sent as a prompt"
      bind:value={artists}
    />
  </label>

  <label class="small" style="display:flex; flex-direction:column; gap:4px">
    brief — what this song is required to do; hashed into the prompt as <code>spec_sha256</code>
    <textarea class="brief-input" bind:value={brief} spellcheck="false"></textarea>
  </label>

  <div class="row">
    <button onclick={onNewSong}>new song</button>
    <span class="muted small">
      a blank draft: empty selections, a fresh seed, and no words
    </span>
  </div>
</Collapsible>
