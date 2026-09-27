# Pyodide text-core spike

Tests the claim a static, server-less SPA rests on: that the checks the UI must run **live** are
pure enough to run unchanged in a WebAssembly CPython, so the browser can be a *second adapter* of
the one implementation rather than a TypeScript rewrite that drifts from the CLI.

The layer under test is the text tier of the `musicmaster` package — `lyrics.py`, `render.py`,
`timeline.py`, `templates.py` and `vocabulary.py`, extracted from the original scripts. Their only
imports are `json`, `re`, `difflib`, `textwrap`, `pathlib`, `sys` and an optional `jsonschema`, so
the question is not whether they are *portable* but whether "portable" survives contact with a real
WASM runtime and is still fast enough to sit under a text editor. `tests/test_text_tier.py` guards
that import rule.

Everything that needs `numpy`, `librosa`, `scipy` or the network — `analyse_*.py`, `verify_render.py`,
`build_and_submit.py` and the execute tier they will become — is out of scope here and always will
be: it cannot run in the browser at all, which is why it belongs behind the optional local backend.

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
Python version gap (native CPython **3.12.3**, Pyodide **3.14.2**, 30 files mounted):

| invocation | result |
| --- | --- |
| `musicmaster.render` on the fixture | identical |
| `musicmaster.lyrics` on the fixture, with selections | identical |
| `musicmaster.lyrics --self-test` | identical |
| `musicmaster.lyrics` on a song lyric | identical |
| `musicmaster.templates --list` | identical |
| `musicmaster.templates --brief` | identical |
| `musicmaster.templates --timeline` | identical |

Both sides drive the real entry point — `python3 -m <module>` natively, and `runpy.run_module(...)`
with `run_name="__main__"` under Pyodide — so this is the code path a user hits rather than a
re-implementation of it. The unit tests in `tests/` cover *what* the tier computes; this harness
covers *where* it runs, so a green run here means the runtime is not the variable.

One informational difference, characterised rather than waved away: `musicmaster.vocabulary` differs,
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
| timeline (per tempo/template change) | 0.04 ms | 0.10 ms | 2.5x | 0.12 ms |
| lyrics (full check, per caret move) | 6.21 ms | 12.13 ms | 2.0x | 13.68 ms |

Medians move by a few tenths of a millisecond between runs; the shape does not. WASM costs a
consistent factor of about two, and the most expensive live operation sits near ~12 ms median and
~14–17 ms p95. A caret-driven inspector has roughly a frame's budget to play with, so this is
comfortably real-time — and the two keystroke-path operations are effectively free.

## What this does not prove

- **It is Node, not a browser.** Same WASM CPython and same stdlib, but the browser adds the
  first-load cost of the runtime (single-digit MB, cacheable), worker and memory constraints, and
  module-resolution differences. Those are integration risks for the SPA, not risks to the claim
  that the logic is portable.
- **Latency is one machine's.** The numbers are this host, so a slower device scales them. What
  transfers is the ratio and the shape: about 2x, the two keystroke paths free, the caret check in
  the low tens of milliseconds.
- **It says nothing about the audio layer.** Measurement, rendering and the oracle stay on a host.
