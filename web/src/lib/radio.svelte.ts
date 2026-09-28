/**
 * The radio engine.
 *
 * A station is a genre's range, and the page plays it: a few songs are always rendered ahead, the
 * next one starts when the current ends, and skipping promotes whatever is already ready. The
 * engine owns the queue, the per-song pipeline and the saved history; the panel owns the audio
 * element and the controls.
 *
 * One song goes through four stages, and each is somebody else's job:
 *
 *   plan      musicmaster.radio draws the selections, tempo, key and subject (the text tier)
 *   write     the model writes a lyric for that subject, or the take is instrumental
 *   render    ComfyUI runs the full 8-step graph into `output/radio/<station>/`
 *   play      the panel plays the file and the engine moves on when it ends
 *
 * Runes in a module are Svelte 5's way of holding state that outlives the component that shows it,
 * which is what lets a song keep rendering while the user is on another tab.
 *
 * A full render is slow, so the queue is deliberate: `bufferTarget` songs are kept either ready or
 * in flight, and playback starts as soon as the first is ready rather than waiting for all of them.
 * A station's finished songs are kept per station in browser storage, because the page cannot list
 * ComfyUI's output directory and the files themselves are what the user will go back to.
 */
import {
  fetchHistory,
  fetchOutcome,
  freshSeed,
  submitWorkflow,
  viewUrl,
  type OutputFile,
} from "./comfy";
import { generate, ollamaBase } from "./ollama";
import { buildPrompt } from "./prompt";
import { renderQueue } from "./render.svelte";
import { parseTakeName, takeKey, takesFromHistory, type TakeName } from "./takes";
import type { Artifacts, DirectiveRemoval, RadioPlan, RenderResult, Selections } from "./types";

export type RadioStatus =
  | "planning"
  | "waiting"
  | "writing"
  | "queued"
  | "rendering"
  | "ready"
  | "playing"
  | "played"
  | "failed";

export interface RadioSong {
  id: string;
  index: number;
  stationId: string;
  title: string;
  seed: number;
  status: RadioStatus;
  plan: RadioPlan | null;
  selections: Selections;
  bpm: number;
  caption: string;
  theme: string;
  lyrics: string;
  instrumental: boolean;
  lyricSource: "model" | "instrumental";
  jobId: string | null;
  waited: number;
  file: OutputFile | null;
  url: string | null;
  artifacts: Artifacts | null;
  error: string | null;
  at: number;
  /** When the song entered the pipeline, so the panel can show how long a stage has been running. */
  startedAt: number;
  abort: AbortController;
}

/** A finished song as it is kept in browser storage: enough to re-address and replay the file. */
export interface SavedRadioSong {
  id: string;
  index: number;
  stationId: string;
  title: string;
  seed: number;
  caption: string;
  theme: string;
  instrumental: boolean;
  file: OutputFile | null;
  at: number;
}

/**
 * What the engine needs from the page, registered by the app.
 *
 * The text tier is one Python instance behind `core`, and the app owns it; the engine asks for the
 * four things it needs rather than reaching into the app's state.
 */
export interface RadioHost {
  plan: (
    stationId: string,
    index: number,
    seed: number,
    instrumental: boolean,
  ) => RadioPlan | null;
  render: (selections: Selections) => RenderResult | null;
  brief: (templateId: string, bpm: number, selections: Selections) => string;
  /**
   * Take the brief's own directive lines back out of a draft, where the model copied one in.
   *
   * It is the text tier's `strip_directives`, so a radio take and a Lyrics-tab draft are repaired
   * by the same rule rather than by two implementations that drift.
   */
  cleanLyric: (text: string) => { text: string; removed: DirectiveRemoval[] };
  artifacts: (request: {
    song_id: string;
    template_id: string;
    bpm: number;
    seed: number;
    selections: Selections;
    lyrics: string;
    brief: string;
    artifacts_dir: string;
    filename_prefix: string;
  }) => Artifacts | null;
}

let host: RadioHost | null = null;

export function setRadioHost(fn: RadioHost | null): void {
  host = fn;
}

const SETTINGS_KEY = "mm.radio.settings";
const HISTORY_KEY = "mm.radio.history";
/** The Generator panel's model key, so the radio writes with whichever model is already chosen. */
const MODEL_KEY = "mm.ollama.model";
const HISTORY_PER_STATION = 24;
const MAX_CONSECUTIVE_FAILURES = 3;
/**
 * How long a lyric may take before the take gives up and goes instrumental.
 *
 * A model is optional, so it must never be able to stall the station: without a cap, one request
 * that never answers holds its buffer slot forever and nothing behind it ever plays.
 */
