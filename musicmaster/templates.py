"""Instantiate a structure template: as a writing brief, a bar plan, or a time budget.

A template is a contract, so it has three jobs. Handed to a lyric writer it is a brief: which
sections, in what order, how many lines, which rhyme scheme, at what intensity -- and, crucially,
how many seconds and how many syllables each section has room for. Handed to the composer it is a
plan: bars per section and where each section starts at the chosen tempo. And because a song is
not all vocal, the third job is the one that decides whether the lyric fits at all: the time
budget, which reserves the instrumental sections and puts a hard syllable ceiling on the rest.

The arithmetic -- bars to seconds, sections to start times, time to syllables, and scaling a
template to a target duration -- is done here in code, which is the same division the rest of the
design uses. A language model should never be asked to compute a timestamp.

    python3 vocabulary/structure_templates.py --list
    python3 vocabulary/structure_templates.py --template=pop_standard --brief
    python3 vocabulary/structure_templates.py --template=pop_standard --timeline --bpm=95 --duration=180
    python3 vocabulary/structure_templates.py --template=pop_standard --bpm=95 --duration=180
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import timeline as T

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_PATH = ROOT / "vocabulary" / "structure-templates.json"
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
RHYME_PATH = ROOT / "vocabulary" / "rhyme-schemes.json"


def scale_to_duration(sections: list[dict], target_s: float, bpm: float) -> tuple[list[dict], float]:
    """Scale every section's bars so the total lands near the target duration.

    Bars are rounded to even numbers so the result stays musically plausible, and a section never
    drops below two bars. The achieved duration is returned so the drift is visible rather than
    silently accepted.
    """
    total_bars = sum(s["bars"] for s in sections)
    target_bars = target_s * bpm / (T.BEATS_PER_BAR * 60.0)
    factor = target_bars / total_bars
    scaled = []
    for s in sections:
        bars = max(2, int(round(s["bars"] * factor / 2.0)) * 2)
        scaled.append({**s, "bars": bars})
    return scaled, T.seconds_for_bars(sum(s["bars"] for s in scaled), bpm)


def print_list(templates: list[dict]) -> None:
    print(f"{'id':<24}{'bars':>5}  {'sections':>8}  {'instr':>6}  name")
    for t in templates:
        bars = sum(s["bars"] for s in t["sections"])
        instr = sum(1 for s in t["sections"] if not s.get("lines"))
        print(f"{t['id']:<24}{bars:>5}  {len(t['sections']):>8}  {instr:>6}  {t['name']}")
        if t.get("summary"):
            print(f"{'':<24}{'':>5}  {'':>8}  {'':>6}  {t['summary']}")


def print_plan(plan: dict, achieved: float | None) -> None:
    t = plan
    print(f"template: {t['template_id']} -- {t['template_name']}")
    print(f"  tempo: {t['bpm']:g} BPM, {T.BEATS_PER_BAR}/4")
    print(f"  delivery: {t['profile_label']} (band {t['band'][0]}-{t['band'][1]} syllables per line)")

    print(f"\n  {'#':>2}  {'section':<22}{'bars':>5}{'lines':>6}{'rhyme':>7}{'energy':>7}  {'start':>6}{'dur':>7}")
    for r in t["rows"]:
        label = r["label"] + (" (opt)" if r["optional"] else "")
        print(
            f"  {r['index']:>2}  {label[:22]:<22}{r['bars']:>5}{r['lines'] or '-':>6}"
            f"{r['rhyme_scheme'] or '-':>7}{r['energy'] or '-':>7}"
            f"  {T.mmss(r['start_s']):>6}{r['dur_s']:>6.1f}s"
        )

    tot = t["totals"]
    print(f"\n  total: {tot['bars']} bars, {T.mmss(tot['total_s'])} ({tot['total_s']:.1f}s)")
    if achieved is not None:
        print(f"  scaled to the requested duration; achieved {achieved:.1f}s")


def print_timeline(plan: dict, achieved: float | None) -> None:
    t = plan
    tot = t["totals"]
    print(f"template: {t['template_id']} -- {t['template_name']}")
    print(f"  tempo: {t['bpm']:g} BPM, {T.BEATS_PER_BAR}/4   delivery: {t['profile_label']}")
    print(
        f"  total {T.mmss(tot['total_s'])} ({tot['total_s']:.1f}s)"
        f"  |  vocal {T.mmss(tot['vocal_s'])} ({tot['vocal_s']:.1f}s)"
        f"  |  instrumental {T.mmss(tot['instrumental_s'])} ({tot['instrumental_s']:.1f}s)"
        f"  |  {tot['instrumental_sections']} of {tot['sections']} sections carry no vocal"
    )
    if achieved is not None:
        print(f"  scaled to the requested duration; achieved {achieved:.1f}s")

    print(
        f"\n  {'#':>2}  {'section':<22}{'vocal':>6}{'bars':>5}{'lines':>6}"
        f"{'start':>7}{'dur':>8}{'singable':>10}{'budget':>9}{'ceiling':>9}{'density':>9}"
    )
    for r in t["rows"]:
        label = r["label"] + (" (opt)" if r["optional"] else "")
        budget = f"{r['budget_min']}-{r['budget_max']}" if r["lines"] else "-"
        ceiling = str(r["ceiling"]) if not r["instrumental"] else "-"
        if r["instrumental"]:
            density = "-"
        else:
            rate = r["rate_at_budget_max"]
            density = f"{rate:.2f}/s"
            if not r["budget_fits"]:
                density += " !!"
            elif r["sparse"]:
                density += " ~"
        print(
            f"  {r['index']:>2}  {label[:22]:<22}{'no' if r['instrumental'] else 'yes':>6}"
            f"{r['bars']:>5}{r['lines'] or '-':>6}"
            f"{T.mmss(r['start_s']):>7}{r['dur_s']:>7.1f}s{r['singable_s']:>9.1f}s"
            f"{budget:>9}{ceiling:>9}{density:>9}"
        )

    print(
        f"\n  lyric budget {tot['budget_min']}-{tot['budget_max']} syllables across "
        f"{tot['vocal_lines']} lines; comfortable ceiling ~{tot['comfortable_max']}, "
        f"hard ceiling ~{tot['ceiling']}"
    )
    print("  (the budget is guidance from the delivery profile; the ceiling is the clock)")
    print(
        f"  density is the rate at the top of the budget, against a comfortable "
        f"{t['profile_label']} ceiling of {T.rate_profile(T.load_delivery_rates(), t['profile'])['comfortable_max']}/s"
    )
    misfit = [r for r in t["rows"] if not r["instrumental"] and not r["budget_fits"]]
    if misfit:
        print(
            f"  !! {len(misfit)} section(s) cannot hold even the minimum budget in the time "
            f"available: the template and the delivery profile disagree"
        )
    sparse = [r for r in t["rows"] if r.get("sparse")]
    if sparse:
        print(
            f"  ~  {len(sparse)} section(s) are sparse at the top of the budget (marked ~): the "
            f"section is long for the lines it carries, which is what scaling a template to a "
            f"longer duration does. Either accept a roomier delivery, raise the tempo, or carry "
            f"more lines"
        )


def print_brief(plan: dict, notes: str | None, st: dict) -> None:
    t = plan
    tot = t["totals"]
    print(f"WRITING BRIEF -- {t['template_name']} ({t['template_id']})")
    print(
        f"{T.mmss(tot['total_s'])} total, of which {T.mmss(tot['vocal_s'])} is sung "
        f"and {T.mmss(tot['instrumental_s'])} is instrumental. Write words only for the "
        f"singable sections."
    )
    print()
    print("Write one section per block below, in this order. Put the tag on its own line,")
    print("then the lines, then a blank line before the next section.")
    print()

    labels = T.tag_label_map(st)
    for r in t["rows"]:
        label = r["label"] + ("   (optional)" if r["optional"] else "")
        print(f"  [{label}]")
        if r["instrumental"]:
            print(f"      instrumental, {r['bars']} bars, {r['dur_s']:.1f}s -- no words here")
            if r["energy_tags"]:
                tags = "  ".join(f"[{labels.get(i, i)}]" for i in r["energy_tags"])
                print(f"      place this under the header: {tags}")
            if r.get("transition_out"):
                print(f"      leave this section with: "
                      f"[{labels.get(r['transition_out'], r['transition_out'])}]")
        else:
            details = [
                f"{r['bars']} bars, {r['dur_s']:.1f}s",
                f"{r['lines']} lines",
                f"budget {r['budget_min']}-{r['budget_max']} syllables",
            ]
            if r["effective_per_line"] < t["band"][1]:
                details.append(
                    f"at most {r['effective_per_line']} syllables per line here "
                    f"(the clock, not the band, is the limit)"
                )
            if r["rhyme_scheme"]:
                details.append(f"rhyme {r['rhyme_scheme']}")
            if r["energy"]:
                details.append(f"energy {r['energy']}/5")
            if r["hook"]:
                details.append("this is the hook")
            print(f"      {' | '.join(details)}")
            print(f"      at most {r['ceiling']} syllables can be sung in the time available")
            wanted = list(r.get("vocals") or []) + list(r.get("energy_tags") or [])
            if wanted:
                tags = "  ".join(f"[{labels.get(i, i)}]" for i in wanted)
                print(f"      place these performance tags under the header, one per line: {tags}")
            if r.get("transition_out"):
                print(f"      leave this section with: "
                      f"[{labels.get(r['transition_out'], r['transition_out'])}]")
        print()

    print("Rules")
    print(f"  - {t['band'][0]}-{t['band'][1]} syllables per line for this delivery; keep lines in")
    print("    the same position across repeated sections within 2 syllables.")
    print("  - Count syllables per phrase, not per printed line: cadence splits lines, so a")
    print("    caesura marker ( / or | ) may be written inside a line and is never sung.")
    print("  - At most one modifier per tag, written [Section - modifier].")
    print("  - Up to four standalone performance tags per section, each on its own line, which is")
    print("    how the model's guide presents vocal and energy control as against section modifiers.")
    print("  - Uppercase inside a line means louder delivery; parentheses mean backing vocal.")
    print("  - Keep one core metaphor for the whole song rather than mixing images.")
    if notes:
        print(f"\nNote\n  {notes}")


def main(argv: list[str]) -> int:
    doc = T.load(TEMPLATES_PATH)
    st = T.load(SECTION_TAGS_PATH)
    rates = T.load_delivery_rates()
    templates = {t["id"]: t for t in doc["templates"]}

    if "--list" in argv or len(argv) == 1:
        print_list(doc["templates"])
        return 0

    tid = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--template=")), None)
    if not tid:
        print(__doc__)
        return 2
    t = templates.get(tid)
    if t is None:
        print(f"unknown template '{tid}'. Try --list")
        return 2

    bpm = float(next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--bpm=")), 120))
    target = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--duration=")), None)
    profile_id = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--profile=")), None)
    profile = T.rate_profile(rates, profile_id)

    sections = t["sections"]
    achieved = None
    if target is not None:
        sections, achieved = scale_to_duration(sections, float(target), bpm)

    plan = T.build_timeline({**t, "sections": sections}, bpm, st, profile, doc)

    if "--brief" in argv:
        print_brief(plan, t.get("notes"), st)
    elif "--timeline" in argv:
        print_timeline(plan, achieved)
    else:
        print_plan(plan, achieved)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
