// Verify the browser glue against the CLI, without a browser.
//
// The page adds one piece of new Python -- `src/lib/core_glue.py` -- so the question worth answering
// is whether it returns what the package returns for the same input. This runs both: the glue inside
// Pyodide with the *built* repository mounted, and the same calls natively through `musicmaster`.
//
//   npm run build && node scripts/smoke.mjs
//
// It reads `dist/repo/` rather than the working tree, so it also checks that the build shipped the
// files the page will ask for. It is not a browser: it says nothing about rendering, layout, or the
// Pyodide bootstrap inside a page. It says the plumbing is right, which a build cannot.

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { loadPyodide } from "pyodide";
import { parseFindings, slotFor } from "../src/lib/lens.ts";
import { presetFor, freshSeed, previewSeed, describeMessages } from "../src/lib/comfy.ts";
import { encodeWav, monoFrom } from "../src/lib/stereo.ts";
import { freeName, stable } from "../src/lib/draft.ts";
import { editorTheme } from "../src/lib/lens.ts";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { proxy } from "svelte/internal/client";
import { generate } from "../src/lib/ollama.ts";
import { reloadUrl, stamp } from "../src/lib/paths.ts";
import { buildPrompt } from "../src/lib/prompt.ts";
import { parseTakeName, takesFromHistory } from "../src/lib/takes.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const REPO = path.resolve(WEB, "..");
const DIST = path.join(WEB, "dist");
const SONG = "rap-metal-groove";

const failures = [];
function check(label, actual, expected) {
  const same = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`  ${same ? "ok  " : "FAIL"}  ${label}`);
  if (!same) {
    failures.push(label);
    console.log(`        native: ${JSON.stringify(expected)?.slice(0, 300)}`);
    console.log(`        glue:   ${JSON.stringify(actual)?.slice(0, 300)}`);
  }
}

if (!fs.existsSync(path.join(DIST, "repo", "manifest.json"))) {
  console.error("dist/ is missing; run `npm run build` first.");
  process.exit(1);
}

// --- The native control ------------------------------------------------------------------

// A draft carrying every leak the lyric repair exists for: a brief directive, tags written without
// brackets (one the grammar takes on its own line and one it does not), an instrumental note, and a
// transition glued to the last lyric line. The native control and the page's glue must repair it
// identically, which also proves the glue can read the vocabulary the repair needs.
const DIRTY_LYRIC = [
  "[Verse 1]",
  "Low energy",
  "Melodic hook",
  "The cassette won't turn but the reels still hold",
  "hard cut",
  "",
  "[Chorus]",
  "(instrumental)",
  "Energy 3/5",
].join("\n");

const NATIVE = `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from musicmaster import jev, lyrics, oracle, prompt, radio, render, spec, timeline
vocab = render.load_vocabulary()
selections = json.load(open(${JSON.stringify(path.join(REPO, "songs", SONG, "selections.json"))}))["selections"]
song = json.load(open(${JSON.stringify(path.join(REPO, "songs", SONG, "song.json"))}))
st = timeline.load(timeline.SECTION_TAGS_PATH)
doc = timeline.load(timeline.TEMPLATES_PATH)
rates = timeline.load_delivery_rates()
profile = timeline.profile_for_vocals(selections, rates)
template = {t["id"]: t for t in doc["templates"]}[song["template_id"]]
plan = timeline.build_timeline(template, song["bpm"], st, profile, doc)
built = prompt.build({
    "song_id": song["song_id"],
    "template_id": song["template_id"],
    "bpm": song["bpm"],
    "seed": song["seed"],
    "selections": selections,
    "lyrics": open(${JSON.stringify(path.join(REPO, "songs", SONG, "lyrics.md"))}).read(),
    "brief": open(${JSON.stringify(path.join(REPO, "songs", SONG, "brief.md"))}).read(),
    "artist_references": song.get("artist_references", []),
    "vocabulary_path": ${JSON.stringify(path.join(REPO, "vocabulary", "tag-bins.json"))},
    "vocabulary": vocab,
    "section_tags": st,
    "templates_doc": doc,
})
radio_plan = radio.plan_song(radio.load_stations(), "neon-drive", 3, seed=12345, vocab=vocab)
jev_draft = {
    "selections": selections,
    "bpm": song["bpm"],
    "duration_s": None,
    "template_id": song["template_id"],
    "lyrics": open(${JSON.stringify(path.join(REPO, "songs", SONG, "lyrics.md"))}).read(),
    "caption": render.render(vocab, selections)["string"],
    "theme": "leaving a coastal town in autumn",
    "artist_references": song.get("artist_references", []),
}
jev_built = spec.interpret(jev_draft, vocab=vocab)
print(json.dumps({
    "render": {**render.render(vocab, selections),
               "problems": sorted(render.coherence_check(vocab, selections))},
    "profile": profile["label"],
    "plan": {"totals": plan["totals"], "rows": len(plan["rows"]),
             "profile_label": plan["profile_label"]},
    "artifacts": {"prompt_sha256": built["prompt_sha256"],
                  "prompt_text": prompt.serialise(built["prompt"]),
                  "workflow_text": prompt.serialise(built["workflow"])},
    "radio": {"plan": radio_plan,
              "caption": render.render(vocab, radio_plan["selections"])["string"]},
    "jev": {"spec": jev_built["spec"],
            "request": jev.build_request(jev_built["state"], oracle.build_questions(jev_built["spec"]))},
    "clean": lyrics.strip_directives(${JSON.stringify(DIRTY_LYRIC)}),
}))
`;

