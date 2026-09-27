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
import { loadPyodide } from "pyodide";

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
from musicmaster import render, timeline
vocab = render.load_vocabulary()
selections = json.load(open(${JSON.stringify(path.join(REPO, "songs", SONG, "selections.json"))}))["selections"]
song = json.load(open(${JSON.stringify(path.join(REPO, "songs", SONG, "song.json"))}))
st = timeline.load(timeline.SECTION_TAGS_PATH)
doc = timeline.load(timeline.TEMPLATES_PATH)
rates = timeline.load_delivery_rates()
profile = timeline.profile_for_vocals(selections, rates)
template = {t["id"]: t for t in doc["templates"]}[song["template_id"]]
plan = timeline.build_timeline(template, song["bpm"], st, profile, doc)
print(json.dumps({
    "render": {**render.render(vocab, selections),
               "problems": sorted(render.coherence_check(vocab, selections))},
    "profile": profile["label"],
    "plan": {"totals": plan["totals"], "rows": len(plan["rows"]),
             "profile_label": plan["profile_label"]},
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
