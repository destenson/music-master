"""The time budget for a lyric.

The bar plan says how long each section is; this says how much of that time is *singable*, and
how many syllables fit in it. That distinction is the whole point: a three-minute song with a
ten-second intro, an eight-second outro, a four-bar bridge and an instrumental break has
considerably less than three minutes of room for words, and a lyric written to the printed line
count alone will not fit.

Two different numbers come out of it, and conflating them is a mistake:

* a **budget**, in the writer's terms, `lines x band` -- guidance, inherited from the delivery
  profile, and the thing the brief states;
* a **ceiling**, in physics, `singable seconds x syllables per second` -- the hard limit, which
  is what actually decides whether a line can be sung in the time available.

Rap makes the distinction visible: a rapped line carries far more syllables than a sung one, so
the band moves with the delivery while the ceiling stays a property of the clock.

All of it is arithmetic on data that already exists, so it belongs in code rather than in a
model's head.

    from timeline import build_timeline, check_fit
    plan = build_timeline(template, bpm=95, section_tags=st, profile=prof)
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_PATH = ROOT / "vocabulary" / "structure-templates.json"
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
DELIVERY_RATES_PATH = ROOT / "vocabulary" / "delivery-rates.json"

BEATS_PER_BAR = 4  # the templates assume 4/4


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def seconds_for_bars(bars: int, bpm: float) -> float:
    return bars * BEATS_PER_BAR * 60.0 / bpm


def section_meta(section_tags: dict) -> dict[str, dict]:
    """Role -> {'label', 'instrumental', 'numbered'}, keyed without the 'sec_' prefix."""
    return {
        s["id"].removeprefix("sec_"): {
            "label": s["label"],
            "instrumental": bool(s.get("instrumental")),
            "numbered": bool(s.get("numbered")),
        }
        for s in section_tags["sections"]
    }


def section_label(meta: dict[str, dict], role: str, occurrence: int, total: int) -> str:
    m = meta.get(role, {})
    label = m.get("label", role)
    if total > 1 and m.get("numbered"):
        return f"{label} {occurrence}"
    return label


# --- Delivery profiles -------------------------------------------------------------------

def load_delivery_rates(path: Path = DELIVERY_RATES_PATH) -> dict:
    return load(path)


def rate_profile(rates: dict, profile_id: str | None) -> dict:
    profiles = {p["id"]: p for p in rates["profiles"]}
    return profiles.get(profile_id or rates["default"], next(iter(profiles.values())))


def profile_for_vocals(selections: dict, rates: dict) -> dict:
    """Pick a delivery profile from the tag selections, so a rap verse is not judged as a ballad.

    A heuristic over option ids, not a judgement about the song: it exists so the band and the
    rate ceiling are in the right range, and it is reported alongside every number it produced.
    """
    opts: set[str] = set()
    for bin_id in ("lead_vocal", "vocal_delivery", "genre", "groove", "fusion"):
        opts.update((selections.get(bin_id) or {}).get("options") or [])
    joined = " ".join(sorted(opts))

    if any(k in joined for k in ("instrumental", "no_vocals")):
        return rate_profile(rates, "instrumental")
    if "double_time" in joined:
        return rate_profile(rates, "double_time")
    # "rapid_fire" describes a delivery, not a tempo: a fast rapper is still a rapper, and jumping
    # to the double-time ceiling would judge every verse against a rate nobody is aiming for.
    if any(k in joined for k in ("rap", "drill", "grime", "phonk", "hip_hop", "rapid_fire")):
        return rate_profile(rates, "rapped")
    if any(k in joined for k in ("up_tempo", "energy_high", "energy_very_high", "punk", "metal", "drum_and_bass")):
        return rate_profile(rates, "sung_fast")
    if any(k in joined for k in ("slow_jam", "downtempo", "ballad", "ambient", "energy_very_low", "folk")):
        return rate_profile(rates, "sung_slow")
    return rate_profile(rates, rates["default"])


# --- The plan ----------------------------------------------------------------------------

def tag_label_map(section_tags: dict) -> dict[str, str]:
    """id -> display label for every tag pool, so plans and briefs can name them."""
    out: dict[str, str] = {}
    for pool in ("vocal_tags", "energy_tags", "instrumental_section_tags", "transition_tags",
                 "modifiers", "sections"):
        for t in section_tags.get(pool, []):
            out[t["id"]] = t["label"]
    return out


def build_timeline(
    template: dict,
    bpm: float,
    section_tags: dict,
    profile: dict,
    templates_doc: dict | None = None,
) -> dict:
    """Turn a template into a timed plan with a singable budget and a hard ceiling per section."""
    doc = templates_doc or load(TEMPLATES_PATH)
    band = tuple(profile.get("band") or doc.get("default_syllable_band", [6, 10]))

    meta = section_meta(section_tags)
    totals_by_role: dict[str, int] = {}
    for s in template["sections"]:
        totals_by_role[s["role"]] = totals_by_role.get(s["role"], 0) + 1

    rows: list[dict] = []
    seen: dict[str, int] = {}
    start = 0.0
    for i, s in enumerate(template["sections"], start=1):
        role = s["role"]
        seen[role] = seen.get(role, 0) + 1
        m = meta.get(role, {})
        lines = s.get("lines") or 0
        instrumental = bool(m.get("instrumental")) or lines == 0
        dur = seconds_for_bars(s["bars"], bpm)
        singable = 0.0 if instrumental else dur
        ceiling = round(singable * profile["hard_max"])
        comfortable = round(singable * profile["comfortable_max"])
        # The budget is the delivery profile's band, clipped by the clock. Stating the band's top
        # when the section cannot hold it would be advice that is wrong on its face: a 4-bar
        # pre-chorus with 4 lines cannot carry 10 syllables a line at this tempo.
        budget_min = lines * band[0]
        budget_max = min(lines * band[1], ceiling) if lines else 0
        rate_at_budget_max = (budget_max / singable) if singable else 0.0
        rows.append(
            {
                "index": i,
                "role": role,
                "label": section_label(meta, role, seen[role], totals_by_role[role]),
                "optional": bool(s.get("optional")),
                "instrumental": instrumental,
                "bars": s["bars"],
                "lines": lines,
                "rhyme_scheme": s.get("rhyme_scheme"),
                "energy": s.get("energy"),
                "hook": bool(s.get("hook")),
                # Standalone performance tags the template asks for on this section, as ids from
                # the vocal_tags and energy_tags pools.
                "vocals": list(s.get("vocals") or []),
                "energy_tags": list(s.get("energy_tags") or []),
                "transition_out": s.get("transition_out"),
                "start_s": start,
                "dur_s": dur,
                "singable_s": singable,
                "budget_min": budget_min,
                "budget_max": budget_max,
                "effective_per_line": (
                    min(band[1], ceiling // lines) if lines else 0
                ),
                "comfortable_max": comfortable,
                "ceiling": ceiling,
                "rate_at_budget_max": rate_at_budget_max,
                # Does even the band's floor fit the clock? If not, the template and the delivery
                # profile disagree and no writer could satisfy both.
                "budget_fits": (not instrumental) and budget_min <= ceiling,
                "sparse": (
                    (not instrumental)
                    and rate_at_budget_max > 0
                    and rate_at_budget_max < profile["comfortable_max"] * 0.7
                ),
            }
        )
        start += dur

    total_s = start
    vocal_rows = [r for r in rows if not r["instrumental"]]
    return {
        "template_id": template["id"],
        "template_name": template["name"],
        "bpm": bpm,
        "band": list(band),
        "profile": profile["id"],
        "profile_label": profile["label"],
        "rows": rows,
        "totals": {
            "bars": sum(r["bars"] for r in rows),
            "sections": len(rows),
            "total_s": total_s,
            "vocal_s": sum(r["singable_s"] for r in rows),
            "instrumental_s": total_s - sum(r["singable_s"] for r in rows),
            "instrumental_sections": sum(1 for r in rows if r["instrumental"]),
            "vocal_lines": sum(r["lines"] for r in rows),
            "budget_min": sum(r["budget_min"] for r in rows),
            "budget_max": sum(r["budget_max"] for r in rows),
            "comfortable_max": sum(r["comfortable_max"] for r in vocal_rows),
            "ceiling": sum(r["ceiling"] for r in vocal_rows),
        },
    }


def check_fit(plan: dict, written: dict[str, int]) -> list[dict]:
    """Compare written syllables per section against the budget and the ceiling.

    ``written`` maps a section label, as it appears in the lyric, to its syllable count. Each
    finding is one of: ``lyrics_in_instrumental``, ``over_ceiling``, ``over_comfortable``,
    ``over_budget``, ``under_budget`` or ``ok``. Only the first three are problems.
    """
    findings: list[dict] = []
    for row in plan["rows"]:
        label = row["label"]
        n = written.get(label)

        if row["instrumental"]:
            if n:
                findings.append({
                    "label": label, "kind": "lyrics_in_instrumental",
                    "detail": f"{n} syllables written into an instrumental section",
                })
            continue

        if n is None:
            findings.append({
                "label": label, "kind": "missing",
                "detail": f"no lyric found for a vocal section with {row['lines']} lines",
            })
            continue

        kind, detail = "ok", f"{n} syllables"
        if n > row["ceiling"]:
            kind = "over_ceiling"
            detail = (
                f"{n} syllables but only ~{row['ceiling']} fit in "
                f"{row['singable_s']:.1f}s at {plan['bpm']:g} BPM; it cannot be sung in the time"
            )
        elif n > row["comfortable_max"]:
            kind = "over_comfortable"
            detail = (
                f"{n} syllables against a comfortable ~{row['comfortable_max']} in "
                f"{row['singable_s']:.1f}s; it will be rushed"
            )
        elif n > row["budget_max"]:
            kind = "over_budget"
            detail = f"{n} syllables over the {row['budget_min']}-{row['budget_max']} line budget"
        elif n < row["budget_min"]:
            kind = "under_budget"
            detail = f"{n} syllables under the {row['budget_min']}-{row['budget_max']} line budget"

        if kind == "ok":
            rate = n / row["singable_s"] if row["singable_s"] else 0.0
            detail += f" at {rate:.2f}/s"
        findings.append({"label": label, "kind": kind, "detail": detail})
    return findings