const native = JSON.parse(execFileSync("python3", ["-c", NATIVE], { encoding: "utf8" }));
const selections = JSON.parse(
  fs.readFileSync(path.join(REPO, "songs", SONG, "selections.json"), "utf8"),
).selections;
const song = JSON.parse(fs.readFileSync(path.join(REPO, "songs", SONG, "song.json"), "utf8"));

// --- The same work inside Pyodide, over the built artifacts -------------------------------

const py = await loadPyodide();
const manifest = JSON.parse(fs.readFileSync(path.join(DIST, "repo", "manifest.json"), "utf8"));
for (const rel of manifest) {
  const dest = `/repo/${rel}`;
  py.FS.mkdirTree(path.posix.dirname(dest));
  py.FS.writeFile(dest, fs.readFileSync(path.join(DIST, "repo", rel)));
}
py.runPython(fs.readFileSync(path.join(WEB, "src/lib/core_glue.py"), "utf8"));

const call = (fn, payload) => JSON.parse(py.globals.get(fn)(JSON.stringify(payload)));

const rendered = call("render_selections", selections);
const plan = call("plan", { template_id: song.template_id, bpm: song.bpm, selections });

console.log(`\nglue vs native for ${SONG} (${manifest.length} files from dist/repo):\n`);
check("caption tag list", rendered.tags, native.render.tags);
check("caption string", rendered.string, native.render.string);
check("tags dropped by the budget", rendered.omitted, native.render.omitted);
check("negative conditioning", rendered.negatives, native.render.negatives);
check("coherence problems", [...rendered.problems].sort(), native.render.problems);
check("delivery profile", rendered.profile, native.profile);
check("planned sections", plan.rows.length, native.plan.rows);
check("timeline totals", plan.totals, native.plan.totals);

// The repair reads the tag vocabularies, which the page gets from the mounted repository, so this
// checks both the repair and that the glue can reach the files it needs. The report is part of the
// result: what the repair dropped and what it rewrote, never a silent edit.
const cleaned = call("clean_lyric", { text: DIRTY_LYRIC });
check("the lyric repair matches the CLI", cleaned, native.clean);
check("the repair reports what it dropped", cleaned.removed.length, 3);
check("the repair reports what it rewrote", cleaned.changed.map((entry) => entry.replacement),
  ["[Low energy]", "[hard cut]"]);

// --- The render path: the browser's artifacts must be the ones the CLI writes -----------------

const lyricsText = fs.readFileSync(path.join(DIST, "repo", "songs", SONG, "lyrics.md"), "utf8");
const briefText = fs.readFileSync(path.join(DIST, "repo", "songs", SONG, "brief.md"), "utf8");

// --- The oracle path: one spec and one request, from the same text tier in both runtimes -------

// The page derives its own requirements from what it holds, and what leaves the machine is
// whatever this produces. Asserting it against the CLI is the same claim the prompt artifact
// makes: the page cannot ask a question the repository does not describe.
const jevDraft = {
  selections,
  bpm: song.bpm,
  duration_s: null,
  template_id: song.template_id,
  lyrics: lyricsText,
  caption: rendered.string,
  theme: "leaving a coastal town in autumn",
  artist_references: song.artist_references ?? [],
};
const jevBuilt = call("jev_request", jevDraft);
check("derived requirement spec", jevBuilt.spec, native.jev.spec);
check("the request the oracle would be sent", jevBuilt.request, native.jev.request);
const artifact = call("artifacts", {
  song_id: song.song_id,
  template_id: song.template_id,
  bpm: song.bpm,
  seed: song.seed,
  selections,
  lyrics: lyricsText,
  brief: briefText,
  artist_references: song.artist_references ?? [],
});

