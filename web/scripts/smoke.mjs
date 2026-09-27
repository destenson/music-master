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
import { presetFor, freshSeed } from "../src/lib/comfy.ts";
import { freeName, stable } from "../src/lib/draft.ts";
import { editorTheme } from "../src/lib/lens.ts";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { generate } from "../src/lib/ollama.ts";
import { buildPrompt } from "../src/lib/prompt.ts";

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

const NATIVE = `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from musicmaster import prompt, render, timeline
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
print(json.dumps({
    "render": {**render.render(vocab, selections),
               "problems": sorted(render.coherence_check(vocab, selections))},
    "profile": profile["label"],
    "plan": {"totals": plan["totals"], "rows": len(plan["rows"]),
             "profile_label": plan["profile_label"]},
    "artifacts": {"prompt_sha256": built["prompt_sha256"],
                  "prompt_text": prompt.serialise(built["prompt"]),
                  "workflow_text": prompt.serialise(built["workflow"])},
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

// --- The render path: the browser's artifacts must be the ones the CLI writes -----------------

const lyricsText = fs.readFileSync(path.join(DIST, "repo", "songs", SONG, "lyrics.md"), "utf8");
const briefText = fs.readFileSync(path.join(DIST, "repo", "songs", SONG, "brief.md"), "utf8");
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

// --- The generator: the brief must be the core's own, and the scaffold must be valid on arrival ---

const templatesFile = JSON.parse(
  fs.readFileSync(path.join(DIST, "repo", "vocabulary", "structure-templates.json"), "utf8"),
);
const template = templatesFile.templates.find((t) => t.id === song.template_id);
const brief = call("brief", { template_id: song.template_id, bpm: song.bpm, selections });
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
