"""Time the three operations a live UI repeats, so "runs in the browser" can be checked against
"runs fast enough to sit under a text editor".

Correctness parity (`parity.mjs`) shows the text core produces identical output natively and under
Pyodide. This probe answers the other question the plan depends on: the lyric inspector updates on
the caret, not on save (ui-plan.md 6.2), so the check pipeline's per-invocation cost is a UX budget.

The probe is runtime-agnostic on purpose: `latency.mjs` runs this same file under Pyodide, and
running it directly under CPython gives the baseline to compare against.

    python3 spikes/pyodide_text_core/latency_probe.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from musicmaster import lyrics as CL  # noqa: E402
from musicmaster import render as RT  # noqa: E402
from musicmaster import timeline as T  # noqa: E402


def time_it(fn, reps: int) -> dict:
    samples = []
    for _ in range(reps):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    return {
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 2),
        "reps": reps,
    }


def main() -> int:
    st = CL.load(CL.SECTION_TAGS_PATH)
    vocab = CL.load(CL.VOCAB_PATH)
    templates_doc = CL.load(CL.TEMPLATES_PATH)
    rates = T.load_delivery_rates()
    selections = json.loads(
        (ROOT / "vocabulary/examples/late-night-trap.json").read_text()
    )["selections"]
    profile = T.profile_for_vocals(selections, rates)
    band = tuple(profile["band"])
    template = {t["id"]: t for t in templates_doc["templates"]}["pop_standard"]
    lines = (ROOT / "songs/rap-metal-groove/lyrics.md").read_text().splitlines()

    def render_caption() -> None:
        RT.render(vocab, selections)

    def build_plan() -> None:
        T.build_timeline(template, 92.0, st, profile, templates_doc)

    def check_lyric() -> None:
        # The full pipeline main() runs, minus the printing: this is what a caret move costs.
        report = CL.Report()
        found = CL.analyse(lines, st, report)
        CL.check_blank_lines(lines, st, report)
        CL.check_consistency(found, st, vocab, selections, report)
        CL.check_cliches(lines, report)
        meter = CL.check_meter_and_rhyme(lines, st, report, band=band)
        CL.check_template(
            meter, st, template, report, plan=T.build_timeline(template, 92.0, st, profile, templates_doc)
        )

    result = {
        "render (caption, per keystroke)": time_it(render_caption, 200),
        "timeline (per tempo/template change)": time_it(build_plan, 100),
        "lyrics (full check, per caret move)": time_it(check_lyric, 30),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