console.log("\nrender path:\n");
check("the prompt hash matches the CLI", artifact.prompt_sha256, native.artifacts.prompt_sha256);
check("prompt.json matches the CLI", artifact.prompt_text, native.artifacts.prompt_text);
check("workflow.json matches the CLI", artifact.workflow_text, native.artifacts.workflow_text);
check(
  "the workflow carries the seed it was built with",
  JSON.parse(artifact.workflow_text)["8"]["inputs"]["seed"],
  song.seed,
);
check(
  "the prompt pins the composition it ships",
  artifact.prompt.form.composition_sha256,
  createHash("sha256").update(artifact.composition_text).digest("hex"),
);

// A new take is the same prompt with a different seed; a new song is the same machinery with
// nothing in it yet. Both must go through the one builder rather than a second code path.
const reseeded = call("artifacts", {
  song_id: song.song_id,
  template_id: song.template_id,
  bpm: song.bpm,
  seed: song.seed + 1,
  selections,
  lyrics: lyricsText,
  brief: briefText,
  artist_references: song.artist_references ?? [],
});
check(
  "a new seed reaches the graph",
  JSON.parse(reseeded.workflow_text)["8"]["inputs"]["seed"],
  song.seed + 1,
);
check("a new seed changes the prompt hash", reseeded.prompt_sha256 !== artifact.prompt_sha256, true);
// Why a render picks a fresh seed: the same graph reproduces the same take. Of the eighteen takes on
// disk, the only two sharing a graph came out byte-identical, and every other pair differed because
// something in the inputs had. A pinned seed re-renders one take rather than making a new one.
check(
  "a different seed makes a different graph, so each take has its own address",
  reseeded.workflow_text !== artifact.workflow_text,
  true,
);
const generated = freshSeed();
check(
  "a generated seed is usable as a ComfyUI seed",
  Number.isInteger(generated) && generated > 0 && generated <= 0x7fffffff,
  true,
);
// A preview and an A/B exist to explain a take, so they hold that take's arrangement: a seed the
// render path generated, or one typed into the field, does not reach a preview until a take has
// actually been rendered with it. Before any take there is nothing to hold and the page's seed is
// what a render would send.
check("a preview before any take uses the page's seed", previewSeed(null, 4409), 4409);
check("a preview holds the last take's seed", previewSeed(777, 4409), 777);
check(
  "a seed that produced no take does not reach a preview",
  previewSeed(777, 12345),
  777,
);

// A preview row is its own solo graph so the page can cache and reuse it. The batch node keeps one
// generator for a whole batch, so a caption's audio depends on what rode along with it; a row that
// cannot be reproduced on its own is a row that cannot be cached. And the base row of an A/B has to
// be the same graph as a plain preview of the caption, or the cache would never hit.
const previewRequest = {
  song_id: song.song_id,
  template_id: song.template_id,
  bpm: song.bpm,
  seed: song.seed,
  selections,
  lyrics: lyricsText,
  brief: briefText,
  artist_references: song.artist_references ?? [],
};
const plainPreview = call("preview", { ...previewRequest, steps: 2 });
const abPreview = call("preview", {
  ...previewRequest,
  steps: 2,
  variants: [{ bin: "drums", option: "taiko" }],
});
check("a plain preview is one row", plainPreview.rows.length, 1);
check("a preview row is named", plainPreview.rows[0].name, "current");
check("an A/B is the caption plus the variant", abPreview.rows.map((row) => row.name),
  ["current", "drums:taiko"]);
for (const row of abPreview.rows) {
  const graph = row.workflow;
  check(`preview row ${row.name} renders a batch of one`, graph["6"]["inputs"]["batch_size"], 1);
  check(`preview row ${row.name} carries its caption alone`,
    graph["11"]["inputs"]["captions"].includes("\n"), false);
}
check("the variant row's caption differs from the caption",
  abPreview.rows[1].caption !== abPreview.rows[0].caption, true);
check("the A of an A/B is the graph a plain preview renders",
  JSON.stringify(abPreview.rows[0].workflow), JSON.stringify(plainPreview.rows[0].workflow));

// --- The simultaneous A/B ----------------------------------------------------------------------
//
// The merged track is a stereo WAV built in the page: each take downmixed to mono, the current
// caption on the left and the variant on the right. The channel arithmetic is plain and is checked
// here; only the decode needs a browser.

