/**
 * Boots the text tier in the browser and is the only thing the UI calls.
 *
 * Pyodide is loaded from our own static directory rather than a CDN, and the repository is mounted
 * into the WASM filesystem at `/repo` — the layout the package's path constants already expect.
 * That mirrors exactly what `spikes/pyodide_text_core` proved works, instead of inventing a second
 * way to reach the same code.
 */
import type { PyodideInterface } from "pyodide";
import glueSource from "./core_glue.py?raw";
import { asset, withBuild } from "./paths";
import type {
  Artifacts,
  LyricReport,
  RadioPlan,
  RadioStation,
  RenderResult,
  Selections,
  SectionTagsFile,
  StructureTemplate,
  TagPools,
  TemplatesFile,
  TimelinePlan,
  VocabularyFile,
} from "./types";

const MOUNT = "/repo";

// `asset` moved to paths.ts, which the update watcher also needs and which the smoke test can
// import without a browser. Kept exported here because the app has always imported it from here.
export { asset } from "./paths";

export interface StaticData {
  vocabulary: VocabularyFile;
  templates: StructureTemplate[];
  /** The lyric tag pools, so the editor's lens and the checker read the same vocabulary. */
  pools: TagPools;
  /** The radio stations, so the picker and the planner read the same document. */
  stations: RadioStation[];
}

async function fetchBytes(url: string): Promise<Uint8Array> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
  return new Uint8Array(await response.arrayBuffer());
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
  return (await response.json()) as T;
}

/** The vocabulary, templates and tag pools, read once so the form, the lens and the checkers agree. */
export async function loadStaticData(): Promise<StaticData> {
  const vocabulary = await fetchJson<VocabularyFile>(
    withBuild(asset("repo/vocabulary/tag-bins.json")),
  );
  const templatesFile = await fetchJson<TemplatesFile>(
    withBuild(asset("repo/vocabulary/structure-templates.json")),
  );
  const tagFile = await fetchJson<SectionTagsFile>(
    withBuild(asset("repo/vocabulary/section-tags.json")),
  );
  const stationFile = await fetchJson<{ stations: RadioStation[] }>(
    withBuild(asset("repo/vocabulary/radio-stations.json")),
  );
  return {
    vocabulary,
    templates: templatesFile.templates,
    stations: stationFile.stations,
    pools: {
      sections: tagFile.sections,
      modifiers: tagFile.modifiers,
      transition_tags: tagFile.transition_tags,
      vocal_tags: tagFile.vocal_tags,
      energy_tags: tagFile.energy_tags,
      instrumental_section_tags: tagFile.instrumental_section_tags,
    },
  };
}

export class MusicMasterCore {
  private constructor(private readonly py: PyodideInterface) {}

  static async boot(report: (message: string) => void): Promise<MusicMasterCore> {
    report("starting the Python runtime");
    const runtimeUrl = asset("pyodide/pyodide.mjs");
    const runtime = (await import(/* @vite-ignore */ runtimeUrl)) as {
      loadPyodide: (options: { indexURL: string }) => Promise<PyodideInterface>;
    };
    const py = await runtime.loadPyodide({ indexURL: asset("pyodide/") });

    report("mounting the repository");
    // Stamped with the running build: a new build must not be handed the previous build's cached
    // repository, which is how a page ends up running new code against old data.
    const manifest = await fetchJson<string[]>(withBuild(asset("repo/manifest.json")));
    for (const rel of manifest) {
      const dest = `${MOUNT}/${rel}`;
      py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf("/")));
      py.FS.writeFile(dest, await fetchBytes(withBuild(asset(`repo/${rel}`))));
    }

    report("loading the text tier");
    py.runPython(glueSource);
    report("ready");
    return new MusicMasterCore(py);
  }

  /** Call one of the glue functions with a JSON payload and parse its JSON reply. */
  private call<T>(fn: string, payload: unknown): T {
    const entry = this.py.globals.get(fn);
    if (typeof entry !== "function") {
      throw new Error(`the text tier does not expose ${fn}()`);
    }
    return JSON.parse(entry(JSON.stringify(payload)) as string) as T;
  }

  render(selections: Selections): RenderResult {
    return this.call<RenderResult>("render_selections", selections);
  }

  plan(request: {
    template_id: string;
    bpm: number;
    duration_s?: number | null;
    profile_id?: string | null;
    /** Supplied so the budget uses the delivery band the selections imply, not the default. */
    selections?: Selections;
  }): TimelinePlan {
    return this.call<TimelinePlan>("plan", request);
  }

  checkLyric(request: {
    text: string;
    selections?: Selections;
    template_id?: string | null;
    bpm?: number | null;
  }): LyricReport {
    return this.call<LyricReport>("check_lyric", request);
  }

  /** A structurally correct empty lyric for the template: headers, tags and transitions only. */
  scaffold(request: { template_id: string }): { text: string } {
    return this.call<{ text: string }>("scaffold", request);
  }

  /** The writing brief, exactly as `structure_templates.py --brief` prints it. */
  brief(request: {
    template_id: string;
    bpm: number;
    duration_s?: number | null;
    selections?: Selections;
  }): { brief: string } {
    return this.call<{ brief: string }>("brief", request);
  }

  /**
   * The canonical prompt, the composition it pins, and the ComfyUI graph — built by the same
   * `musicmaster.prompt` the CLI uses, from what the page holds rather than from a song directory.
   */
  artifacts(request: {
    song_id: string;
    template_id: string;
    bpm: number;
    seed: number;
    selections: Selections;
    lyrics: string;
    brief: string;
    artist_references: string[];
    /** Where this take's companion files belong, for a take that is not a `songs/<id>/` song. */
    artifacts_dir?: string;
    /** The audio's path under ComfyUI's output directory. Defaults to `audio/<song_id>`. */
    filename_prefix?: string;
  }): Artifacts {
    return this.call<Artifacts>("artifacts", request);
  }

  /**
   * A full-length, coarse preview: the current caption plus one row per bin/option variant, all in
   * one graph. Cheap per caption because the LM runs once for the whole batch.
   */
  preview(request: {
    song_id: string;
    template_id: string;
    bpm: number;
    seed: number;
    selections: Selections;
    lyrics: string;
    brief: string;
    artist_references: string[];
    variants?: { bin: string; option: string }[];
    steps?: number;
    seconds?: number | null;
  }): { workflow: unknown; captions: string[]; names: string[] } {
    return this.call<{ workflow: unknown; captions: string[]; names: string[] }>(
      "preview",
      request,
    );
  }

  /**
   * One song of one radio station: the selections, tempo, key, form and subject.
   *
   * The same `musicmaster.radio.plan_song` the CLI and the tests use, so the page cannot invent a
   * station the document does not describe.
   */
  radioPlan(request: {
    station_id: string;
    index: number;
    seed?: number;
    instrumental?: boolean;
  }): RadioPlan {
    return this.call<RadioPlan>("radio_plan", request);
  }
}
