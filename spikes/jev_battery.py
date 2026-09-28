"""Ask the real battery about a real song, and print every answer it gave.

The seam, the wire format and the question bank are all testable without a network -- that is what
the replay oracle and `--print-request` are for. What none of them can tell you is whether the
questions, asked of the live service about an actual song, produce answers a person would recognise
as being about that song. This spike exists for that one question.

It is read-only and opt-in. Nothing in the package imports it, it writes nothing but its own
artifacts, and it sends only the projected fact sheet the battery would send anyway: the caption,
the chords and the lyrics the questions name.

    source ~/.bash_aliases        # TYPESAFE_API_KEY
    python3 spikes/jev_battery.py
    python3 spikes/jev_battery.py --song songs/rap-metal-groove --repeats 3
    python3 spikes/jev_battery.py --print-request
    python3 spikes/jev_battery.py --questions vocabulary/oracle-questions.json --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web" / "src" / "lib"))

from musicmaster import jev, oracle, precheck, spec  # noqa: E402

ARTIFACTS = ROOT / "spikes" / "jev_battery" / "artifacts"

DEFAULT_SONG = ROOT / "songs" / "nu-metal-rap-rock"


# --- reading a song directory -------------------------------------------------------------


def _bin_labels(vocab: dict, selections: dict, bin_id: str) -> str:
    """The labels a bin holds, the way the page reads them.

    The theme is the `lyric_theme` bin and nothing else. The page has no separate theme field, so a
    spike that scraped one out of the brief's prose would be asking about a theme the application
    never states -- and a question about a theme nobody set is a fixture bug, not a finding.
    """
    entry = (selections or {}).get(bin_id) or {}
    options = entry.get("options") if isinstance(entry, dict) else entry
    labels = {option["id"]: option["label"] for option in next((b for b in vocab["bins"] if b["id"] == bin_id), {}).get("options", [])}
    return ", ".join(labels.get(option, option) for option in (options or []))


def load_draft(song_dir: Path) -> dict:
    selections = json.loads((song_dir / "selections.json").read_text())
    prompt = json.loads((song_dir / "prompt.json").read_text())
    metadata = prompt.get("metadata") or {}
    bins = selections.get("selections") or {}
    vocab = spec.load_vocabulary()

    lyrics_path = song_dir / "lyrics.md"
    lyrics = lyrics_path.read_text() if lyrics_path.exists() else ""

    theme = _bin_labels(vocab, bins, "lyric_theme")

    template_id = None
    composition_path = song_dir / "composition.json"
    if composition_path.exists():
        template_id = json.loads(composition_path.read_text()).get("template_id")

    return {
        "selections": bins,
        "bpm": metadata.get("bpm"),
        "duration_s": metadata.get("duration_s"),
        "template_id": template_id,
        "lyrics": lyrics,
        "caption": (prompt.get("style") or {}).get("rendered_string") or "",
        "chords": "",
        "theme": theme,
        "artist_references": [],
    }


# --- the live transport -------------------------------------------------------------------


def post(payload: dict, key: str, endpoint: str, timeout: float = 90.0) -> tuple[dict | None, str | None, float]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, f"HTTP {exc.code}: {detail[:500]}", time.monotonic() - started
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}", time.monotonic() - started


# --- reporting ----------------------------------------------------------------------------


def describe_question(question: dict) -> str:
    instructions = question["instructions"]
    if isinstance(instructions, dict):
        return instructions.get("question", json.dumps(instructions))
    return instructions


def show_run(label: str, spec_: dict, state: dict, questions: dict, selections: dict, response: dict | None, error: str | None, seconds: float) -> dict:
    parsed = jev.parse_response(response or {}, questions) if response else {"answers": {}, "problems": [], "model": None, "usage": None}
    given = oracle.GivenOracle(
        parsed["answers"],
        kind="jev",
        model=parsed.get("model"),
        problems=parsed.get("problems") or (),
        error=error,
    )
    report = oracle.evaluate(
        spec_,
        state,
        given,
        bank=oracle.load_bank(),
        mechanical=precheck.caption_verdicts(spec_, state, spec.load_vocabulary(), selections),
        song_id=label,
    )

    print(f"\n=== {label}  ({seconds:.2f}s)  model={report['oracle'].get('model')} ===")
    if report["oracle"].get("degraded_reason"):
        print(f"  degraded: {report['oracle']['degraded_reason']}")

    width_id = max((len(v["requirement_id"]) for v in report["verdicts"]), default=12)
    print(f"  {'requirement':<{width_id}}  {'verdict':<10} {'sev':<7} {'prob':>6} {'margin':>7}  note")
    for verdict in report["verdicts"]:
        answer = parsed["answers"].get(verdict["requirement_id"]) or {}
        prob = verdict.get("probability")
        margin = verdict.get("top2_margin")
        print(
            f"  {verdict['requirement_id']:<{width_id}}  {verdict['verdict']:<10} "
            f"{verdict.get('severity', ''):<7} "
            f"{'-' if prob is None else f'{prob:.3f}':>6} "
            f"{'-' if margin is None else f'{margin:.3f}':>7}  {verdict.get('note', '')}"
        )
    counts = report["counts"]
    print(
        f"\n  overall: {report['overall']}   met {counts['met']}/{counts['total']}  "
        f"uncertain {counts['uncertain']}  unverified {counts['unverified']}"
    )
    if report.get("cross_check"):
        print(f"  cross-check: {report['cross_check']['note']}  (noul={report['cross_check']['noul']})")

    print("\n  raw answers by question:")
    for question_id, question in questions.items():
        answer = parsed["answers"].get(question_id)
        print(f"    {question_id}  [{question['type']}]")
        print(f"      q: {describe_question(question)}")
        if answer is None:
            print("      a: (no answer)")
        elif "distribution" in answer:
            levels = question.get("levels") or question.get("options") or []
            parts = [
                f"{levels[i] if i < len(levels) else i}={p:.2f}"
                for i, p in enumerate(answer["distribution"])
            ]
            top = max(range(len(answer["distribution"])), key=lambda i: answer["distribution"][i])
            print(f"      a: top={top + 1}  " + "  ".join(parts))
        else:
            print(f"      a: {json.dumps(answer)}")
    if parsed["problems"]:
        print("\n  problems:")
        for problem in parsed["problems"]:
            print(f"    {problem}")
    if parsed.get("usage"):
        print(f"\n  usage: {parsed['usage']}")

    return {
        "label": label,
        "seconds": seconds,
        "error": error,
        "answers": parsed["answers"],
        "problems": parsed["problems"],
        "report": report,
        "usage": parsed.get("usage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--song", default=str(DEFAULT_SONG), help="a song directory with selections.json")
    parser.add_argument("--model", default=jev.DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=jev.ENDPOINT)
    parser.add_argument("--questions", default=str(oracle.QUESTION_BANK_PATH), help="a question bank to use instead")
    parser.add_argument("--print-request", action="store_true", help="print the body and send nothing")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    bank = oracle.load_bank(args.questions)
    song_dir = Path(args.song)
    draft = load_draft(song_dir)
    built = spec.interpret(draft)
    questions = oracle.build_questions(built["spec"], bank)
    payload = jev.build_request(built["state"], questions, args.model)

    if args.print_request:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 2

    print(f"song {song_dir.name}: {len(built['spec']['requirements'])} requirements, {len(questions)} questions")
    print(f"state fields: {sorted(built['state'].keys())}")
    print(f"request bytes: {len(json.dumps(payload))}")

    runs = []
    for index in range(max(1, args.repeats)):
        response, error, seconds = post(payload, key, args.endpoint)
        runs.append(show_run(f"run {index + 1}", built["spec"], built["state"], questions, draft["selections"], response, error, seconds))

    if args.repeats > 1:
        print("\n=== stability across runs ===")
        for question_id, question in questions.items():
            values = []
            for run in runs:
                answer = run["answers"].get(question_id)
                if answer is None:
                    values.append(None)
                elif "distribution" in answer:
                    top = max(range(len(answer["distribution"])), key=lambda i: answer["distribution"][i]) + 1
                    values.append(top)
                else:
                    values.append(round(answer.get("noul", 0.0), 2))
            distinct = {v for v in values if v is not None}
            marker = "STABLE " if len(distinct) <= 1 else "VARIES "
            print(f"  {marker}{question_id}: {values}")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = ARTIFACTS / f"jev-battery-{song_dir.name}-{stamp}.json"
    out.write_text(json.dumps({"song": song_dir.name, "request": payload, "runs": runs}, indent=2, ensure_ascii=False, default=str))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
