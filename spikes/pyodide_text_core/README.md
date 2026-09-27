# Pyodide text-core spike

Tests the claim a static, server-less SPA rests on: that the checks the UI must run **live** are
pure enough to run unchanged in a WebAssembly CPython, so the browser can be a *second adapter* of
the one implementation rather than a TypeScript rewrite that drifts from the CLI.

The layer under test is the five text modules in `vocabulary/` — `check_lyrics.py`,
`timeline.py`, `render_tags.py`, `structure_templates.py` and `validate_vocabulary.py`. Their only
imports are `json`, `re`, `difflib`, `textwrap`, `pathlib`, `sys` and an optional `jsonschema`, so
the question is not whether they are *portable* but whether "portable" survives contact with a
real WASM runtime and is still fast enough to sit under a text editor.

Everything that needs `numpy`, `librosa`, `scipy` or the network — `analyse_*.py`,
`verify_render.py`, `build_and_submit.py` — is out of scope here and always will be: it cannot run
in the browser at all, which is why it belongs behind the optional local backend.

## Running it

```bash
cd spikes/pyodide_text_core
npm install
node parity.mjs     # correctness: native CPython vs Pyodide, byte-for-byte
node latency.mjs    # speed: is the per-caret check inside a frame budget?
```

Node 24 and `pyodide` are the only requirements. `npm install` writes to `node_modules/` and
`.npm-cache/`, both ignored.

## Result 1 — parity

**7 of 7 CLI invocations byte-identical**, comparing stdout, stderr and exit status, and across a
Python version gap (native CPython **3.12.3**, Pyodide **3.14.2**, 22 files mounted):

| invocation | result |
| --- | --- |
| `render_tags.py` on the fixture | identical |
| `check_lyrics.py` on the fixture, with selections | identical |
| `check_lyrics.py --self-test` | identical |
| `check_lyrics.py songs/rap-metal-groove/lyrics.md` | identical |
| `structure_templates.py --list` | identical |
| `structure_templates.py --brief` | identical |
| `structure_templates.py --timeline` | identical |

The scripts are run through `runpy` on their real `__main__` entry point, so this exercises the
actual code path a user hits, not a re-implementation of it.

One informational difference, characterised rather than waved away: `validate_vocabulary.py` differs,
and the first divergence is line 1 —

```
native: warn: bin 'drums': exclusion no_drums -> 808_kicks is declared one way only ...
wasm:   warn: jsonschema is not installed; skipped schema conformance check
```

That is the missing optional dependency, not a behavioural difference: the coherence warnings are
identical and only the JSON-Schema conformance section is skipped. It is also an admin/CI tool
rather than a live UI surface, because the vocabulary editor is not in v1.

## Result 2 — latency

The plan requires the lyric inspector to update **on the caret, not on save**, so the check
pipeline's per-invocation cost is a UX budget. `latency_probe.py` times the three operations a live
UI repeats, with the vocabulary loaded once as the SPA would:

| operation | native median | Pyodide median | slowdown | Pyodide p95 |
| --- | --- | --- | --- | --- |
| render (caption, per keystroke) | 0.02 ms | 0.04 ms | 2.0x | 0.05 ms |
| timeline (per tempo/template change) | 0.04 ms | 0.09 ms | 2.3x | 0.11 ms |
| lyrics (full check, per caret move) | 6.19 ms | 11.83 ms | 1.9x | 16.97 ms |

The conclusion is that WASM costs a consistent factor of about two, and the most expensive live
operation is still ~12 ms median and ~17 ms p95. A caret-driven inspector has roughly a frame's
budget to play with, so this is comfortably real-time — and the two keystroke-path operations are
effectively free.

## What this does not prove

- **It is Node, not a browser.** Same WASM CPython and same stdlib, but the browser adds the
  first-load cost of the runtime (single-digit MB, cacheable), worker and memory constraints, and
  module-resolution differences. Those are integration risks for the SPA, not risks to the claim
  that the logic is portable.
- **It does not test the extracted package.** It runs the current scripts as they are, including the
  `sys.path.insert(...)` + `import timeline as T` arrangement that will not travel to a browser
  cleanly. Moving to `musicmaster/` with real imports is what removes that, which is why M0 comes
  first.
- **It says nothing about the audio layer.** Measurement, rendering and the oracle stay on a host.
