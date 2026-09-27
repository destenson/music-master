<script lang="ts">
  import { onMount } from "svelte";
  import Brief from "./lib/Brief.svelte";
  import Builder from "./lib/Builder.svelte";
  import Caption from "./lib/Caption.svelte";
  import Inspector from "./lib/Inspector.svelte";
  import Lyrics from "./lib/Lyrics.svelte";
  import Timeline from "./lib/Timeline.svelte";
  import { asset, loadStaticData, MusicMasterCore, type StaticData } from "./lib/core";
  import { clear as clearDraft, read as readDraft, stable, write as writeDraft } from "./lib/draft";
  import { parseFindings, type Finding } from "./lib/lens";
  import { buildPrompt } from "./lib/prompt";
  import * as S from "./lib/selection";
  import type { LyricReport, RenderResult, Selections, TimelinePlan } from "./lib/types";

  /** One song for now; the workspace listing comes with the next milestone. */
  const SONG = "rap-metal-groove";
  const DRAFT_KEY = "state";

  interface Draft {
    selections?: string;
    lyric?: string;
    template?: string;
    bpm?: number;
    duration?: number | null;
    view?: "builder" | "lyrics";
  }

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
  let caretLine = $state(1);
  let view = $state<"builder" | "lyrics">("builder");

  // What the repository gave us. Everything else is a draft, and the interface says so: the song
  // directory is the record and a static page cannot write to it.
  let origin = $state<{
    selections: string;
    lyric: string;
    template: string;
    bpm: number;
    duration: number | null;
  } | null>(null);

  let dirty = $derived.by(() => {
    if (!origin) return false;
    return (
      stable(selections) !== origin.selections ||
      lyricText !== origin.lyric ||
      templateId !== origin.template ||
      bpm !== origin.bpm ||
      duration !== origin.duration
    );
  });

  // The Python calls are synchronous and cheap (a caption round-trip is well under a millisecond),
  // so derived values are enough: no debounce, no request queue.
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
    if (!core || !templateId) return null;
    try {
      return core.checkLyric({
        text: lyricText,
        selections,
        template_id: templateId,
        bpm,
      });
    } catch (error) {
      console.error("lyric check failed", error);
      return null;
    }
  });

  let brief = $derived.by((): string => {
    if (!core || !templateId) return "";
    try {
      return core.brief({ template_id: templateId, bpm, duration_s: duration, selections }).brief;
    } catch (error) {
      console.error("brief failed", error);
      return "";
    }
  });

  // Keep the working state across a reload. `stable` walks every property, which is what makes a
  // change deep inside a selection a dependency of this effect rather than an invisible one.
  let saveTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const snapshot: Draft = {
      selections: stable(selections),
      lyric: lyricText,
      template: templateId,
      bpm,
      duration,
      view,
    };
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => writeDraft(DRAFT_KEY, snapshot), 250);
  });

  /** Throw the draft away and go back to what the repository holds. */
  function revertToRepository(): void {
    if (!origin) return;
    selections = JSON.parse(origin.selections) as Selections;
    lyricText = origin.lyric;
    templateId = origin.template;
    bpm = origin.bpm;
    duration = origin.duration;
    clearDraft(DRAFT_KEY);
  }

  /** The linter's view of the same check, for the squiggles. Pure: it writes no state. */
  function checkText(source: string): Finding[] {
    if (!core || !templateId) return [];
    try {
      return parseFindings(
        core.checkLyric({ text: source, selections, template_id: templateId, bpm }),
      );
    } catch (error) {
      console.error("lint failed", error);
      return [];
    }
  }

  function buildPromptFor(theme: string): string {
    return buildPrompt({
      brief: brief || "(the brief could not be built)",
      caption: rendered?.string || "(nothing selected)",
      theme,
    });
  }

  function applyDraft(draft: string): void {
    lyricText = draft;
  }

  function scaffoldFromTemplate(): void {
    if (!core || !templateId) return;
    try {
      lyricText = core.scaffold({ template_id: templateId }).text;
    } catch (error) {
      console.error("scaffold failed", error);
    }
  }

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
      const loadedSelections = selectionFile.selections ?? {};

      const response = await fetch(asset(`repo/songs/${SONG}/lyrics.md`));
      const loadedLyric = await response.text();

      origin = {
        selections: stable(loadedSelections),
        lyric: loadedLyric,
        template: song.template_id,
        bpm: song.bpm,
        duration: null,
      };

      selections = loadedSelections;
      lyricText = loadedLyric;

      // A draft from a previous visit wins over the files, but only until it is reverted.
      const draft = readDraft<Draft>(DRAFT_KEY);
      if (draft) {
        if (draft.selections) selections = JSON.parse(draft.selections) as Selections;
        if (typeof draft.lyric === "string") lyricText = draft.lyric;
        if (draft.template) templateId = draft.template;
        if (typeof draft.bpm === "number") bpm = draft.bpm;
        if (draft.duration !== undefined) duration = draft.duration;
        if (draft.view) view = draft.view;
      }

      core = await MusicMasterCore.boot((message) => (status = message));
      status = "ready";
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error);
      status = "failed";
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
    {#if dirty}
      <span
        class="chip warn"
        title="Held in this browser only. The song directory is the record, and a page cannot write to it."
      >
        local draft
      </span>
      <button onclick={revertToRepository}>revert to {songId}</button>
    {/if}
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
        <Lyrics
          bind:text={lyricText}
          report={lyricReport}
          pools={data.pools}
          check={checkText}
          buildPrompt={buildPromptFor}
          onDraft={applyDraft}
          onScaffold={scaffoldFromTemplate}
          onCaret={(line) => (caretLine = line)}
        />
      </div>
      <div class="column">
        <div class="stack">
          <Inspector report={lyricReport} {plan} {caretLine} />
          <Brief text={brief} />
          <Caption {rendered} selected={S.selectedCount(selections)} />
        </div>
      </div>
    </div>
  {/if}
</div>