const LYRIC_TIMEOUT_MS = 150_000;

/** A promise that gives up after `ms`. The work is aborted by `onTimeout`, which knows what to cancel. */
function withTimeout<T>(
  work: Promise<T>,
  ms: number,
  message: string,
  onTimeout: () => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      onTimeout();
      reject(new Error(message));
    }, ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Lyric calls run one at a time.
 *
 * The buffer fills several songs at once, and a cloud model asked for several lyrics in parallel
 * answers them slowly, inconsistently, or not at all. The render is the long pole anyway, so there
 * is nothing to win by asking for them together — and one request at a time is what keeps the
 * lyric stage from being the thing that stalls a station.
 */
let lyricQueue: Promise<unknown> = Promise.resolve();

function serializeLyrics<T>(work: () => Promise<T>): Promise<T> {
  const next = lyricQueue.then(work, work);
  lyricQueue = next.catch(() => undefined);
  return next;
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage can be denied or full; losing radio history is not worth failing a render over */
  }
}

interface RadioSettings {
  stationId: string;
  instrumental: boolean;
  bufferTarget: number;
  model: string;
}

const saved = readJson<Partial<RadioSettings>>(SETTINGS_KEY, {});

export const radioState = $state({
  stationId: saved.stationId ?? "",
  /** Whether the stream is running. The panel owns the audio element; this owns the intent. */
  on: false,
  instrumental: saved.instrumental ?? false,
  /** Songs kept ready-or-in-flight ahead of the current one. */
  bufferTarget: saved.bufferTarget ?? 3,
  model: saved.model ?? readJson<string>(MODEL_KEY, ""),
  currentId: null as string | null,
  /** Songs created for this station that have not been played yet, including the current one. */
  queue: [] as RadioSong[],
  /** Played songs for the current station, newest first. */
  history: [] as SavedRadioSong[],
  /** How many already-rendered takes the last start began from, so the panel can say so. */
  recovered: 0,
  /**
   * The takes the current station already has, found when the station is chosen so the panel can
   * show them before anything is playing. Playback seeds from this list rather than looking again.
   */
  available: [] as SavedRadioSong[],
  availableBusy: false,
  lastError: null as string | null,
  /** A non-fatal message, such as the lyric model being unreachable and the take going instrumental. */
  notice: null as string | null,
  /**
   * Set when the lyric model failed, so the next songs go straight to instrumental instead of each
   * waiting on a call that is known to be failing. Cleared by choosing a model or pressing play.
   */
  lyricModelDown: false,
  /** Set when the radio stopped itself after repeated failures, so the panel can say why. */
  stopped: false,
});

/** A bump cancels every in-flight task from an earlier run, without touching ComfyUI's queue. */
let session = 0;
let failures = 0;
const indices: Record<string, number> = {};
let historyMap: Record<string, SavedRadioSong[]> = readJson(HISTORY_KEY, {});

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function persistSettings(): void {
  writeJson(SETTINGS_KEY, {
    stationId: radioState.stationId,
    instrumental: radioState.instrumental,
    bufferTarget: radioState.bufferTarget,
    model: radioState.model,
  });
}

/** Keep the current station's history in the map, so switching away does not lose it. */
function rememberHistory(): void {
  if (!radioState.stationId) return;
  historyMap = { ...historyMap, [radioState.stationId]: radioState.history };
  writeJson(HISTORY_KEY, historyMap);
}

function loadHistory(stationId: string): SavedRadioSong[] {
  const list = historyMap[stationId];
  return Array.isArray(list) ? list : [];
}

/** Trim what the model wrote down to the lyric: no fence, no preamble, tags intact. */
export function trimPreamble(text: string): string {
  let out = text.trim();
  out = out.replace(/^```[a-zA-Z]*\s*/, "").replace(/```\s*$/, "").trim();
  const first = out.indexOf("[");
  if (first > 0) out = out.slice(first).trim();
  return out;
}

function nextIndex(stationId: string): number {
  const index = indices[stationId] ?? 0;
  indices[stationId] = index + 1;
  return index;
}