console.log("\nstereo split:\n");
{
  const left = Float32Array.from([1, -1, 0]);
  const right = Float32Array.from([-1, 1, 0]);
  const bytes = encodeWav([left, right], 44100);
  const view = new DataView(bytes);
  const text = (offset, length) => String.fromCharCode(...new Uint8Array(bytes, offset, length));
  check("the merged track is a WAV", [text(0, 4), text(8, 4)], ["RIFF", "WAVE"]);
  check(
    "the merged track is stereo 16-bit PCM at the clip's rate",
    [view.getUint16(22, true), view.getUint16(34, true), view.getUint32(24, true)],
    [2, 16, 44100],
  );
  check("the data chunk holds every frame of both channels", view.getUint32(40, true), 3 * 2 * 2);
  check(
    "A lands on the left and B on the right",
    [0, 1, 2, 3, 4, 5].map((i) => view.getInt16(44 + i * 2, true)),
    [0x7fff, -0x8000, -0x8000, 0x7fff, 0, 0],
  );
  check(
    "a downmix averages the channels",
    [...monoFrom([Float32Array.from([1, 0]), Float32Array.from([0, 1])])],
    [0.5, 0.5],
  );
  check("a mono clip is left as it is", [...monoFrom([Float32Array.from([1, -1])])], [1, -1]);
}

const blank = call("artifacts", {
  song_id: "untitled-song",
  template_id: song.template_id,
  bpm: 120,
  seed: 1,
  selections: {},
  lyrics: "",
  brief: "",
  artist_references: [],
});
check("a blank song still builds a prompt", typeof blank.prompt_sha256, "string");
check("a blank song names itself in the graph",
  JSON.parse(blank.workflow_text)["10"]["inputs"]["filename_prefix"], "audio/untitled-song");

// The v2 API accepts the API-format graph verbatim and rejects the UI export (`nodes`/`links`) with
// `workflow_format_ui`. One graph serves both protocols, so it has to be the API format.
const graph = JSON.parse(artifact.workflow_text);
check(
  "the graph is API format, which v2 requires",
  !("nodes" in graph) &&
    Object.values(graph).every(
      (node) => node && typeof node === "object" && "class_type" in node && "inputs" in node,
    ),
  true,
);
check(
  "Comfy Cloud is a v2 surface and needs a key",
  (() => {
    const cloud = presetFor("https://cloud.comfy.org");
    return cloud ? [cloud.protocol, cloud.needsKey] : null;
  })(),
  ["v2", true],
);
check(
  "the local presets are the native protocol",
  ["http://127.0.0.1:8188", "http://127.0.0.1:8288"].map(
    (base) => presetFor(base)?.protocol ?? null,
  ),
  ["native", "native"],
);

// --- The radio: the browser's station plan must be the CLI's ----------------------------------
//
// The page plays what the station document says, so the two must not be able to disagree about a
// station any more than about a caption. The same station, position and seed are planned in both
// and compared whole, selections included; then the graph is built for that plan and checked to
// land under the station rather than in a song directory.

const tagBudget = JSON.parse(
  fs.readFileSync(path.join(DIST, "repo", "vocabulary", "tag-bins.json"), "utf8"),
).tag_budget;
const radioPlan = call("radio_plan", { station_id: "neon-drive", index: 3, seed: 12345 });
const radioCaption = call("render_selections", radioPlan.selections);
const nextPlan = call("radio_plan", { station_id: "neon-drive", index: 4, seed: 12346 });
const instrumentalPlan = call("radio_plan", {
  station_id: "neon-drive",
  index: 3,
  seed: 12345,
  instrumental: true,
});

console.log("\nradio:\n");
check("the browser plans the station the CLI plans", radioPlan, native.radio.plan);
check("the browser renders the station's caption", radioCaption.string, native.radio.caption);
check("a radio caption is inside the tag budget", radioCaption.tags.length <= tagBudget, true);
check(
  "the next song of the station is a different song",
  call("render_selections", nextPlan.selections).string !== radioCaption.string,
  true,
);
check(
  "an instrumental take is marked in its file name",
  instrumentalPlan.filename_prefix,
  "radio/neon-drive/neon-drive-instrumental",
);
check(
  "the take kind does not move the record's directory",
  instrumentalPlan.artifacts_dir,
  radioPlan.artifacts_dir,
);

// A subject drawn at random repeats within any six songs by pigeonhole, which is what made
// consecutive radio songs read as the same song. The position rotates it, and the way it is told
// rotates on a slower cycle, so a subject that comes back comes back differently. Both are read
// from the document rather than assumed here.
const stationDoc = JSON.parse(
  fs.readFileSync(path.join(DIST, "repo", "vocabulary", "radio-stations.json"), "utf8"),
);
const neon = stationDoc.stations.find((entry) => entry.id === "neon-drive");
const cycles = [3, 4, 3 + neon.themes.length].map((index) =>
  call("radio_plan", { station_id: "neon-drive", index, seed: 12345 }),
);
check("the subject rotates by position",
  cycles.map((plan) => plan.theme), [neon.themes[3], neon.themes[4], neon.themes[3]]);
