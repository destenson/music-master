"""Does the battery's question separate a satisfied requirement from a violated one?

The seam's tests show that a probability is read and gated correctly. They cannot show whether the
question, asked of the live service, is *about the property it names*: a model that answers the same
thing for two opposite artifacts passes every structural test and measures nothing. This spike asks
one labelled pair per property -- an artifact that satisfies it and one that violates it -- and
reports whether each arm separates them, so a failure is attributed rather than asserted.

Four arms:

  * **score-question**      -- the comparative score question the pre-render check used to ask.
  * **score+target**        -- that same question, with the target placed at the path it names.
  * **property-noul**       -- a narrow noul: does `artifact` carry what `target` asks for?
  * **code**                -- deterministic containment, which is what the caption properties
                               are checked with now that the score question has been removed.

Read-only and opt-in. It sends only the hand-written fixtures below, never a user's song.

    source ~/.bash_aliases
    python3 spikes/jev_property_probe.py
    python3 spikes/jev_property_probe.py --json
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

from musicmaster import jev, oracle, spec  # noqa: E402

ARTIFACTS = ROOT / "spikes" / "jev_property_probe" / "artifacts"
SONG = ROOT / "songs" / "nu-metal-rap-rock"

CAPTION = (
    "Rap Rock, Nu Metal, Electronic, Driving, Syncopated, Live Drums, Drum Machine, Distorted Bass, "
    "Distorted Guitar, Power Chords, Palm-Muted Guitar, Guitar Riffs, Electric Piano, Detuned Synths, "
    "Male Rap Vocals, Male Tenor Vocals, Clean Vocals, Melodic Vocals, Soaring Vocals, Harsh Vocals, "
    "Gang Vocals, Layered Harmonies, Polished Production, Layered Production, Punchy, Bright, "
    "Aggressive, Defiant, Dynamic Energy, Vinyl Scratching, Nu-Metal Rap-Rock"
)

THEME_LYRIC = (
    "[Verse]\nSalt on the window, the last bus is boarding\n"
    "October is folding the light off the bay\n"
    "[Chorus]\nSo long, low tide, I am going inland\nAutumn is closing the door on the coast"
)
OFF_THEME_LYRIC = (
    "[Verse]\nStatic on the wire, a fire I can't put out\n"
    "Every word I swallow leaves me hollow and loud\n"
    "[Chorus]\nCut through the static, let it scream\nI am the signal in the dream"
)
CLEAN_LYRIC = "[Verse]\nThe kettle sings, the morning is ordinary\nI fold the washing while the radio plays"
EXPLICIT_LYRIC = "[Verse]\nFuck the quiet, fuck the polite goodbye\nI drink until the ceiling spins and tell them all to die"
HATEFUL_LYRIC = "[Verse]\nThose people are vermin and should be driven out\nThere is no place for them among us"

# One case per property: the target the requirement carries, the artifact that satisfies it, and the
# artifact that violates it. `target_path` is the state path the shipped question names, which is the
# path the target would have to occupy for that question to be answerable at all.
CASES = [
    {
        "property": "genre_fidelity",
        "field": "caption",
        "target": "Rap Rock, Nu Metal, Electronic",
        "target_path": "brief.genre",
        "code_terms": ["Rap Rock", "Nu Metal", "Electronic"],
        "matched": CAPTION,
        "mismatched": "Bossa Nova, Lounge, Acoustic, Soft, Warm, Intimate, Nylon Guitar",
    },
    {
        "property": "instrumentation",
        "field": "caption",
        "target": "Live Drums, Distorted Guitar, Distorted Bass, Power Chords, Guitar Riffs",
        "target_path": "brief.instruments",
        "code_terms": ["Live Drums", "Distorted Guitar", "Distorted Bass", "Power Chords", "Guitar Riffs"],
        "matched": CAPTION,
        "mismatched": CAPTION.replace("Distorted Guitar", "Banjo").replace("Power Chords", "Fiddle"),
    },
    {
        "property": "era_production",
        "field": "caption",
        "target": "Polished Production, Layered Production",
        "target_path": "brief.era",
        "code_terms": ["Polished Production", "Layered Production"],
        "matched": CAPTION,
        "mismatched": "Lo-Fi Production, Raw, Bedroom, Minimal, Vintage, Muddy",
    },
    {
        "property": "timbre",
        "field": "caption",
        "target": "Punchy, Bright",
        "target_path": "target",
        "code_terms": ["Punchy", "Bright"],
        "matched": CAPTION,
        "mismatched": "Warm, Dark, Muddy, Velvety, Smooth",
    },
    {
        "property": "vocal_spec",
        "field": "caption",
        "target": "Male Rap Vocals, Male Tenor Vocals, Clean Vocals",
        "target_path": "target",
        "code_terms": ["Male Rap Vocals", "Male Tenor Vocals", "Clean Vocals"],
        "matched": CAPTION,
        "mismatched": "Female Soprano Vocals, Whispered Delivery, Breathy Whispers",
    },
    {
        "property": "energy",
        "field": "caption",
        "target": "Dynamic Energy",
        "target_path": "target",
        "code_terms": ["Dynamic Energy"],
        "matched": CAPTION,
        "mismatched": "Very Low Energy, Low Energy, Soft Delivery, Sparse",
    },
    {
        "property": "groove_fidelity",
        "field": "caption",
        "target": "Driving, Syncopated",
        "target_path": "brief.groove",
        "code_terms": ["Driving", "Syncopated"],
        "matched": CAPTION,
        "mismatched": "Laid-Back, Straight, Four-on-the-Floor",
    },
    {
        "property": "theme",
        "checker": "jev.theme_adherence",
        "field": "lyrics",
        "target": "leaving a coastal town in autumn",
        "target_path": "brief.theme",
        "code_terms": None,
        "matched": THEME_LYRIC,
        "mismatched": OFF_THEME_LYRIC,
    },
    {
        "property": "explicitness",
        "field": "lyrics",
        "target": "no swearing or explicit content",
        "target_path": "brief.explicitness",
        "code_terms": None,
        "matched": CLEAN_LYRIC,
        "mismatched": EXPLICIT_LYRIC,
    },
    {
        "property": "content_policy",
        "field": "lyrics",
        "target": "no hateful or harassing content",
        "target_path": None,
        "code_terms": None,
        "matched": CLEAN_LYRIC,
        "mismatched": HATEFUL_LYRIC,
    },
]


def post(payload: dict, key: str, endpoint: str, timeout: float = 90.0) -> tuple[dict | None, str | None]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}"
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}"


def shipped_question(bank: dict, case: dict) -> dict:
    checker = case.get("checker") or f"jev.{case['property']}"
    entry = bank["questions"][checker]
    question = {
        "id": case["property"],
        "type": entry["type"],
        "instructions": entry["instructions"],
        "reads": entry["reads"],
    }
    if entry["type"] == "noul":
        question["criteria"] = entry["criteria"]
        question["polarity"] = entry.get("polarity", "goal")
    else:
        question["levels"] = entry["levels"]
        question["bound"] = entry.get("default_bound")
    return question


def property_question(case: dict) -> dict:
    field = case["field"]
    return {
        "id": case["property"],
        "type": "noul",
        "instructions": f"Does `{field}` carry what `target` asks for?",
        "criteria": {
            "true": f"Everything `target` asks for is present in `{field}`: each named item appears by name or by an unmistakable synonym, and nothing in `{field}` contradicts it.",
            "false": f"At least one item `target` asks for is absent from `{field}`, or `{field}` states something that contradicts it. A related item is not the item asked for.",
        },
        "reads": [field, "target"],
    }


def real_state() -> dict:
    """The state the battery actually builds for the song, which is the honest as-built baseline."""
    from spikes.jev_battery import load_draft

    return spec.interpret(load_draft(SONG))["state"]


def build_state(case: dict, variant: str, *, with_target: bool, target_path: str | None = None) -> dict:
    state = json.loads(json.dumps(BASE_STATE))
    state[case["field"]] = case[variant]
    path = case["target_path"] if target_path is None else target_path
    if with_target and path:
        head, _, tail = path.partition(".")
        if tail:
            state.setdefault(head, {})[tail] = case["target"]
        else:
            state[head] = case["target"]
    return state


def read_value(question: dict, answer: dict) -> float | None:
    if not answer:
        return None
    if question["type"] == "noul":
        value = answer.get("noul")
        return float(value) if isinstance(value, (int, float)) else None
    probabilities = answer.get("probabilities") or {}
    if not probabilities:
        return None
    keys = sorted(probabilities, key=lambda k: int(k) if str(k).isdigit() else 0)
    return float(max(range(len(keys)), key=lambda i: probabilities[keys[i]]) + 1)


def send(key: str, endpoint: str, model: str, question: dict, state: dict) -> tuple[float | None, str | None]:
    body = {"state": state, "model": model, "questions": {question["id"]: jev.question_payload(question)}}
    response, error = post(body, key, endpoint)
    if error:
        return None, error
    answer = ((response or {}).get("answers") or {}).get(question["id"]) or {}
    return read_value(question, answer), None


def code_containment(terms: list[str], text: str) -> bool:
    lowered = text.lower()
    return all(term.lower() in lowered for term in terms)


def on_expected_side(value: float | None, kind: str, matched: bool, polarity: str = "goal") -> bool:
    if value is None:
        return False
    if kind == "noul":
        # A violation question asks whether the failure is present, so the passing side is the low one.
        if polarity == "violation":
            return value <= 0.30 if matched else value >= 0.70
        return value >= 0.70 if matched else value <= 0.30
    # A score arrives as a level; the bank's default bound of 3 is the pass.
    return value >= 3 if matched else value < 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=jev.DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=jev.ENDPOINT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 2

    bank = oracle.load_bank()
    global BASE_STATE
    BASE_STATE = real_state()
    print(f"as-built state fields: {sorted(BASE_STATE)}\n")
    results: list[dict] = []

    def record(arm: str, case: dict, variant: str, kind: str, value, error, polarity: str = "goal"):
        results.append(
            {
                "arm": arm,
                "property": case["property"],
                "variant": variant,
                "expected": variant == "matched",
                "kind": kind,
                "polarity": polarity,
                "value": value,
                "error": error,
            }
        )

    for case in CASES:
        question = shipped_question(bank, case)
        kind = question["type"]
        for variant in ("matched", "mismatched"):
            state = build_state(case, variant, with_target=False)
            value, error = send(key, args.endpoint, args.model, question, state)
            record("score-question", case, variant, kind, value, error, question.get("polarity", "goal"))

            state = build_state(case, variant, with_target=True)
            value, error = send(key, args.endpoint, args.model, question, state)
            record("score+target", case, variant, kind, value, error, question.get("polarity", "goal"))

            state = build_state(case, variant, with_target=True, target_path="target")
            value, error = send(key, args.endpoint, args.model, property_question(case), state)
            record("property-noul", case, variant, "noul", value, error)

        if case["code_terms"]:
            record("code", case, "matched", "code", code_containment(case["code_terms"], case["matched"]), None)
            record("code", case, "mismatched", "code", code_containment(case["code_terms"], case["mismatched"]), None)

    by_arm: dict[tuple[str, str], dict] = {}
    for result in results:
        by_arm.setdefault((result["arm"], result["property"]), {})[result["variant"]] = result

    arms = ["score-question", "score+target", "property-noul", "code"]
    properties = [case["property"] for case in CASES]
    print(f"model {args.model}\n")
    print(f"  {'property':<16} " + " ".join(f"{arm:>26}" for arm in arms))
    for prop in properties:
        cells = []
        for arm in arms:
            pair = by_arm.get((arm, prop)) or {}
            value_kind = pair.get("matched", {}).get("kind")
            cells.append(
                f"{_fmt(pair.get('matched', {}).get('value'), value_kind):>11} / "
                f"{_fmt(pair.get('mismatched', {}).get('value'), value_kind):<12}"
            )
        print(f"  {prop:<16} " + " ".join(cells))

    print("\n  cell = value on the matched artifact / value on the violated artifact")
    print("  noul: >=0.70 is the pass, <=0.30 the fail; score: the level; code: containment")
    print("\n  separation -- matched on the passing side and violated on the failing side:")
    for arm in arms:
        kind_of = lambda prop: (by_arm.get((arm, prop)) or {}).get("matched", {}).get("kind")  # noqa: E731
        scoped = [p for p in properties if (by_arm.get((arm, p)) or {})]
        if arm == "code":
            scoped = [p for p in scoped if kind_of(p) == "code"]
            good = sum(
                1
                for p in scoped
                if by_arm[(arm, p)]["matched"]["value"] is True and by_arm[(arm, p)]["mismatched"]["value"] is False
            )
            print(f"    {arm:<16} {good}/{len(scoped)} properties")
            continue
        good = sum(
            1
            for p in scoped
            if on_expected_side(
                by_arm[(arm, p)]["matched"]["value"],
                kind_of(p),
                True,
                by_arm[(arm, p)]["matched"].get("polarity", "goal"),
            )
            and on_expected_side(
                by_arm[(arm, p)]["mismatched"]["value"],
                kind_of(p),
                False,
                by_arm[(arm, p)]["mismatched"].get("polarity", "goal"),
            )
        )
        print(f"    {arm:<16} {good}/{len(scoped)} properties")

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"\n  {len(errors)} request errors; first: {errors[0]['error']}")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / f"jev-property-probe-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps({"model": args.model, "results": results}, indent=2, default=str))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


def _fmt(value, kind) -> str:
    if value is None:
        return "-"
    if kind == "code":
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