function createSong(stationId: string): RadioSong {
  const index = nextIndex(stationId);
  return {
    id: `${stationId}-${index}-${Math.random().toString(36).slice(2, 8)}`,
    index,
    stationId,
    title: `…`,
    seed: freshSeed(),
    status: "planning",
    plan: null,
    selections: {},
    bpm: 0,
    caption: "",
    theme: "",
    lyrics: "",
    instrumental: radioState.instrumental,
    lyricSource: "instrumental",
    jobId: null,
    waited: 0,
    file: null,
    url: null,
    artifacts: null,
    error: null,
    at: 0,
    startedAt: Date.now(),
    abort: new AbortController(),
  };
}

/**
 * A song the page already has, as a queue entry. It has no plan and needs none: the file exists, so
 * playing it is the whole job, and the fields the panel shows come from the record that was kept.
 */
function songFromSaved(take: SavedRadioSong, status: RadioStatus): RadioSong {
  return {
    id: take.id,
    index: Number.isFinite(take.index) ? take.index : nextIndex(take.stationId),
    stationId: take.stationId,
    title: take.title,
    seed: take.seed,
    status,
    plan: null,
    selections: {},
    bpm: 0,
    caption: take.caption,
    theme: take.theme,
    lyrics: "",
    instrumental: take.instrumental,
    // The take's own kind, not a default: a recovered sung take is not an instrumental one.
    lyricSource: take.instrumental ? "instrumental" : "model",
    jobId: null,
    waited: 0,
    file: take.file,
    url: take.file ? viewUrl(renderQueue.target.base, take.file) : null,
    artifacts: null,
    error: null,
    at: take.at,
    startedAt: 0,
    abort: new AbortController(),
  };
}

/**
 * Put a song in the queue and hand back the one the queue actually holds.
 *
 * Svelte's state is proxied deeply and a write only reaches the UI if it goes through the proxy: a
 * song kept as a plain local updates its own fields while the panel keeps showing whatever it first
 * read — the elapsed timer ticks on, because it reads real state, and the status never moves. So
 * every mutation downstream goes through the value the queue holds, never the object pushed into it.
 */
function enqueue(song: RadioSong): RadioSong {
  radioState.queue.push(song);
  return radioState.queue[radioState.queue.length - 1];
}

function currentSong(): RadioSong | null {
  return radioState.queue.find((song) => song.id === radioState.currentId) ?? null;
}

function readyAfterCurrent(): RadioSong[] {
  const current = currentSong();
  return radioState.queue
    .filter((song) => song.status === "ready" && (!current || song.index > current.index))
    .sort((a, b) => a.index - b.index);
}

function inFlight(): number {
  return radioState.queue.filter((song) =>
    ["planning", "waiting", "writing", "queued", "rendering"].includes(song.status),
  ).length;
}

/**
 * One song's whole pipeline. Every await is followed by a session check, so a stopped or switched
 * radio does not play a song the user has moved on from.
 */