check("the telling rotates on its own cycle",
  cycles.map((plan) => plan.angle),
  [stationDoc.angles[0], stationDoc.angles[0], stationDoc.angles[1]]);

const radioArtifact = call("artifacts", {
  song_id: radioPlan.song_id,
  template_id: radioPlan.template_id,
  bpm: radioPlan.bpm,
  seed: 12345,
  selections: radioPlan.selections,
  lyrics: "",
  brief: "",
  artist_references: [],
  artifacts_dir: radioPlan.artifacts_dir,
  filename_prefix: radioPlan.filename_prefix,
});
const radioGraph = JSON.parse(radioArtifact.workflow_text);
check(
  "a radio take lands in its station's directory",
  radioGraph["10"].inputs.filename_prefix,
  "radio/neon-drive/neon-drive",
);
check(
  "a radio take names its own artifacts directory",
  radioArtifact.prompt.lyrics.ref,
  `radio/neon-drive/${radioPlan.song_id}/lyrics.md`,
);
check("a radio take still pins a composition", typeof radioArtifact.prompt.form.composition_sha256, "string");

// --- The generator: the brief must be the core's own, and the scaffold must be valid on arrival ---

const templatesFile = JSON.parse(
  fs.readFileSync(path.join(DIST, "repo", "vocabulary", "structure-templates.json"), "utf8"),
);
const template = templatesFile.templates.find((t) => t.id === song.template_id);
const brief = call("brief", { template_id: song.template_id, bpm: song.bpm, selections });

// How a song is told reaches the model only through the prompt, so the prompt has to carry it, and a
// hand-built song — which has no angle — has to read exactly as it did before.
const toldPrompt = buildPrompt({
  brief: brief.brief,
  caption: rendered.string,
  theme: "a subject",
  angle: stationDoc.angles[0],
});
check(
  "the prompt says how the song is told",
  toldPrompt.includes("HOW IT IS TOLD") && toldPrompt.includes(stationDoc.angles[0]),
  true,
);
check(
  "a hand-built song has no telling section",
  buildPrompt({ brief: brief.brief, caption: rendered.string, theme: "a subject" }).includes(
    "HOW IT IS TOLD",
  ),
  false,
);

const scaffold = call("scaffold", { template_id: song.template_id });
const checked = call("check_lyric", {
  text: scaffold.text,
  template_id: song.template_id,
  bpm: song.bpm,
  selections,
});

// A scaffold that needs fixing before it can be written into is not a useful starting point.
const prose = scaffold.text
  .split("\n")
  .filter((line) => line.trim() !== "" && !/^\[[^\]]+\]$/.test(line.trim()));

console.log("\ngenerator:\n");
check("the brief is produced", brief.brief.length > 500, true);
check("the brief names the template", brief.brief.includes(template.name), true);
check("the brief states each section's line budget", brief.brief.includes("budget"), true);
check("the scaffold is only tags and blank lines", prose, []);
check("the scaffold names every section", checked.outline.length, template.sections.length);
check("the scaffold passes the checker", checked.errors, []);

if (process.argv.includes("--show")) {
  console.log("\n--- scaffold ---\n" + scaffold.text.replace(/^/gm, "  "));
  console.log("--- brief ---\n" + brief.brief.replace(/^/gm, "  "));
}

// --- The lens: the rules the editor enforces, which a build cannot check ---------------------

const LABELS = new Set(["Intro", "Verse 1", "Chorus", "Solo"]);
const slot = (lines, line, content = "") =>
  slotFor({ lines, line, content, sectionLabels: LABELS });

console.log("\nlens:\n");
check(
  "a positional finding keeps its line",
  parseFindings({ errors: ["line 3: unknown tag '[X]'"], warnings: [] }),
  [{ line: 3, severity: "error", message: "unknown tag '[X]'" }],
);
check(
  "a finding about the whole song gets no line",
  parseFindings({ errors: [], warnings: ["[Verse 1]: rhyme scheme AAAA vs template (approximate)"] }),
  [],
);
check("an empty section is a header slot", slot(["[Verse 1]"], 1), "header");
check("a tag under a header is a performance slot", slot(["[Verse 1]", "[rap]"], 2), "within");
check(
  "a tag after the words is a leaving slot",
  slot(["[Verse 1]", "[rap]", "a line of words", "[build-up]"], 4),
  "leaving",
);
check(
  "a tag after a blank line is a leaving slot",
  slot(["[Verse 1]", "[rap]", "[spoken word]", "", "[build-up]"], 5),
  "leaving",
);
check("a new section after a blank is still a leaving slot", slot(["[Verse 1]", "[rap]", "words", "", "[Chorus]"], 5), "leaving");
check("a hyphen opens the modifier slot", slot(["[Verse 1]"], 1, "Verse 1 - "), "modifier");

