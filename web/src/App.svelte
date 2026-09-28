<script lang="ts">
  import { onMount } from "svelte";
  import Brief from "./lib/Brief.svelte";
  import Builder from "./lib/Builder.svelte";
  import Caption from "./lib/Caption.svelte";
  import Inspector from "./lib/Inspector.svelte";
  import Lyrics from "./lib/Lyrics.svelte";
  import Oracle from "./lib/Oracle.svelte";
  import RadioPanel from "./lib/Radio.svelte";
  import Render from "./lib/Render.svelte";
  import Preview from "./lib/Preview.svelte";
  import Song from "./lib/Song.svelte";
  import Timeline from "./lib/Timeline.svelte";
  import { freshSeed, previewSeed } from "./lib/comfy";
  import { asset, loadStaticData, MusicMasterCore, type StaticData } from "./lib/core";
  import {
    clear as clearDraft,
    deleteNamed,
    freeName,
    listSaved,
    loadNamed,
    read as readDraft,
    saveNamed,
    stable,
    write as writeDraft,
    type DraftSummary,
  } from "./lib/draft";
  import { parseFindings, type Finding } from "./lib/lens";
  import { generate, ollamaBase } from "./lib/ollama";
  import { buildPrompt } from "./lib/prompt";
  import { setPreviewBuilder } from "./lib/preview.svelte";
  import { setRadioHost } from "./lib/radio.svelte";
  import { checkTarget, forgetUsedSeed, rememberTarget, renderQueue, startRender } from "./lib/render.svelte";
  import {
    reloadNow,
    reloadedFor,
    updateState,
    watchForUpdates,
  } from "./lib/update.svelte";
  import * as S from "./lib/selection";
  import type { Artifacts, LyricRepair, LyricReport, PreviewRow, RenderResult, Selections, TimelinePlan } from "./lib/types";

  /** One song for now; the workspace listing comes with the next milestone. */
  const SONG = "rap-metal-groove";
  const DRAFT_KEY = "state";

  interface Draft {
    selections?: string;
    lyric?: string;
    template?: string;
    bpm?: number;
    duration?: number | null;
    view?: View;
    songId?: string;
    seed?: number;
    artists?: string;
    brief?: string;
  }

  type View = "builder" | "lyrics" | "render" | "radio" | "compliance";

  /** Everything a saved draft carries. The view is deliberately not in it: loading a draft should
   * not move you to another tab. */
  interface Snapshot {
    selections: string;
    lyric: string;
    template: string;
    bpm: number;
    duration: number | null;
    songId: string;
    seed: number;
    artists: string;
    brief: string;
  }

  let status = $state("starting up");
  let failure = $state<string | null>(null);
  let core = $state<MusicMasterCore | null>(null);
  let data = $state<StaticData | null>(null);
  let songId = $state(SONG);
  let templateId = $state("");
  let bpm = $state(120);
  let duration = $state<number | null>(null);
  let seed = $state(0);
  let artists = $state("");
  let briefText = $state("");
  let selections = $state<Selections>({});
  let lyricText = $state("");
  /** What the last repair did to a generated draft, so the edit is never silent. */
  let lyricRepair = $state<LyricRepair | null>(null);
  let caretLine = $state(1);
  let view = $state<View>("builder");

  // What the repository gave us. Everything else is a draft, and the interface says so: the song
  // directory is the record and a static page cannot write to it.
  let origin = $state<{
    selections: string;
    lyric: string;
    template: string;
    bpm: number;
    duration: number | null;
    songId: string;
    seed: number;
    artists: string;
    brief: string;
  } | null>(null);

  let dirty = $derived.by(() => {
    if (!origin) return false;
    return (
      stable(selections) !== origin.selections ||
      lyricText !== origin.lyric ||
      templateId !== origin.template ||
      bpm !== origin.bpm ||
      duration !== origin.duration ||
      songId !== origin.songId ||
      seed !== origin.seed ||
      artists !== origin.artists ||
      briefText !== origin.brief
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

  /**
   * What the song is about, for the compliance spec. The page has no single theme field — the
   * writer types one in the generator panel — but the draft does record it in the `lyric_theme`
   * bin, so the oracle reads the labels the form already holds rather than a second, invented
   * source. An empty bin means no theme was stated, which the spec marks as unspecified.
   */
  let theme = $derived.by((): string => {
    const bin = data?.vocabulary.bins.find((entry) => entry.id === "lyric_theme");
    return bin ? S.labels(bin, selections[bin.id]).join(", ") : "";
  });

  // The exclusions the prompt already carries, in the shape the Jev request expects.
  let artistReferences = $derived(
    artists
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  );

  /** The render path: the canonical prompt, the composition it pins, and the ComfyUI graph.
   *
   * Built for a given seed rather than only for the current one, so a render can use a fresh seed
   * that the graph on screen does not carry yet. */
  function artifactsFor(seedValue: number): Artifacts | null {
    if (!core || !templateId) return null;
    try {
      return core.artifacts({
        song_id: songId,
        template_id: templateId,
        bpm,
        seed: seedValue,
        selections,
        lyrics: lyricText,
        brief: briefText,
        artist_references: artists
          .split(",")
          .map((entry) => entry.trim())
          .filter(Boolean),
      });
    } catch (error) {
      console.error("artifacts failed", error);
      return null;
    }
  }

  let artifact = $derived.by(() => artifactsFor(seed));

  /**
   * The seed a preview and an A/B render with: the seed of the last take. A render's fresh seed — or
   * one typed into the seed field — does not reach a preview until a take has been rendered with it,
   * because a preview explains a take and so has to hold that take's arrangement.
   */
  let previewSeedValue = $derived(previewSeed(renderQueue.usedSeed, seed));

  /**
   * The preview graphs: the same caption the page would send, at full song length and coarse steps.
   * `variants` are bin/option pairs and each becomes its own row, so an A/B of a tag is one graph
   * for the current caption and one for the variant. Each row is a solo render, because the queue
   * caches a row and reuses it and a caption rendered inside a batch is not the same take.
   */
  function buildPreview(
    forSelections: Selections,
    steps: number,
    variants: { bin: string; option: string }[],
  ): { rows: PreviewRow[] } | null {
    if (!core || !templateId) return null;
    try {
      return core.preview({
        song_id: songId,
        template_id: templateId,
        bpm,
        seed: previewSeedValue,
        selections: forSelections,
        lyrics: lyricText,
        brief: briefText,
        artist_references: artists
          .split(",")
          .map((entry) => entry.trim())
          .filter(Boolean),
        variants,
        steps,
      });
    } catch (error) {
      console.error("preview failed", error);
      return null;
    }
  }

  // The preview queue is shared by the top-bar panel and the per-checkbox A/B buttons, so the one
  // builder that reads the page's current state is registered here rather than rebuilt in each.
  $effect(() => {
    setPreviewBuilder((steps, variants) => buildPreview(selections, steps, variants));
  });

  /**
   * The radio engine needs the text tier, and the app owns it. Registering the four calls it needs
   * keeps the engine out of the page's state: it asks for a plan, a caption, a brief and a graph,
   * and never reaches into the form.
   */
  $effect(() => {
    const instance = core;
    if (!instance) {
      setRadioHost(null);
      return;
    }
    setRadioHost({
      plan: (stationId, index, seed, instrumental) =>
        instance.radioPlan({ station_id: stationId, index, seed, instrumental }),
      render: (forSelections) => instance.render(forSelections),
      brief: (templateId, atBpm, forSelections) =>
        instance.brief({ template_id: templateId, bpm: atBpm, duration_s: null, selections: forSelections })
          .brief,
      cleanLyric: (text) => instance.cleanLyric({ text }),
      artifacts: (request) => instance.artifacts({ ...request, artist_references: [] }),
    });
    return () => setRadioHost(null);
  });

  /**
   * Take a new build as soon as it is seen.
   *
   * Nothing is allowed to hold it back. An earlier version waited for a render, a preview or a
   * station to finish first, which reads as "never" for a station: a stream is always running, so
   * waiting for it to be idle is waiting forever, and the update only ever appeared as a chip.
   * The guard is what stops a stale version answer from reloading in a loop.
   */
  $effect(() => {
    if (!updateState.ready || reloadedFor(updateState.latest)) {
      updateState.notice = null;
      return;
    }
    updateState.notice = "updating to the new version…";
    const timer = setTimeout(() => reloadNow(), 600);
    return () => clearTimeout(timer);
  });

  /**
   * The render target is app-level state, so its persistence and its reachability check live here
   * rather than in a panel that only exists while its tab is open.
   */
  let targetTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    // Read so the effect tracks them, then discarded: the dependency is the point, not the value.
    void renderQueue.target.base;
    void renderQueue.target.protocol;
    void renderQueue.target.key;
    rememberTarget();
    clearTimeout(targetTimer);
    targetTimer = setTimeout(() => void checkTarget(), 600);
  });

  /**
   * Both top-bar actions, and the only two. `fresh` decides the seed, so neither of them consults
   * the Render panel's checkbox — a button that changed meaning according to a control in a panel
   * you might not have open is what made this confusing.
   */
  function quickRender(fresh: boolean): void {
    void startRender({ seed, fresh, onSeed: (chosen) => (seed = chosen), artifactsFor });
  }

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
      songId,
      seed,
      artists,
      brief: briefText,
    };
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => writeDraft(DRAFT_KEY, snapshot), 250);
  });

  /** Throw the draft away and go back to what the repository holds. */
  function revertToRepository(): void {
    if (!origin) return;
    selections = JSON.parse(origin.selections) as Selections;
    lyricText = origin.lyric;
    lyricRepair = null;
    templateId = origin.template;
    bpm = origin.bpm;
    duration = origin.duration;
    songId = origin.songId;
    seed = origin.seed;
    artists = origin.artists;
    briefText = origin.brief;
    clearDraft(DRAFT_KEY);
  }

  // --- Named drafts ---------------------------------------------------------------------------
  //
  // The autosave above keeps one working state so a reload does not lose an edit. These are the
  // deliberate ones: a name you choose, kept until you delete it, so several directions can exist at
  // once and be switched between.

  let saved = $state<DraftSummary[]>([]);
  let draftName = $state("");
  let nameInput = $state("");
  let baseline = $state("");

  function currentSnapshot(): Snapshot {
    return {
      selections: stable(selections),
      lyric: lyricText,
      template: templateId,
      bpm,
      duration,
      songId,
      seed,
      artists,
      brief: briefText,
    };
  }

  function applySnapshot(snapshot: Snapshot): void {
    selections = JSON.parse(snapshot.selections) as Selections;
    lyricText = snapshot.lyric;
    lyricRepair = null;
    templateId = snapshot.template;
    bpm = snapshot.bpm;
    duration = snapshot.duration;
    songId = snapshot.songId;
    seed = snapshot.seed;
    artists = snapshot.artists;
    briefText = snapshot.brief;
  }

  // The snapshot's own selections field is already a canonical string, so this is deterministic.
  const serialise = (snapshot: Snapshot): string => JSON.stringify(snapshot);

  const modified = $derived(
    draftName !== "" && baseline !== "" && serialise(currentSnapshot()) !== baseline,
  );

  function saveCurrentDraft(): void {
    // Re-saving under a name that exists would overwrite it silently, so a free one is chosen.
    const name = freeName(nameInput || songId, saved.map((entry) => entry.name));
    const snapshot = currentSnapshot();
    saved = saveNamed(name, snapshot, songId);
    draftName = name;
    nameInput = name;
    baseline = serialise(snapshot);
  }

  function loadSavedDraft(name: string): void {
    draftName = name;
    if (!name) {
      baseline = "";
      return;
    }
    const snapshot = loadNamed<Snapshot>(name);
    if (!snapshot) return;
    applySnapshot(snapshot);
    nameInput = name;
    baseline = serialise(snapshot);
  }

  function deleteSavedDraft(): void {
    if (!draftName) return;
    saved = deleteNamed(draftName);
    draftName = "";
    nameInput = "";
    baseline = "";
  }

  /** A blank song in the browser. A page cannot make a directory, so this is a draft you export. */
  function newSong(): void {
    songId = "untitled-song";
    seed = freshSeed();
    // No take exists for a blank song, so there is no previous seed for a preview to hold.
    forgetUsedSeed();
    artists = "";
    briefText = "";
    selections = {};
    duration = null;
    draftName = "";
    nameInput = "";
    baseline = "";
    try {
      lyricText = core?.scaffold({ template_id: templateId }).text ?? "";
      lyricRepair = null;
    } catch (error) {
      console.error("scaffold failed", error);
    }
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
    // A new generation is arriving, so the previous repair's report no longer describes the text.
    lyricRepair = null;
    lyricText = draft;
  }

  /**
   * The finished draft, repaired, with every edit it took reported.
   *
   * A model that has just read the brief sometimes writes one of its lines — "Energy 3/5" — into the
   * section it describes, or a tag without its brackets, where the meter check counts it and the
   * renderer would sing it. The rule lives in the text tier, so the repair here is the same one the
   * CLI applies, and a failure to repair leaves the draft as the model wrote it rather than throwing
   * it away. What the repair removed or rewrote is kept, because a silent edit to the words is worse
   * than the leak it fixed.
   */
  function applyFinalDraft(draft: string): void {
    if (!core) {
      lyricText = draft;
      return;
    }
    try {
      const repaired = core.cleanLyric({ text: draft });
      lyricText = repaired.text;
      lyricRepair = repaired.removed.length || repaired.changed.length ? repaired : null;
    } catch (error) {
      console.error("the lyric repair failed", error);
      lyricText = draft;
      lyricRepair = null;
    }
  }

  function scaffoldFromTemplate(): void {
    if (!core || !templateId) return;
    try {
      lyricText = core.scaffold({ template_id: templateId }).text;
      lyricRepair = null;
    } catch (error) {
      console.error("scaffold failed", error);
    }
  }

  /** Generate.svelte remembers the chosen lyric model here, so the repair uses the same one. */
  const LYRIC_MODEL_KEY = "mm.ollama.model";

  /**
   * Rewrite the lyric to satisfy the check's own repair instructions, and return the new text.
   *
   * The instructions come from `musicmaster.repairs`, so the generator is told what each failed
   * check localised rather than being asked to critique its own output. The prompt is a *repair*
   * prompt, not the writing brief: leading with the brief invites a fresh lyric, and the point is to
   * change the lines the repairs name and leave the rest alone. The model is the one chosen on the
   * Lyrics tab; with none chosen there is nothing to generate with, and the caller shows why.
   */
  async function repairLyrics(instructions: string): Promise<string> {
    let model = "";
    try {
      model = localStorage.getItem(LYRIC_MODEL_KEY) ?? "";
    } catch {
      model = "";
    }
    if (!model) {
      throw new Error("no lyric model selected — choose one on the Lyrics tab, then check again");
    }
    const context = [
      rendered?.string ? `Caption: ${rendered.string}` : "",
      theme ? `Theme: ${theme}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    const prompt = [
      context,
      "",
      "You are repairing an existing lyric, not writing a new one. Apply every repair below and",
      "return the whole lyric. Keep every section header, performance tag and line that the repairs",
      "do not name exactly as it is; change only what they name.",
      "",
      "## Repairs",
      instructions,
      "",
      "## Lyric to repair",
      lyricText,
    ].join("\n");
    const text = await generate({ model, base: ollamaBase(), prompt, onText: applyDraft });
    applyFinalDraft(text);
    return lyricText;
  }

  async function getJson<T>(path: string): Promise<T> {
    const response = await fetch(asset(`repo/${path}`));
    if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${path}`);
    return (await response.json()) as T;
  }

  onMount(async () => {
    try {
      saved = listSaved();
      // Before anything is loaded: a page the host served from its cache is running superseded code,
      // and it should reload rather than spend the boot on a build it is about to replace.
      watchForUpdates();
      status = "reading the vocabulary";
      data = await loadStaticData();

      const song = await getJson<{
        song_id: string;
        template_id: string;
        bpm: number;
        seed: number;
        artist_references?: string[];
      }>(`songs/${SONG}/song.json`);
      songId = song.song_id;
      templateId = song.template_id;
      bpm = song.bpm;
      seed = song.seed;
      artists = (song.artist_references ?? []).join(", ");

      const selectionFile = await getJson<{ selections: Selections }>(
        `songs/${SONG}/selections.json`,
      );
      const loadedSelections = selectionFile.selections ?? {};

      const response = await fetch(asset(`repo/songs/${SONG}/lyrics.md`));
      const loadedLyric = await response.text();
      const briefResponse = await fetch(asset(`repo/songs/${SONG}/brief.md`));
      const loadedBrief = await briefResponse.text();

      origin = {
        selections: stable(loadedSelections),
        lyric: loadedLyric,
        template: song.template_id,
        bpm: song.bpm,
        duration: null,
        songId: song.song_id,
        seed: song.seed,
        artists: artists,
        brief: loadedBrief,
      };

      selections = loadedSelections;
      lyricText = loadedLyric;
      briefText = loadedBrief;

      // A draft from a previous visit wins over the files, but only until it is reverted.
      const draft = readDraft<Draft>(DRAFT_KEY);
      if (draft) {
        if (draft.selections) selections = JSON.parse(draft.selections) as Selections;
        if (typeof draft.lyric === "string") lyricText = draft.lyric;
        if (draft.template) templateId = draft.template;
        if (typeof draft.bpm === "number") bpm = draft.bpm;
        if (draft.duration !== undefined) duration = draft.duration;
        if (draft.view) view = draft.view;
        if (draft.songId) songId = draft.songId;
        if (typeof draft.seed === "number") seed = draft.seed;
        if (typeof draft.artists === "string") artists = draft.artists;
        if (typeof draft.brief === "string") briefText = draft.brief;
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

    <div class="drafts">
      <select
        value={draftName}
        onchange={(event) => loadSavedDraft(event.currentTarget.value)}
        title={saved.length ? "load a saved draft" : "no saved drafts yet"}
      >
        <option value="">{saved.length ? "load a draft…" : "no saved drafts"}</option>
        {#each saved as entry (entry.name)}
          <option value={entry.name}>{entry.name}</option>
        {/each}
      </select>
      <input class="draft-name" placeholder="draft name" bind:value={nameInput} />
      <button onclick={saveCurrentDraft} title="save the current state under this name">save</button>
      {#if draftName}
        <button onclick={deleteSavedDraft} title="delete this saved draft">delete</button>
      {/if}
      {#if modified}
        <span class="chip warn" title="changed since you saved this draft">modified</span>
      {/if}
    </div>

    {#if dirty}
      <span
        class="chip warn"
        title="Differs from the files in songs/<id>/. A page cannot write them, so export instead."
      >
        differs from repo
      </span>
      <button onclick={revertToRepository}>revert to {songId}</button>
    {/if}

    <button
      class="primary"
      onclick={() => quickRender(true)}
      disabled={renderQueue.busy || !artifact}
      title="Render from any tab with a generated seed, so this take's arrangement is new."
    >
      {renderQueue.busy ? `rendering ${renderQueue.waited}s` : "render"}
    </button>
    <button
      onclick={() => quickRender(false)}
      disabled={renderQueue.busy || !artifact}
      title={`Re-render with seed ${seed}. The same inputs reproduce the same take, which holds the arrangement still while something else changes.`}
    >
      re-render {seed}
    </button>
    <Preview bins={data?.vocabulary.bins ?? []} ready={!!core && !!data} seed={previewSeedValue} />
    {#if renderQueue.error}
      <span class="chip warn" title={renderQueue.error}>render failed</span>
    {/if}
    {#if renderQueue.outcome?.ok}
      <span class="chip" title={renderQueue.outcome.outputs.join("\n")}>
        {renderQueue.outcome.outputs.length} file(s)
      </span>
    {/if}

    {#if updateState.ready}
      <button
        class="chip warn"
        onclick={reloadNow}
        title="A new build is deployed. It reloads itself as soon as no render, preview or station is running."
      >
        {updateState.notice ?? "new version — reload"}
      </button>
    {/if}

    <div class="tabs" role="tablist">
      <button role="tab" aria-selected={view === "builder"} onclick={() => (view = "builder")}>
        Builder
      </button>
      <button role="tab" aria-selected={view === "lyrics"} onclick={() => (view = "lyrics")}>
        Lyrics
      </button>
      <button role="tab" aria-selected={view === "render"} onclick={() => (view = "render")}>
        Render
      </button>
      <button role="tab" aria-selected={view === "radio"} onclick={() => (view = "radio")}>
        Radio
      </button>
      <button
        role="tab"
        aria-selected={view === "compliance"}
        onclick={() => (view = "compliance")}
      >
        Check
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
  {:else if view === "lyrics"}
    <div class="columns">
      <div class="column">
        <Lyrics
          bind:text={lyricText}
          report={lyricReport}
          repair={lyricRepair}
          pools={data.pools}
          check={checkText}
          buildPrompt={buildPromptFor}
          onDraft={applyDraft}
          onFinal={applyFinalDraft}
          onScaffold={scaffoldFromTemplate}
          onDismissRepair={() => (lyricRepair = null)}
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
  {:else if view === "render"}
    <div class="columns">
      <div class="column">
        <div class="stack">
          <Song
            bind:songId
            bind:templateId
            bind:bpm
            bind:artists
            bind:brief={briefText}
            templates={data.templates}
            onNewSong={newSong}
          />
          <Brief text={brief} />
        </div>
      </div>
      <div class="column">
        <Render {artifact} bind:seed {artifactsFor} />
      </div>
    </div>
  {:else if view === "compliance"}
    <!-- The oracle is one full-width pane rather than the form-and-inspector split: a report is a
         document to read across, and its unverified block is the part that must not be cramped. -->
    <div class="columns" style="grid-template-columns: minmax(0, 1fr)">
      <div class="column">
        <Oracle
          {core}
          {songId}
          {selections}
          {bpm}
          {duration}
          {templateId}
          lyrics={lyricText}
          caption={rendered?.string ?? ""}
          {theme}
          {artistReferences}
          onRepair={repairLyrics}
        />
      </div>
    </div>
  {/if}

  <!--
    The radio is mounted on every tab and hidden with CSS rather than unmounted, because its
    `<audio>` element is the stream: a radio that stopped when you looked at the Builder would not
    be a radio.
  -->
  {#if data}
    <div class="radio-host" class:active={view === "radio"}>
      <RadioPanel stations={data.stations} ready={!!core} />
    </div>
  {/if}
</div>