async function produce(song: RadioSong, token: number): Promise<void> {
  if (!host) {
    song.status = "failed";
    song.error = "the text tier is not ready";
    return;
  }
  try {
    // The model is optional. With none chosen, unreachable, or the instrumental box ticked, the
    // take is planned as an instrumental from the start, so the caption describes the singer who is
    // actually there: none.
    const wantsVocal =
      !song.instrumental && Boolean(radioState.model) && !radioState.lyricModelDown;
    let plan = host.plan(song.stationId, song.index, song.seed, !wantsVocal);
    if (!plan) throw new Error("the text tier could not plan the song");
    song.plan = plan;
    song.instrumental = plan.instrumental;
    song.title = plan.title;
    song.selections = plan.selections;
    song.bpm = plan.bpm;
    song.theme = plan.theme;
    song.caption = host.render(plan.selections)?.string ?? "";
    if (token !== session) return;

    if (plan.instrumental) {
      song.lyrics = "";
      song.lyricSource = "instrumental";
    } else {
      // Waiting for the one-at-a-time lyric slot is not the same as being written; saying which is
      // the difference between a queue and a thing that looks stuck.
      song.status = "waiting";
      // Its own controller, so a timeout can abandon this one request without looking like a stop.
      const lyric = new AbortController();
      const stopIt = (): void => lyric.abort();
      song.abort.signal.addEventListener("abort", stopIt, { once: true });
      try {
        const brief = host.brief(plan.template_id, plan.bpm, plan.selections);
        const prompt = buildPrompt({ brief, caption: song.caption, theme: plan.theme });
        const text = await withTimeout(
          serializeLyrics(() => {
            song.status = "writing";
            return generate({
              model: radioState.model,
              base: ollamaBase(),
              prompt,
              signal: lyric.signal,
              // The lyric is the whole answer; a thinking model's reasoning is tens of seconds that
              // nothing downstream can use.
              think: false,
            });
          }),
          LYRIC_TIMEOUT_MS,
          "the lyric model did not answer in time",
          stopIt,
        );
        if (token !== session) return;
        song.lyrics = host.cleanLyric(trimPreamble(text)).text;
        if (!song.lyrics) throw new Error("the model wrote nothing");
        song.lyricSource = "model";
        song.error = null;
        radioState.notice = null;
      } catch (cause) {
        if (song.abort.signal.aborted) throw cause;
        // A station that cannot reach a model still plays, instrumentally: the song is re-planned
        // so its caption stops describing a voice that will not be in the audio. One failure is
        // enough to stop asking for every later song for this run.
        radioState.lyricModelDown = true;
        const fallback = host.plan(song.stationId, song.index, song.seed, true);
        if (fallback) {
          plan = fallback;
          song.plan = fallback;
          song.instrumental = true;
          song.selections = fallback.selections;
          song.bpm = fallback.bpm;
          song.caption = host.render(fallback.selections)?.string ?? song.caption;
        }
        song.lyrics = "";
        song.lyricSource = "instrumental";
        radioState.notice = `no lyric model reachable (${
          cause instanceof Error ? cause.message : String(cause)
        }); playing instrumentally`;
      } finally {
        song.abort.signal.removeEventListener("abort", stopIt);
      }
    }

    song.status = "queued";
    const artifacts = host.artifacts({
      song_id: plan.song_id,
      template_id: plan.template_id,
      bpm: plan.bpm,
      seed: song.seed,
      selections: plan.selections,
      lyrics: song.lyrics,
      brief: host.brief(plan.template_id, plan.bpm, plan.selections),
      // The text tier decides where a radio take lives: under its station, with an instrumental
      // take marked in the file name so the output directory classifies itself.
      artifacts_dir: plan.artifacts_dir,
      filename_prefix: plan.filename_prefix,
    });
    if (!artifacts) throw new Error("the graph could not be built");
    song.artifacts = artifacts;

    const started = await submitWorkflow(renderQueue.target, artifacts.workflow);
    if (token !== session) return;
    song.jobId = started.jobId;
    song.status = "rendering";

    const began = Date.now();
    for (;;) {
      await sleep(3000);
      if (token !== session) return;
      song.waited = Math.round((Date.now() - began) / 1000);
      const state = await fetchOutcome(renderQueue.target, started.pollUrl);
      if (!state.done) {
        if (song.waited > 1200) throw new Error("gave up waiting after 20 minutes");
        continue;
      }
      if (!state.ok) throw new Error(`the render ${state.status}`);
      const output = state.outputs[0];
      if (!output) throw new Error("the render finished but reported no audio file");
      if (!output.url && !output.file) {
        throw new Error(
          "this target does not return a playable URL; point the radio at a native ComfyUI",
        );
      }
      if (token !== session) return;
      song.file = output.file ?? null;
      song.url = output.url ?? (output.file ? viewUrl(renderQueue.target.base, output.file) : null);
      song.status = "ready";
      song.at = Date.now();
      failures = 0;
      if (!radioState.currentId) promoteNext();
      ensure();
      return;
    }
  } catch (cause) {
    if (token !== session) return;
    song.status = "failed";
    song.error = cause instanceof Error ? cause.message : String(cause);
    radioState.lastError = song.error;
    failures += 1;
    if (failures >= MAX_CONSECUTIVE_FAILURES) {
      radioState.on = false;
      radioState.stopped = true;
    }
    ensure();
  }
}

/** Keep the buffer full: spawn songs until enough are ready or already on their way. */
function ensure(): void {
  if (!radioState.on || !host || !radioState.stationId || radioState.stopped) return;
  const token = session;
  let guard = 0;
  while (readyAfterCurrent().length + inFlight() < radioState.bufferTarget && guard < 12) {
    guard += 1;
    const song = enqueue(createSong(radioState.stationId));
    void produce(song, token).finally(() => {
      if (token === session) ensure();
    });
  }
}

/** Make the earliest ready song current, if nothing is playing. */
function promoteNext(): void {
  if (radioState.currentId) {
    const current = currentSong();
    if (current && current.status === "playing") return;
  }
  const next = readyAfterCurrent()[0] ?? radioState.queue.find((song) => song.status === "ready");
  if (!next) {
    radioState.currentId = null;
    return;
  }
  next.status = "playing";
  radioState.currentId = next.id;
}

