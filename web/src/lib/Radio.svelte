<script lang="ts">
  /**
   * The Radio tab.
   *
   * A station list on the left, the stream on the right. The engine holds the queue and the
   * per-song pipeline; this component owns the one `<audio>` element, the controls, and the
   * history for the current station.
   *
   * The audio element is why this component is mounted even when another tab is showing: a
   * streaming radio that stopped when you looked at the Builder would not be a radio. The app
   * hides it with `display: none` rather than unmounting it.
   */
  import { onMount } from "svelte";
  import { listModels, ollamaBase, type OllamaModel } from "./ollama";
  import {
    advance,
    downloadSong,
    nowPlaying,
    radioState,
    refreshAvailable,
    replay,
    selectStation,
    setBufferTarget,
    setInstrumental,
    setModel,
    startRadio,
    stopRadio,
    upNext,
    type RadioSong,
    type RadioStatus,
  } from "./radio.svelte";
  import type { RadioStation } from "./types";

  let { stations, ready }: { stations: RadioStation[]; ready: boolean } = $props();

  let filter = $state("");
  let audio = $state<HTMLAudioElement | null>(null);
  let loadedUrl: string | null = null;
  // Whether the radio was on at the last run, so the effect starts playback on the edge rather
  // than on every change: otherwise a status change in the queue would undo a manual pause.
  let wasOn = false;
  let blocked = $state(false);
  /** Why the browser refused the current take, in words, rather than a silent 0:00. */
  let audioError = $state<string | null>(null);

  function audioFailure(): string {
    switch (audio?.error?.code) {
      case 1:
        return "playback was aborted";
      case 2:
        return "the network refused the file";
      case 3:
        return "the file could not be decoded";
      case 4:
        return "the browser would not load the file — this page may not be allowed to reach it";
      default:
        return "the file could not be played";
    }
  }

  let models = $state<OllamaModel[]>([]);
  let modelError = $state<string | null>(null);

  const current = $derived(nowPlaying());
  const next = $derived(upNext());
  const station = $derived(stations.find((entry) => entry.id === radioState.stationId) ?? null);

  /** A one-second tick, so a stage that is slow reads as slow rather than as stuck. */
  let now = $state(Date.now());
  const RUNNING = new Set<RadioStatus>(["planning", "waiting", "writing", "queued", "rendering"]);

  function elapsed(song: RadioSong): string {
    if (!song.startedAt || !RUNNING.has(song.status)) return "";
    const seconds = Math.round((now - song.startedAt) / 1000);
    return seconds >= 1 ? `${seconds}s` : "";
  }

  const families = $derived.by(() => {
    const query = filter.trim().toLowerCase();
    const groups: { family: string; stations: RadioStation[] }[] = [];
    for (const entry of stations) {
      if (
        query &&
        !`${entry.name} ${entry.tagline} ${entry.family}`.toLowerCase().includes(query)
      ) {
        continue;
      }
      let group = groups.find((candidate) => candidate.family === entry.family);
      if (!group) {
        group = { family: entry.family, stations: [] };
        groups.push(group);
      }
      group.stations.push(entry);
    }
    return groups;
  });

  const STATUS: Record<RadioStatus, string> = {
    planning: "planning",
    waiting: "waiting for the model",
    writing: "writing lyrics",
    queued: "queued",
    rendering: "rendering",
    ready: "ready",
    playing: "playing",
    played: "played",
    failed: "failed",
  };

  async function refreshModels(): Promise<void> {
    modelError = null;
    try {
      models = await listModels(ollamaBase());
      if (!radioState.model && models.length) setModel(models[0].name);
    } catch (cause) {
      models = [];
      modelError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  onMount(() => {
    void refreshModels();
    const timer = window.setInterval(() => (now = Date.now()), 1000);
    return () => window.clearInterval(timer);
  });

  // Look up what the station already has whenever one is chosen — on mount too, for the station a
  // reload came back to — so its takes are listed before anything is playing.
  $effect(() => {
    if (radioState.stationId) void refreshAvailable();
  });

  // Follow the engine's current song, and only that song. The player is cleared when there is
  // nothing current, because a leftover source would let starting a station with an empty queue play
  // a take that is not in it — which reads as "playing" while the panel says it is still buffering.
  $effect(() => {
    const song = current;
    const url = song?.url ?? null;
    if (!audio) return;

    if (!url) {
      if (loadedUrl !== null) {
        loadedUrl = null;
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      audioError = null;
      wasOn = radioState.on;
      return;
    }

    const fresh = url !== loadedUrl;
    if (fresh) {
      loadedUrl = url;
      audioError = null;
      audio.src = url;
      audio.load();
    }
    // Play a new song, or a song already loaded when the radio is switched on.
    if (radioState.on && (fresh || !wasOn)) playCurrent();
    wasOn = radioState.on;
  });

  function choose(entry: RadioStation): void {
    selectStation(entry.id);
  }

  function toggle(): void {
    if (radioState.on) stopRadio();
    else void startRadio();
  }

  function playCurrent(): void {
    if (!audio) return;
    void audio
      .play()
      .then(() => (blocked = false))
      .catch(() => (blocked = true));
  }

  /** Open the take itself, which works even where the page is not allowed to embed the file. */
  function openCurrent(): void {
    const url = current?.url;
    if (url) window.open(url, "_blank", "noopener");
  }

  function when(at: number): string {
    return at ? new Date(at).toLocaleTimeString() : "";
  }
</script>

<div class="columns radio">
  <div class="column">
    <div class="stack">
      <div class="row">
        <strong>Stations</strong>
        <span class="chip">{stations.length}</span>
        <input
          class="draft-name"
          style="flex:1; min-width:8rem"
          placeholder="filter stations…"
          bind:value={filter}
        />
      </div>

      <p class="small muted" style="margin:0">
        A station is a genre's range, not one arrangement: each song draws its own instruments,
        production, groove, delivery and key from the station's pools, so consecutive songs differ
        and still sound like the station. Every take is a full 8-step render, saved under
        <code>output/radio/&lt;station&gt;/</code>.
      </p>

      {#each families as group (group.family)}
        <div class="section">
          <div class="section-title" style="padding:6px 0 2px">{group.family}</div>
          <div class="station-list">
            {#each group.stations as entry (entry.id)}
              <button
                class="station"
                class:selected={entry.id === radioState.stationId}
                onclick={() => choose(entry)}
                disabled={!ready}
              >
                <span class="station-name">{entry.name}</span>
                <span class="small muted">{entry.tagline}</span>
              </button>
            {/each}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <div class="column">
    <div class="stack">
      <div class="section">
        <div class="section-body">
          <div class="row" style="justify-content:space-between">
            <div class="row">
              <button class="primary" onclick={toggle} disabled={!ready || !radioState.stationId}>
                {radioState.on ? "stop" : "play"}
              </button>
              <button onclick={() => advance()} disabled={!radioState.on && !current}>
                skip
              </button>
              <button onclick={() => current && void downloadSong(current)} disabled={!current}>
                save / download
              </button>
              {#if blocked}
                <button onclick={playCurrent}>press to play</button>
              {/if}
            </div>
            <span class="small muted">
              {#if radioState.on}
                {next.length} queued
              {:else if radioState.stationId}
                stopped
              {:else}
                pick a station
              {/if}
            </span>
          </div>

          <audio
            bind:this={audio}
            controls
            preload="auto"
            onended={() => advance()}
            onerror={() => (audioError = audioFailure())}
          ></audio>

          {#if audioError}
            <div class="finding error">
              {audioError}.
              {#if current?.url}
                <button class="small" onclick={openCurrent}>open the file</button>
              {/if}
            </div>
          {/if}

          {#if current}
            <div>
              <div class="row" style="justify-content:space-between">
                <strong>{current.title}</strong>
                <span class="chip" class:meta={current.instrumental}>
                  {current.instrumental ? "instrumental" : "sung"}
                </span>
              </div>
              <div class="small muted">
                {station?.name ?? current.stationId}
                {#if current.bpm}· {current.bpm} BPM{/if}
                {#if current.seed}· seed <span class="mono">{current.seed}</span>{/if}
                {#if current.theme}· about “{current.theme}”{/if}
                {#if current.angle}· {current.angle}{/if}
              </div>
              {#if current.instrumental && current.plan && !radioState.instrumental}
                <div class="finding note">no lyric model was reachable, so this take is instrumental</div>
              {/if}
              <details style="margin-top:6px">
                <summary class="small muted">caption</summary>
                <code class="caption">{current.caption}</code>
              </details>
              {#if current.lyrics}
                <details>
                  <summary class="small muted">lyrics</summary>
                  <pre class="brief">{current.lyrics}</pre>
                </details>
              {/if}
              {#if current.file}
                <div class="small muted mono" style="margin-top:4px">
                  output/{current.file.subfolder}/{current.file.filename}
                </div>
              {:else if current.plan}
                <div class="small muted mono" style="margin-top:4px">
                  output/radio/{current.stationId}/{current.plan.song_id}
                </div>
              {/if}
            </div>
          {:else if radioState.stopped}
            <p class="small muted" style="margin:0">
              stopped after repeated failures; fix the target and press play
            </p>
          {:else if radioState.stationId && radioState.on}
            <p class="small muted" style="margin:0">
              buffering — nothing has been rendered for this station yet, so the first song is still
              rendering
            </p>
          {:else if radioState.stationId}
            <p class="small muted" style="margin:0">
              Press play to start the station. It begins on any songs already rendered for it, so
              there is usually nothing to wait for, and renders ahead from there.
            </p>
          {:else}
            <p class="small muted" style="margin:0">
              Choose a station on the left. Songs are rendered a few ahead, so there is always a
              next one.
            </p>
          {/if}

          {#if radioState.recovered}
            <div class="finding note">
              playing the {radioState.recovered} take{radioState.recovered === 1 ? "" : "s"} this
              station already had, oldest first; it renders new songs once they run down
            </div>
          {/if}

          {#if radioState.notice}
            <div class="finding note">{radioState.notice}</div>
          {/if}
          {#if radioState.lastError}
            <div class="finding error">{radioState.lastError}</div>
          {/if}
        </div>
      </div>

      <div class="section">
        <div class="section-body">
          <div class="row">
            <label class="row small" title="Render songs with no vocal, and never call the lyric model">
              <input
                type="checkbox"
                checked={radioState.instrumental}
                onchange={(event) => setInstrumental(event.currentTarget.checked)}
              />
              instrumental
            </label>
            <label class="row small">
              keep ahead
              <input
                type="number"
                min="1"
                max="6"
                style="width:4rem"
                value={radioState.bufferTarget}
                onchange={(event) => setBufferTarget(Number(event.currentTarget.value))}
              />
            </label>
          </div>
          <p class="small muted" style="margin:0">
            Instrumental applies to songs generated from here on; the few already rendering were
            planned without it. Set <em>keep ahead</em> to how many songs should be ready or
            rendering.
          </p>

          <div class="row">
            <label class="row small">
              lyric model
              <select
                value={radioState.model}
                onchange={(event) => setModel(event.currentTarget.value)}
              >
                {#if !models.length && radioState.model}
                  <option value={radioState.model}>{radioState.model}</option>
                {/if}
                {#if !radioState.model}
                  <option value="">none — instrumental</option>
                {/if}
                {#each models as entry (entry.name)}
                  <option value={entry.name}>{entry.name}</option>
                {/each}
              </select>
            </label>
            <button class="small" onclick={() => void refreshModels()}>reconnect</button>
          </div>
          {#if modelError}
            <div class="finding note">
              Nothing answered at <code>{ollamaBase()}</code>, so takes will be instrumental. The
              Generator panel's server setting applies here too.
            </div>
          {:else if !radioState.model}
            <div class="finding note">
              No model chosen, so takes will be instrumental. Pick one to have a lyric written for
              each song's subject.
            </div>
          {/if}
        </div>
      </div>

      <div class="section">
        <div class="section-body">
          <div class="section-title">Up next</div>
          {#if radioState.on}
            {#if next.length}
              {#each next as song (song.id)}
                {@const age = elapsed(song)}
                <div class="row queue-row">
                  <span class="small muted mono">{song.index}</span>
                  <span class="small">{song.title}</span>
                  {#if song.theme}<span class="small muted">· {song.theme}</span>{/if}
                  <span class="spacer" style="flex:1"></span>
                  {#if age}<span class="small muted">{age}</span>{/if}
                  {#if song.status === "ready" || song.status === "playing"}
                    <span class="chip" class:meta={song.instrumental}>
                      {song.instrumental ? "instrumental" : "sung"}
                    </span>
                  {/if}
                  <span class="chip" class:warn={song.status === "failed"}>{STATUS[song.status]}</span>
                </div>
              {/each}
            {:else}
              <p class="small muted" style="margin:0">nothing buffered yet</p>
            {/if}
          {:else if radioState.available.length}
            {#each radioState.available as take (take.id)}
              <div class="row queue-row">
                <span class="small">{take.title}</span>
                {#if take.theme}<span class="small muted">· {take.theme}</span>{/if}
                <span class="spacer" style="flex:1"></span>
                <span class="chip" class:meta={take.instrumental}>
                  {take.instrumental ? "instrumental" : "sung"}
                </span>
                <span class="chip">rendered</span>
              </div>
            {/each}
            <p class="small muted" style="margin:4px 0 0">
              already rendered for this station — press play to start on them, oldest first
            </p>
          {:else if radioState.availableBusy}
            <p class="small muted" style="margin:0">
              looking for songs this station already has…
            </p>
          {:else}
            <p class="small muted" style="margin:0">nothing buffered yet</p>
          {/if}
        </div>
      </div>

      <div class="section">
        <div class="section-body">
          <div class="section-title">Played on this station</div>
          {#if radioState.history.length}
            {#each radioState.history as song (song.id)}
              <div class="row queue-row">
                <span class="small">{song.title}</span>
                <span class="small muted">
                  {song.theme}{#if song.instrumental} · instrumental{/if}
                </span>
                <span class="spacer" style="flex:1"></span>
                <span class="small muted">{when(song.at)}</span>
                <button class="small" onclick={() => replay(song)} disabled={!song.file}>
                  replay
                </button>
                <button class="small" onclick={() => void downloadSong(song)} disabled={!song.file}>
                  save
                </button>
              </div>
            {/each}
          {:else}
            <p class="small muted" style="margin:0">
              Songs played from this station are listed here while the browser remembers them. The
              files themselves stay under <code>output/radio/{radioState.stationId}/</code>.
            </p>
          {/if}
        </div>
      </div>
    </div>
  </div>
</div>
