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
    replay,
    selectStation,
    setBufferTarget,
    setInstrumental,
    setModel,
    startRadio,
    stopRadio,
    upNext,
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

  let models = $state<OllamaModel[]>([]);
  let modelError = $state<string | null>(null);

  const current = $derived(nowPlaying());
  const next = $derived(upNext());
  const station = $derived(stations.find((entry) => entry.id === radioState.stationId) ?? null);

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
  });

  // Follow the engine's current song: load it, and play it while the radio is on. `play()` is
  // rejected until the page has been clicked, so the rejection is surfaced as a play button rather
  // than as silence.
  $effect(() => {
    const song = current;
    const url = song?.url ?? null;
    if (!audio) return;
    if (url && url !== loadedUrl) {
      loadedUrl = url;
      audio.src = url;
      audio.load();
      if (radioState.on) playCurrent();
    } else if (radioState.on && !wasOn) {
      playCurrent();
    }
    if (!radioState.on && wasOn) audio.pause();
    wasOn = radioState.on;
  });

  function choose(entry: RadioStation): void {
    selectStation(entry.id);
  }

  function toggle(): void {
    if (radioState.on) stopRadio();
    else startRadio();
  }

  function playCurrent(): void {
    if (!audio) return;
    void audio
      .play()
      .then(() => (blocked = false))
      .catch(() => (blocked = true));
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

          <audio bind:this={audio} controls onended={() => advance()} preload="auto"></audio>

          {#if current}
            <div>
              <div class="row" style="justify-content:space-between">
                <strong>{current.title}</strong>
                <span class="chip" class:meta={current.lyricSource === "instrumental"}>
                  {current.lyricSource === "instrumental" ? "instrumental" : "sung"}
                </span>
              </div>
              <div class="small muted">
                {station?.name ?? current.stationId} · {current.bpm} BPM · seed
                <span class="mono">{current.seed}</span>
                {#if current.theme}· about “{current.theme}”{/if}
              </div>
              {#if current.instrumental && !radioState.instrumental}
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
              <div class="small muted mono" style="margin-top:4px">
                output/radio/{current.stationId}/{current.plan?.song_id ?? ""}
              </div>
            </div>
          {:else if radioState.stationId}
            <p class="small muted" style="margin:0">
              {radioState.stopped
                ? "stopped after repeated failures; fix the target and press play"
                : "buffering — the next song is still rendering, and this one starts when it is done"}
            </p>
          {:else}
            <p class="small muted" style="margin:0">
              Choose a station on the left. Songs are rendered a few ahead, so there is always a
              next one.
            </p>
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
          {#if next.length}
            {#each next as song (song.id)}
              <div class="row queue-row">
                <span class="small muted mono">{song.index}</span>
                <span class="small">{song.title}</span>
                <span class="spacer" style="flex:1"></span>
                <span class="chip" class:warn={song.status === "failed"}>{STATUS[song.status]}</span>
              </div>
            {/each}
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