export function selectStation(stationId: string): void {
  if (stationId === radioState.stationId) return;
  rememberHistory();
  hardStop();
  radioState.stationId = stationId;
  radioState.history = loadHistory(stationId);
  radioState.lastError = null;
  radioState.available = [];
  persistSettings();
  void refreshAvailable();
}

/**
 * Find the takes this station already has, without starting anything.
 *
 * The panel shows them as what is up next before play is pressed, which is what makes "pressing
 * play plays" something to see rather than a promise, and a start seeds from the same list instead
 * of asking the renderer a second time.
 */
export async function refreshAvailable(): Promise<void> {
  const stationId = radioState.stationId;
  if (!stationId) return;
  radioState.availableBusy = true;
  try {
    const found = await discoverExisting(stationId);
    if (stationId !== radioState.stationId) return;
    radioState.available = found;
  } finally {
    if (stationId === radioState.stationId) radioState.availableBusy = false;
  }
}

function hardStop(): void {
  radioState.on = false;
  session += 1;
  // Abandon any model call in flight; a render already queued on ComfyUI will finish, and its
  // file is still on disk under the station, but the page stops waiting for it.
  for (const song of radioState.queue) song.abort.abort();
  radioState.queue = [];
  radioState.currentId = null;
  radioState.recovered = 0;
}

/**
 * The takes this station already has, from the page's own record and the renderer's memory.
 *
 * The saved list is the durable one; the renderer's history is what catches takes the page never
 * recorded — one this browser had not played yet, or one rendered from somewhere else. They are
 * merged by file, so a take both know about is queued once, and ordered by the renderer's own
 * numbering rather than by either list's idea of it.
 */
async function discoverExisting(stationId: string): Promise<SavedRadioSong[]> {
  const found = new Map<string, { take: SavedRadioSong; name: TakeName }>();
  const remember = (key: string, take: SavedRadioSong, name: TakeName): void => {
    if (!found.has(key)) found.set(key, { take, name });
  };

  for (const saved of radioState.history) {
    const parsed = saved.file ? parseTakeName(stationId, saved.file.filename) : null;
    if (!saved.file || !parsed) continue;
    remember(takeKey(saved.file), saved, parsed);
  }

  try {
    const history = await fetchHistory(renderQueue.target);
    for (const take of takesFromHistory(history, `radio/${stationId}`)) {
      // A file under this station that does not carry the take naming is not one of ours to place.
      const parsed = parseTakeName(stationId, take.filename);
      if (!parsed) continue;
      const file = { filename: take.filename, subfolder: take.subfolder, type: take.type };
      remember(takeKey(file), {
        id: `found:${takeKey(file)}`,
        index: 0,
        stationId,
        title: `${stationId} #${parsed.order}`,
        seed: take.seed ?? 0,
        caption: take.caption,
        theme: "",
        instrumental: parsed.instrumental,
        file,
        at: 0,
      }, parsed);
    }
  } catch {
    /* the renderer's history is a bonus; what the page saved is the durable record */
  }

  return [...found.values()]
    .sort(
      (a, b) =>
        a.name.order - b.name.order ||
        (a.take.file?.filename ?? "").localeCompare(b.take.file?.filename ?? ""),
    )
    // The queue orders by this number, so a recovered take is numbered by the render order its file
    // name already carries rather than by a second counter of our own.
    .map(({ take }, index) => ({ ...take, index }));
}

/** How many of a station's own takes to queue at once, so a huge folder cannot flood the list. */
const SEED_LIMIT = 50;

/**
 * Queue the station's existing takes, so pressing play plays rather than waits.
 *
 * They go in oldest first, and all of them: playback starts at the beginning of what the station
 * already has, and nothing new is rendered until that repertoire runs down to the look-ahead.
 * Seeding only the last few started playback at the end of the repertoire, passed over the earlier
 * takes, and rendered replacements while they sat unplayed.
 */
function seedSongs(existing: SavedRadioSong[]): number {
  if (!existing.length) return 0;
  const chosen = existing.slice(0, SEED_LIMIT);
  const highest = existing.reduce(
    (top, take) => Math.max(top, Number.isFinite(take.index) ? take.index : 0),
    0,
  );
  // New songs continue the numbering, so they sort after every recovered take.
  indices[radioState.stationId] = Math.max(indices[radioState.stationId] ?? 0, highest + 1);
  for (const take of chosen) enqueue(songFromSaved(take, "ready"));
  return chosen.length;
}

