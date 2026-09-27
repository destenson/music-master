<script lang="ts">
  import { onMount } from "svelte";
  import Builder from "./lib/Builder.svelte";
  import Caption from "./lib/Caption.svelte";
  import Lyrics from "./lib/Lyrics.svelte";
  import Timeline from "./lib/Timeline.svelte";
  import { asset, loadStaticData, MusicMasterCore, type StaticData } from "./lib/core";
  import * as S from "./lib/selection";
  import type { LyricReport, RenderResult, Selections, TimelinePlan } from "./lib/types";

  /** One song for now; the workspace listing comes with the next milestone. */
  const SONG = "rap-metal-groove";

  let status = $state("starting up");
  let failure = $state<string | null>(null);
  let core = $state<MusicMasterCore | null>(null);
  let data = $state<StaticData | null>(null);
  let songId = $state(SONG);
  let templateId = $state("");
  let bpm = $state(120);
  let duration = $state<number | null>(null);
  let selections = $state<Selections>({});
  let lyricText = $state("");
  let view = $state<"builder" | "lyrics">("builder");

  async function getJson<T>(path: string): Promise<T> {
    const response = await fetch(asset(`repo/${path}`));
    if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${path}`);
    return (await response.json()) as T;
  }

  onMount(async () => {
    try {
      status = "reading the vocabulary";
      data = await loadStaticData();

      const song = await getJson<{ song_id: string; template_id: string; bpm: number }>(
        `songs/${SONG}/song.json`,
      );
      songId = song.song_id;
      templateId = song.template_id;
      bpm = song.bpm;

      const selectionFile = await getJson<{ selections: Selections }>(
        `songs/${SONG}/selections.json`,
      );
      selections = selectionFile.selections ?? {};

      const response = await fetch(asset(`repo/songs/${SONG}/lyrics.md`));
      lyricText = await response.text();

      core = await MusicMasterCore.boot((message) => (status = message));
      status = "ready";
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error);
      status = "failed";
    }
  });

  // The Python calls are synchronous and cheap (the whole caption round-trip is well under a
  // millisecond), so a derived value is enough: no debounce, no request queue.
  let rendered = $derived.by((): RenderResult | null => {
    if (!core) return null;
    try {
      return core.render(selections);
    } catch (error) {
      console.error("render failed", error);
      return null;
    }
  });

  let plan = $derived.by((): TimelinePlan | null => {
    if (!core || !templateId) return null;
    try {
      return core.plan({ template_id: templateId, bpm, duration_s: duration, selections });
    } catch (error) {
      console.error("plan failed", error);
      return null;
    }
  });

  let lyricReport = $derived.by((): LyricReport | null => {
    if (!core || view !== "lyrics") return null;
    try {
      return core.checkLyric({
        text: lyricText,
        selections,
        template_id: templateId || null,
        bpm,
      });
    } catch (error) {
      console.error("lyric check failed", error);
      return null;
    }
  });
</script>

<div class="shell">
  <div class="topbar">
    <h1>Music Master</h1>
    <span class="small muted">
      {songId} · {templateId || "…"} · target ACE-Step 1.5 XL turbo
    </span>
    <span class="spacer"></span>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected={view === "builder"} onclick={() => (view = "builder")}>
        Builder
      </button>
      <button role="tab" aria-selected={view === "lyrics"} onclick={() => (view = "lyrics")}>
        Lyrics
      </button>
    </div>
    <span class="small muted">{status}</span>
  </div>

  {#if failure}
    <div class="status failed">
      <p>Could not start: {failure}</p>
      <p class="small">
        The page needs its own dev server or a static host — opening the file directly will not work,
        because the runtime and the repository are fetched over HTTP.
      </p>
    </div>
  {:else if !core || !data}
    <div class="status">{status}…</div>
  {:else if view === "builder"}
    <div class="columns">
      <div class="column">
        <Builder bins={data.vocabulary.bins} {selections} />
      </div>
      <div class="column">
        <div class="stack">
          <Caption {rendered} selected={S.selectedCount(selections)} />
          <Timeline {plan} templates={data.templates} bind:templateId bind:bpm bind:duration />
        </div>
      </div>
    </div>
  {:else}
    <div class="columns">
      <div class="column">
        <Lyrics bind:text={lyricText} report={lyricReport} />
      </div>
      <div class="column">
        <div class="stack">
          <Caption {rendered} selected={S.selectedCount(selections)} />
        </div>
      </div>
    </div>
  {/if}
</div>
