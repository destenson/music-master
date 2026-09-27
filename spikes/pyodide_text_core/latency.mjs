// Run latency_probe.py natively and under Pyodide, and report the slowdown factor.
//
//   cd spikes/pyodide_text_core && node latency.mjs

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { loadPyodide } from "pyodide";

const REPO = path.resolve(import.meta.dirname, "..", "..");
const PROBE = "spikes/pyodide_text_core/latency_probe.py";
const MOUNTED_DIRS = ["musicmaster", "vocabulary", "schemas"];

function mountDir(py, relDir) {
  const abs = path.join(REPO, relDir);
  for (const rel of fs.readdirSync(abs, { recursive: true })) {
    if (rel.split(path.sep).includes("__pycache__")) continue;
    const src = path.join(abs, rel);
    if (!fs.statSync(src).isFile()) continue;
    const dest = "/repo/" + path.posix.join(relDir, rel.split(path.sep).join("/"));
    py.FS.mkdirTree(path.posix.dirname(dest));
    py.FS.writeFile(dest, fs.readFileSync(src));
  }
}

const py = await loadPyodide();
for (const dir of MOUNTED_DIRS) mountDir(py, dir);
for (const rel of [
  PROBE,
  "songs/rap-metal-groove/lyrics.md",
  "vocabulary/examples/late-night-trap.json",
]) {
  const dest = "/repo/" + rel;
  py.FS.mkdirTree(path.posix.dirname(dest));
  py.FS.writeFile(dest, fs.readFileSync(path.join(REPO, rel)));
}

const native = JSON.parse(
  execFileSync("python3", [PROBE], { cwd: REPO, encoding: "utf8" }),
);

const wasmOut = await py.runPythonAsync(`
import contextlib, io, os, runpy, sys
os.chdir("/repo")
buffer = io.StringIO()
code = 0
with contextlib.redirect_stdout(buffer):
    try:
        runpy.run_path(${JSON.stringify(PROBE)}, run_name="__main__")
    except SystemExit as exc:
        value = exc.code
        code = 0 if value is None else (value if isinstance(value, int) else 1)
if code != 0:
    raise RuntimeError("latency_probe.py exited " + str(code))
buffer.getvalue()
`);
const wasm = JSON.parse(wasmOut);

console.log(
  `${"operation".padEnd(38)}${"native".padStart(10)}${"pyodide".padStart(10)}${"slowdown".padStart(10)}`,
);
for (const key of Object.keys(native)) {
  const n = native[key].median_ms;
  const w = wasm[key].median_ms;
  console.log(
    `${key.padEnd(38)}${(n + " ms").padStart(10)}${(w + " ms").padStart(10)}` +
      `${(w / n).toFixed(1).padStart(9)}x`,
  );
}
console.log("\np95:");
for (const key of Object.keys(native)) {
  console.log(
    `  ${key.padEnd(38)}${(native[key].p95_ms + " ms").padStart(10)}` +
      `${(wasm[key].p95_ms + " ms").padStart(10)}`,
  );
}