export async function startRadio(): Promise<void> {
  if (!host || !radioState.stationId || radioState.on) return;
  radioState.on = true;
  radioState.stopped = false;
  radioState.lastError = null;
  radioState.notice = null;
  // Pressing play is also "try the model again", so a temporary outage does not stick for the tab.
  radioState.lyricModelDown = false;
  radioState.recovered = 0;
  failures = 0;
  session += 1;
  const token = session;

  // What the station already has comes first. It was found when the station was chosen, so pressing
  // play usually does not wait for a request at all; if it was not, this finds it now.
  const existing = radioState.available.length
    ? radioState.available
    : await discoverExisting(radioState.stationId);
  if (token !== session) return;
  radioState.recovered = seedSongs(existing);

  promoteNext();
  ensure();
}

export function stopRadio(): void {
  hardStop();
}

export function toggleRadio(): void {
  if (radioState.on) stopRadio();
  else void startRadio();
}

/** Skip to the next ready song. The current one goes to the history and keeps its file. */
export function advance(): void {
  const current = currentSong();
  if (current) {
    current.status = "played";
    // A recovered take is already in the history; moving it to the front rather than adding it
    // again keeps the list a record of what was played, not of how many times play was pressed.
    const entry = toSaved(current);
    radioState.history = [
      entry,
      ...radioState.history.filter(
        (saved) =>
          saved.id !== entry.id &&
          !(saved.file && entry.file && saved.file.filename === entry.file.filename),
      ),
    ].slice(0, HISTORY_PER_STATION);
    rememberHistory();
  }
  radioState.queue = radioState.queue.filter(
    (song) => song.status !== "played" && song.status !== "failed",
  );
  radioState.currentId = null;
  promoteNext();
  ensure();
}

export function setInstrumental(value: boolean): void {
  radioState.instrumental = value;
  persistSettings();
}

export function setBufferTarget(value: number): void {
  radioState.bufferTarget = Math.max(1, Math.min(6, Math.round(value)));
  persistSettings();
  ensure();
}

export function setModel(name: string): void {
  radioState.model = name;
  radioState.lyricModelDown = false;
  try {
    if (name) localStorage.setItem(MODEL_KEY, name);
  } catch {
    /* not remembering is an acceptable outcome */
  }
  persistSettings();
}

/** The song the panel should be playing, if any. */
export function nowPlaying(): RadioSong | null {
  const current = currentSong();
  return current && (current.status === "playing" || current.status === "ready") ? current : null;
}

export function upNext(): RadioSong[] {
  const current = currentSong();
  return radioState.queue
    .filter((song) => song.status !== "played" && song.status !== "failed" && song.id !== current?.id)
    .sort((a, b) => a.index - b.index);
}

/** A finished song, ready to be kept in browser storage. */
function toSaved(song: RadioSong): SavedRadioSong {
  return {
    id: song.id,
    index: song.index,
    stationId: song.stationId,
    title: song.title,
    seed: song.seed,
    caption: song.caption,
    theme: song.theme,
    instrumental: song.instrumental,
    file: song.file,
    at: song.at,
  };
}

/** Play a song from the history again. It rejoins the queue as ready and becomes current. */
export function replay(saved: SavedRadioSong): void {
  if (!saved.file) {
    radioState.lastError = "that take has no file recorded, so it cannot be re-addressed";
    return;
  }
  const song = enqueue(songFromSaved(saved, "playing"));
  const current = currentSong();
  if (current && current.status === "playing") current.status = "ready";
  radioState.currentId = song.id;
}

/** The file name a download should carry, from the render's own name where there is one. */
export function downloadName(song: RadioSong | SavedRadioSong): string {
  return song.file?.filename || `${song.stationId}-${String(song.index).padStart(3, "0")}.mp3`;
}

function triggerDownload(href: string, name: string): void {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/**
 * Save the audio to the user's machine. It is already on disk under the station's directory; this
 * is the copy in the user's downloads, which is what "save this song" means from a page.
 */
export async function downloadSong(song: RadioSong | SavedRadioSong): Promise<void> {
  const url =
    "url" in song && song.url
      ? song.url
      : song.file
        ? viewUrl(renderQueue.target.base, song.file)
        : null;
  if (!url) {
    radioState.lastError = "nothing to download yet";
    return;
  }
  const name = downloadName(song);
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(String(response.status));
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    triggerDownload(href, name);
    setTimeout(() => URL.revokeObjectURL(href), 10_000);
  } catch {
    // Cross-origin and unproxied targets will not let the page read the bytes; the file is still
    // reachable, so open it rather than failing silently.
    window.open(url, "_blank");
  }
}