// --- Draft state: the comparison the "local draft" badge rests on ------------------------------

console.log("\ndraft state:\n");
check(
  "key order does not make two equal selections differ",
  stable({ genre: { options: ["rap_metal"] }, tempo: { value: 92 } }),
  stable({ tempo: { value: 92 }, genre: { options: ["rap_metal"] } }),
);
check(
  "a changed selection is detected",
  stable({ genre: { options: ["rap_metal"] } }) === stable({ genre: { options: ["pop"] } }),
  false,
);
check("arrays keep their order", stable({ a: [1, 2, 3] }), '{"a":[1,2,3]}');
check("values survive the round trip", JSON.parse(stable({ a: { b: [1, "x", null] } })), {
  a: { b: [1, "x", null] },
});

// --- The editor's theme, and draft names ------------------------------------------------------
//
// The caret was invisible because CodeMirror believed the theme was light: its base theme sets
// `caret-color: black` for `&light` and white for `&dark`, so a dark editor it thinks is light gets
// a black caret. Asserting the facet is asserting the fix.

console.log("\neditor and drafts:\n");
check(
  "CodeMirror is told the theme is dark",
  EditorState.create({ extensions: [editorTheme()] }).facet(EditorView.darkTheme),
  true,
);
check("an unused draft name is left alone", freeName("chorus idea", []), "chorus idea");
check("a taken name gets a suffix", freeName("chorus idea", ["chorus idea"]), "chorus idea 2");
check(
  "a name taken twice keeps counting",
  freeName("chorus idea", ["chorus idea", "chorus idea 2"]),
  "chorus idea 3",
);
check("an empty name still gets one", freeName("   ", []), "draft");

// --- What a render reports back ------------------------------------------------------------------
//
// ComfyUI answers with [event, payload] pairs. Stringifying one keeps the event name and destroys the
// payload, which is exactly backwards — hence execution_start,[object Object] in the panel.

console.log("\nrender status messages:\n");
check(
  "routine events are dropped, not stringified",
  describeMessages([
    ["execution_start", { prompt_id: "x", timestamp: 1 }],
    ["execution_success", { prompt_id: "x", timestamp: 2 }],
  ]),
  [],
);
check(
  "a partly cached run says how much was reused",
  describeMessages([["execution_cached", { nodes: ["1", "2", "3"], prompt_id: "x" }]]),
  [{ kind: "note", text: "3 node(s) came from ComfyUI's cache" }],
);
check(
  "a cache hit is information, not a failure",
  describeMessages([["execution_cached", { nodes: [1] }]]).every((m) => m.kind !== "error"),
  true,
);
check(
  "an execution error is described rather than dumped",
  describeMessages([
    [
      "execution_error",
      {
        node_type: "KSampler",
        exception_type: "RuntimeError",
        exception_message: "allocation on device 0 failed",
        traceback: ["Traceback (most recent call last):", 'RuntimeError: allocation failed'],
      },
    ],
  ]),
  [
    { kind: "error", text: "RuntimeError at KSampler: allocation on device 0 failed" },
    { kind: "error", text: "RuntimeError: allocation failed" },
  ],
);
check(
  "nothing anywhere says [object Object]",
  describeMessages([
    ["execution_start", {}],
    ["execution_cached", { nodes: [1] }],
    ["execution_error", {}],
    ["some_future_event", { a: 1 }],
  ]).some((message) => message.text.includes("[object")),
  false,
);

// --- Updates: the build id a deployed page watches for ------------------------------------------
//
// A static host cannot push a change into a running tab, so the page watches a published version
// file and stamps its repository fetches with the build it booted as. The stamp is what stops new
// code from running against the previous build's cached data.

console.log("\nupdates:\n");
check("a URL with no build id is left alone", stamp("repo/manifest.json", ""), "repo/manifest.json");
check(
  "a build id stamps a repository URL",
  stamp("repo/manifest.json", "abc123"),
  "repo/manifest.json?v=abc123",
);
check(
  "an existing query is extended, not replaced",
  stamp("repo/x.json?a=1", "abc123"),
  "repo/x.json?a=1&v=abc123",
);

