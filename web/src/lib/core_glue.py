"""The browser-side face of the text tier.

Runs inside Pyodide against the same `musicmaster` package the CLI uses, with the repository
mounted at /repo. Everything crosses the JS boundary as a JSON string: the page owns the form and
the selection state, this owns the checks, and neither reimplements the other.

It lives beside the SPA rather than in the package because it is presentation plumbing -- loading
the vocabulary once and shaping results for a page -- not a rule about songs. Anything here that
turns out to be a rule belongs in musicmaster/ instead.
"""

import json
import sys

if "/repo" not in sys.path:
    sys.path.insert(0, "/repo")

from musicmaster import lyrics, render, templates, timeline  # noqa: E402

_vocab = render.load_vocabulary()
_section_tags = timeline.load(timeline.SECTION_TAGS_PATH)
_templates_doc = timeline.load(timeline.TEMPLATES_PATH)
_rates = timeline.load_delivery_rates()


def _template(template_id):
    return {t["id"]: t for t in _templates_doc["templates"]}[template_id]


def _profile(selections):
    return timeline.profile_for_vocals(selections, _rates)


def render_selections(payload):
    """The tag string, what the budget dropped, the negatives, and any coherence problems."""
    selections = json.loads(payload)
    profile = _profile(selections)
    return json.dumps(
        {
            **render.render(_vocab, selections),
            "problems": render.coherence_check(_vocab, selections),
            "profile": profile["label"],
            "band": list(profile["band"]),
            "budget": _vocab["tag_budget"],
        }
    )


def plan(payload):
    """The time budget for a template at a tempo, optionally scaled to a target duration.

    The delivery profile is derived from the selections when they are supplied, because the budget
    is delivery-dependent: a rapped verse measured against the sung band (6-10 syllables a line)
    states a range nobody is aiming for, where the rapped band is 8-16. An explicit `profile_id`
    still wins, which is the precedence the lyric checker already uses.
    """
    request = json.loads(payload)
    template_id = request["template_id"]
    bpm = float(request["bpm"])
    duration = request.get("duration_s")
    profile_id = request.get("profile_id")
    selections = request.get("selections")

    template = _template(template_id)
    if profile_id:
        profile = timeline.rate_profile(_rates, profile_id)
    elif selections:
        profile = _profile(selections)
    else:
        profile = timeline.rate_profile(_rates, None)

    sections = template["sections"]
    achieved = None
    if duration:
        sections, achieved = templates.scale_to_duration(sections, float(duration), bpm)

    built = timeline.build_timeline(
        {**template, "sections": sections}, bpm, _section_tags, profile, _templates_doc
    )
    return json.dumps(
        {
            "template_id": template_id,
            "template_name": template["name"],
            "bpm": bpm,
            "achieved_s": achieved,
            "profile_label": profile["label"],
            **built,
        }
    )


def check_lyric(payload):
    """The checker's findings, plus the per-section numbers the inspector pane reads."""
    request = json.loads(payload)
    lines = request["text"].splitlines()
    selections = request.get("selections") or {}
    template_id = request.get("template_id")
    bpm = float(request.get("bpm") or 120.0)

    report = lyrics.Report()
    found = lyrics.analyse(lines, _section_tags, report)
    lyrics.check_blank_lines(lines, _section_tags, report)
    lyrics.check_consistency(found, _section_tags, _vocab, selections, report)
    lyrics.check_cliches(lines, report)
    band = tuple(_profile(selections)["band"]) if selections else None
    meter = lyrics.check_meter_and_rhyme(lines, _section_tags, report, band=band)

    conformance = None
    if template_id:
        template = _template(template_id)
        plan_ = json.loads(
            plan(json.dumps({"template_id": template_id, "bpm": bpm, "selections": selections}))
        )
        conformance = lyrics.check_template(meter, _section_tags, template, report, plan=plan_)

    return json.dumps(
        {
            "lines": len(lines),
            "sections": meter["sections"],
            "errors": report.errors,
            "warnings": report.warnings,
            "oracle_tasks": report.oracle_tasks,
            "conformance": conformance,
        }
    )
