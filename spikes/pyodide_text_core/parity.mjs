// Prove that the text core runs unchanged under Pyodide, byte-identically to native CPython.
//
// This is the load-bearing claim behind a static (server-less) SPA: the checks the UI must run
// live -- tag rendering, the syllable/time budget, lyric findings -- are pure stdlib Python, so a
// WASM CPython can be the *same* implementation the CLI uses rather than a TypeScript rewrite that
// would drift. This harness runs each script's real entry point (`__main__`) both ways and diffs
// stdout, stderr and exit status.
//
//   cd spikes/pyodide_text_core && npm install && node parity.mjs
//
// The heavy audio layer (librosa, numpy, scipy) is deliberately out of scope: it cannot run in the
// browser at all, which is why it lives behind the optional local backend instead.

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { loadPyodide } from "pyodide";

const REPO = path.resolve(import.meta.dirname, "..", "..");
const MOUNTED_DIRS = ["vocabulary", "schemas"];

// Each entry is one real CLI invocation, run from the repository root both ways.
const COMMANDS = [
  ["render_tags / fixture", ["vocabulary/render_tags.py", "vocabulary/examples/late-night-trap.json"]],
  [
    "check_lyrics / fixture",
    [
      "vocabulary/check_lyrics.py",
      "vocabulary/examples/lyrics-late-night-trap.md",
      "--selections=vocabulary/examples/late-night-trap.json",
    ],
  ],
  ["check_lyrics / self-test", ["vocabulary/check_lyrics.py", "--self-test"]],
  ["check_lyrics / song", ["vocabulary/check_lyrics.py", "songs/rap-metal-groove/lyrics.md"]],
  ["structure_templates / list", ["vocabulary/structure_templates.py", "--list"]],
  [
    "structure_templates / brief",
    [
      "vocabulary/structure_templates.py",
      "--template=pop_standard",
      "--brief",
      "--bpm=95",
      "--duration=180",
    ],
  ],
  [
    "structure_templates / timeline",
    [
      "vocabulary/structure_templates.py",
      "--template=pop_standard",
      "--timeline",
      "--bpm=95",
      "--duration=180",
    ],
  ],
];

function mountDir(py, relDir) {
  const abs = path.join(REPO, relDir);
  if (!fs.existsSync(abs)) return 0;
  let count = 0;
  for (const rel of fs.readdirSync(abs, { recursive: true })) {
    if (rel.split(path.sep).includes("__pycache__")) continue;
    const src = path.join(abs, rel);
    if (!fs.statSync(src).isFile()) continue;
    const dest = "/repo/" + path.posix.join(relDir, rel.split(path.sep).join("/"));
    py.FS.mkdirTree(path.posix.dirname(dest));
    py.FS.writeFile(dest, fs.readFileSync(src));
    count += 1;
  }
  return count;
}

function runNative(argv) {
  const r = spawnSync("python3", argv, { cwd: REPO, encoding: "utf8" });
  return { out: r.stdout ?? "", err: r.stderr ?? "", code: r.status ?? -1 };
}

const RUNNER = `
import contextlib, io, os, runpy, sys

def run_script(argv):
    os.chdir("/repo")
    sys.argv = list(argv)
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            runpy.run_path(argv[0], run_name="__main__")
        except SystemExit as exc:
            value = exc.code
            code = 0 if value is None else (value if isinstance(value, int) else 1)
    return [out.getvalue(), err.getvalue(), code]
`;

function report(name, native, wasm) {
  const checks = [
    ["stdout", native.out === wasm.out],
    ["stderr", native.err === wasm.err],
    ["exit", native.code === wasm.code],
  ];
  const ok = checks.every(([, same]) => same);
  const detail = checks
    .filter(([, same]) => !same)
    .map(([field]) => `${field} (native=${native[field]?.length ?? native[field]} wasm=${wasm[field]?.length ?? wasm[field]})`)
    .join(", ");
  return { name, ok, detail, native, wasm };
}

const py = await loadPyodide();

let mounted = 0;
for (const dir of MOUNTED_DIRS) mounted += mountDir(py, dir);
py.FS.mkdirTree("/repo/songs/rap-metal-groove");
py.FS.writeFile(
  "/repo/songs/rap-metal-groove/lyrics.md",
  fs.readFileSync(path.join(REPO, "songs/rap-metal-groove/lyrics.md")),
);
py.runPython(RUNNER);

const wasmPython = py.globals.get("sys").version.split(" ")[0];
const results = [];

for (const [name, argv] of COMMANDS) {
  const native = runNative(argv);
  const [out, err, code] = py.globals.get("run_script")(py.toPy(argv)).toJs();
  const wasm = { out, err, code: Number(code) };
  const r = report(name, native, wasm);
  results.push(r);
  const mark = r.ok ? "IDENTICAL" : "DIFFERS";
  console.log(`[${mark.padEnd(9)}] ${name}${r.detail ? "  --  " + r.detail : ""}`);
  if (!r.ok) {
    const firstDiff = (a, b) => {
      const n = Math.min(a.length, b.length);
      for (let i = 0; i < n; i += 1) if (a[i] !== b[i]) return i;
      return n;
    };
    for (const field of ["out", "err"]) {
      if (native[field] !== wasm[field]) {
        const i = firstDiff(native[field], wasm[field]);
        console.log(`    native ${field} @${i}: ${JSON.stringify(native[field].slice(i, i + 160))}`);
        console.log(`    wasm   ${field} @${i}: ${JSON.stringify(wasm[field].slice(i, i + 160))}`);
      }
    }
  }
}

const passed = results.filter((r) => r.ok).length;
console.log(
  `\n${passed}/${results.length} invocations byte-identical ` +
    `(native CPython ${process.env.PYTHON_VERSION ?? "python3"} vs Pyodide ${wasmPython}, ${mounted} files mounted)`,
);

// The vocabulary validator is an admin/CI tool, not a live UI surface, and depends on jsonschema.
// It is reported for information rather than as a parity gate.
const nativeValidate = runNative(["vocabulary/validate_vocabulary.py"]);
const [vout, verr, vcode] = py.globals
  .get("run_script")(py.toPy(["vocabulary/validate_vocabulary.py"]))
  .toJs();
const validatorMatches =
  nativeValidate.out === vout && nativeValidate.err === verr && nativeValidate.code === Number(vcode);
console.log(
  `\ninfo: validate_vocabulary.py ${validatorMatches ? "matches" : "differs"} ` +
    `(jsonschema is a native dependency; the core does not need it)`,
);
if (!validatorMatches) {
  const nativeLines = (nativeValidate.out + nativeValidate.err).split("\n");
  const wasmLines = (vout + verr).split("\n");
  for (let i = 0; i < Math.max(nativeLines.length, wasmLines.length); i += 1) {
    if (nativeLines[i] !== wasmLines[i]) {
      console.log(`  first divergence at line ${i + 1}:`);
      console.log(`    native: ${JSON.stringify(nativeLines[i] ?? "<missing>")}`);
      console.log(`    wasm:   ${JSON.stringify(wasmLines[i] ?? "<missing>")}`);
      break;
    }
  }
}

process.exit(passed === results.length ? 0 : 1);