check(
  "a reload goes to a different URL, so the cached document cannot be served",
  reloadUrl("https://host/music-master/", "abc123"),
  "https://host/music-master/?u=abc123",
);
check(
  "a reload replaces the previous one rather than stacking them",
  reloadUrl("https://host/music-master/?u=old", "abc123"),
  "https://host/music-master/?u=abc123",
);

const versionPath = path.join(DIST, "version.json");
const version = fs.existsSync(versionPath)
  ? JSON.parse(fs.readFileSync(versionPath, "utf8"))
  : null;
check("the build publishes a version file", typeof version?.build, "string");
check("the version file names a non-empty build", (version?.build ?? "").length > 0, true);

// --- Recovering a station's existing takes ------------------------------------------------------
//
// The file name is what places a take without its plan, so a station can play what it has already
// rendered instead of rendering a replacement. The station id is anchored, because one id can be a
// prefix of another and a loose match would file one station's songs under the other.

console.log("\ntake names:\n");
check("a take carries the renderer's number", parseTakeName("neon-drive", "neon-drive_00003.mp3"), {
  order: 3,
  instrumental: false,
});
check(
  "an instrumental take says so",
  parseTakeName("neon-drive", "neon-drive-instrumental_00002.mp3"),
  { order: 2, instrumental: true },
);
check(
  "a hyphenated station id parses",
  parseTakeName("reggaeton-block-party", "reggaeton-block-party_00011.mp3"),
  { order: 11, instrumental: false },
);
check(
  "another station's take is not this station's",
  parseTakeName("neon-drive", "trap-after-dark_00001.mp3"),
  null,
);
check(
  "a station id that is a prefix does not match",
  parseTakeName("neon-drive", "neon-drive-b-sides_00001.mp3"),
  null,
);
check("a file that is not a take is refused", parseTakeName("neon-drive", "prompt.json"), null);
check(
  "a name that carried a number of ours is not a take",
  parseTakeName("neon-drive", "neon-drive-005-instrumental_00001.mp3"),
  null,
);

// The renderer's history is the other place a station's takes can be found, and its shape has
// changed between versions. Both shapes are pinned here, along with the rules that keep a temp file
// and another station's folder out of the result.
const historyFixture = {
  tuple: {
    prompt: [
      1,
      "id",
      { 4: { inputs: { tags: "Trap, Dark, Late Night" } }, 8: { inputs: { seed: 42 } } },
      {},
      [],
    ],
    outputs: {
      10: {
        audio: [
          { filename: "neon-drive-000_00001.mp3", subfolder: "radio/neon-drive", type: "output" },
        ],
      },
    },
  },
  bare: {
    prompt: { 4: { inputs: { tags: "Shoegaze, Dreamy" } }, 8: { inputs: { seed: 7 } } },
    outputs: {
      10: {
        audio: [
          {
            filename: "neon-drive-001-instrumental_00001.mp3",
            subfolder: "radio/neon-drive",
            type: "output",
          },
        ],
      },
    },
  },
  elsewhere: {
    prompt: [],
    outputs: {
      10: { audio: [{ filename: "other-000_00001.mp3", subfolder: "radio/other", type: "output" }] },
    },
  },
  preview: {
    prompt: [],
    outputs: {
      9: { audio: [{ filename: "temp_00001.mp3", subfolder: "radio/neon-drive", type: "temp" }] },
    },
  },
  prefix: {
    prompt: [],
    outputs: {
      10: {
        audio: [
          {
            filename: "neon-drive-b-sides-001_00001.mp3",
            subfolder: "radio/neon-drive-b-sides",
            type: "output",
          },
        ],
      },
    },
  },
};
const recovered = takesFromHistory(historyFixture, "radio/neon-drive");
check("a take is recovered from the queue-tuple history", recovered[0], {
  filename: "neon-drive-000_00001.mp3",
  subfolder: "radio/neon-drive",
  type: "output",
  caption: "Trap, Dark, Late Night",
  seed: 42,
});
check("a take is recovered from the bare-graph history", recovered[1], {
  filename: "neon-drive-001-instrumental_00001.mp3",
  subfolder: "radio/neon-drive",
  type: "output",
  caption: "Shoegaze, Dreamy",
  seed: 7,
});
check("only this station's takes are recovered", recovered.length, 2);
check(
  "a preview is not a take",
  recovered.some((take) => take.filename === "temp_00001.mp3"),
  false,
);
check("an empty history is not an error", takesFromHistory(null, "radio/neon-drive"), []);

// --- Reactive state: a write must go through the proxy ------------------------------------------
//
// Svelte's `$state` caches a signal per property and returns the signal's value, so writing to a raw
// reference updates the object and not the signal: the panel keeps showing whatever it first read,
// while anything reading real state — an elapsed timer — keeps ticking. A list of records that are
// mutated as they progress therefore has to be mutated through the value the list holds.

console.log("\nreactive state:\n");
{
  const state = proxy({ queue: [] });
  const pushed = { status: "writing" };
  state.queue.push(pushed);
  const queued = state.queue[0];
  const first = queued.status;
  pushed.status = "done";
  check("the queue holds a proxy, not the object pushed into it", queued === pushed, false);
  check("a write to the pushed object leaves the queued value where it was", queued.status, first);
  queued.status = "done";
  check("a write to the queued value is what a reader sees", queued.status, "done");
}

// --- Reading a model stream ---------------------------------------------------------------------
//
// ollama streams NDJSON and says when it is finished. The read must end on that marker rather than on
// the socket closing: a proxy that holds the connection open otherwise leaves the caller waiting for
// text that already arrived, which is how a radio song sits at "writing lyrics" forever with nothing
// behind it ever playing.

console.log("\nmodel stream:\n");
const realFetch = globalThis.fetch;
const encoder = new TextEncoder();
const chunksOf = (chunks, close) =>
  new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        if (close) controller.close();
        // Otherwise deliberately left open: the model said it was done.
      },
    }),
  );

globalThis.fetch = async () =>
  chunksOf(['{"response":"[Verse 1]\\n","done":false}\n', '{"response":"a line","done":true}\n'], false);
const raced = await Promise.race([
  generate({ model: "m", base: "http://example.invalid", prompt: "p" }),
  new Promise((resolve) => setTimeout(() => resolve("__timeout__"), 3000)),
]);
check("a stream that says done is not waited on to close", raced, "[Verse 1]\na line");

globalThis.fetch = async () => chunksOf(['{"response":"last","done":true}'], true);
check(
  "a final line without a newline is still read",
  await generate({ model: "m", base: "http://example.invalid", prompt: "p" }),
  "last",
);

globalThis.fetch = async () =>
  chunksOf(['{"response":"partial","done":false}\n', '{"response":" tail"'], true);
check(
  "a truncated final line is dropped rather than fatal",
  await generate({ model: "m", base: "http://example.invalid", prompt: "p" }),
  "partial",
);
globalThis.fetch = realFetch;

// --- End to end, on request: does the prompt actually produce a valid lyric? -------------------
//
// Opt-in because it costs a model call and, for a cloud model, sends the brief off this machine.

if (process.argv.includes("--generate")) {
  const flag = (name, fallback) => {
    const found = process.argv.find((argument) => argument.startsWith(`--${name}=`));
    return found ? found.slice(name.length + 3) : fallback;
  };
  const model = flag("model", "deepseek-v4.1-flash:cloud");
  const theme = flag("theme", "a night shift that never ends");

  const prompt = buildPrompt({ brief: brief.brief, caption: rendered.string, theme });
  console.log(`\ngenerating with ${model} …`);
  const started = Date.now();
  const draft = await generate({ model, base: "http://127.0.0.1:11434", prompt });
  const seconds = ((Date.now() - started) / 1000).toFixed(1);

  console.log(`\n--- draft (${seconds}s, ${draft.length} chars) ---\n${draft}`);
  const verdict = call("check_lyric", {
    text: draft,
    template_id: song.template_id,
    bpm: song.bpm,
    selections,
  });
  console.log(
    `\nchecker: ${verdict.errors.length} error(s), ${verdict.warnings.length} warning(s), ` +
      `${verdict.conformance ? verdict.conformance.matched.length : 0}/` +
      `${template.sections.length} sections matched, ${verdict.outline.length} sections found`,
  );
  for (const error of verdict.errors.slice(0, 6)) console.log(`  ERROR ${error}`);
  for (const warning of verdict.warnings.slice(0, 6)) console.log(`  warn  ${warning}`);
}

// The runtime the page loads must have been copied, or the browser boot fails and nothing else does.
const runtime = ["pyodide.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
for (const file of runtime) {
  const present = fs.existsSync(path.join(DIST, "pyodide", file));
  console.log(`  ${present ? "ok  " : "FAIL"}  dist/pyodide/${file} present`);
  if (!present) failures.push(file);
}

console.log(
  failures.length === 0
    ? `\nglue matches the CLI on every compared value (${rendered.tags.length} tags, ${plan.rows.length} sections)`
    : `\n${failures.length} mismatch(es): ${failures.join(", ")}`,
);
process.exit(failures.length === 0 ? 0 : 1);
