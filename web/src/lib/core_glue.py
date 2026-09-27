"""The browser-side face of the text tier.

Runs inside Pyodide against the same `musicmaster` package the CLI uses, with the repository
mounted at /repo. Everything crosses the JS boundary as a JSON string: the page owns the form, the
selection state and the editing, this owns the checks and the generated structure, and neither
reimplements the other.

It lives beside the SPA rather than in the package because it is presentation plumbing -- loading
the vocabulary once and shaping results for a page -- not a rule about songs. Anything here that
turns out to be a rule belongs in musicmaster/ instead.
"""

import contextlib
import io
import json
import sys

if "/repo" not in sys.path:
    sys.path.insert(0, "/repo")

from musicmaster import lyrics, prompt, render, templates, timeline  # noqa: E402

_vocab = render.load_vocabulary()
_section_tags = timeline.load(timeline.SECTION_TAGS_PATH)
_templates_doc = timeline.load(timeline.TEMPLATES_PATH)
_rates = timeline.load_delivery_rates()
_tag_labels = timeline.tag_label_map(_section_tags)
_section_meta = timeline.section_meta(_section_tags)


def _template(template_id):
    return {t["id"]: t for t in _templates_doc["templates"]}[template_id]


def _profile(selections):
    return timeline.profile_for_vocals(selections, _rates)


def _build_plan(request):
    """Build a timeline once, so the plan, the brief and the scaffold cannot disagree.

    The delivery profile is derived from the selections when they are supplied, because the budget
    is delivery-dependent: a rapped verse measured against the sung band (6-10 syllables a line)
    states a range nobody is aiming for, where the rapped band is 8-16. An explicit `profile_id`
    still wins, which is the precedence the lyric checker already uses.
    """
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
    return template, {
        "template_id": template_id,
        "template_name": template["name"],
        "bpm": bpm,
        "achieved_s": achieved,
        "profile_label": profile["label"],
        **built,
    }


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
    """The time budget for a template at a tempo, optionally scaled to a target duration."""
    _, built = _build_plan(json.loads(payload))
    return json.dumps(built)


def brief(payload):
    """The writing brief, captured from the same printer the CLI uses rather than re-worded here."""
    request = json.loads(payload)
    template, built = _build_plan(request)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        templates.print_brief(built, template.get("notes"), _section_tags)
    return json.dumps({"brief": buffer.getvalue()})


def scaffold(payload):
    """A structurally correct empty lyric: every section header in order, the performance tags that
    section asks for, and the transition it leaves on.

    No words and no line placeholders. An empty line is not a lyric the checker can count, and a
    placeholder would be counted as one; the line counts and syllable budgets belong in the brief and
    the inspector, where they read as targets. What the scaffold guarantees is the part that is
    mechanical: the right sections, the right tags, the right order, and the blank-line discipline.
    """
    request = json.loads(payload)
    template = _template(request["template_id"])

    occurrences: dict[str, int] = {}
    for section in template["sections"]:
        occurrences[section["role"]] = occurrences.get(section["role"], 0) + 1

    seen: dict[str, int] = {}
    out: list[str] = []
    for section in template["sections"]:
        role = section["role"]
        seen[role] = seen.get(role, 0) + 1
        out.append(f"[{timeline.section_label(_section_meta, role, seen[role], occurrences[role])}]")

        for tag_id in [*(section.get("vocals") or []), *(section.get("energy_tags") or [])]:
            out.append(f"[{_tag_labels.get(tag_id, tag_id)}]")

        transition = section.get("transition_out")
        if transition:
            # A transition belongs to the section it leaves, after the words. With no words yet it
            # sits below the gap the writer is about to fill.
            out.append("")
            out.append(f"[{_tag_labels.get(transition, transition)}]")

        out.append("")

    return json.dumps({"text": "\n".join(out)})


def artifacts(payload):
    """The canonical prompt, the composition it pins, and the ComfyUI graph it renders to.

    The same `musicmaster.prompt` the CLI writes, given what the page already holds: a static page
    has no song directory to read, so the lyrics, the brief and the selections come from the editor
    instead of from disk.
    """
    request = json.loads(payload)
    built = prompt.build(
        {
            "song_id": request["song_id"],
            "template_id": request["template_id"],
            "bpm": request["bpm"],
            "seed": request["seed"],
            "selections": request["selections"],
            "lyrics": request["lyrics"],
            "brief": request.get("brief") or "",
            "artist_references": request.get("artist_references") or [],
            "vocabulary_path": "/repo/vocabulary/tag-bins.json",
            "vocabulary": _vocab,
            "section_tags": _section_tags,
            "templates_doc": _templates_doc,
            "rates": _rates,
        }
    )
    return json.dumps(
        {
            "prompt": built["prompt"],
            "composition": built["composition"],
            "workflow": built["workflow"],
            "prompt_sha256": built["prompt_sha256"],
            # Serialised once, by the same function the hashes go through, so a download and a
            # hash cannot disagree about what the artifact is.
            "prompt_text": prompt.serialise(built["prompt"]),
            "composition_text": prompt.serialise(built["composition"]),
            "workflow_text": prompt.serialise(built["workflow"]),
        }
    )


def preview(payload):
    """A full-length, coarse preview graph: the current caption plus one row per variant.

    The language model's cost is per pass, not per caption -- a full-length song is the same number
    of sequential tokens whether one caption rides along or twelve -- so several captions in one
    submission is how "what does this tag do" gets answered cheaply. The graph ends in
    PreviewAudio, so a preview never lands in the render output directory.

    Variants are given as bin/option pairs and applied to the page's own selections, so what is
    previewed is the caption the page would actually send.
    """
    request = json.loads(payload)
    built = prompt.build(
        {
            "song_id": request["song_id"],
            "template_id": request["template_id"],
            "bpm": request["bpm"],
            "seed": request["seed"],
            "selections": request["selections"],
            "lyrics": request["lyrics"],
            "brief": request.get("brief") or "",
            "artist_references": request.get("artist_references") or [],
            "vocabulary_path": "/repo/vocabulary/tag-bins.json",
            "vocabulary": _vocab,
            "section_tags": _section_tags,
            "templates_doc": _templates_doc,
            "rates": _rates,
        }
    )
    captions = [built["prompt"]["style"]["rendered_string"]]
    names = ["current"]
    for variant in request.get("variants") or []:
        selections = json.loads(json.dumps(request["selections"]))
        entry = selections.setdefault(variant["bin"], {"options": []})
        options = entry.setdefault("options", [])
        if variant["option"] in options:
            options.remove(variant["option"])
        else:
            options.append(variant["option"])
        captions.append(render.render(_vocab, selections)["string"])
        names.append(f"{variant['bin']}:{variant['option']}")

    workflow = prompt.build_preview_workflow(
        built["prompt"],
        request["lyrics"],
        captions,
        seconds=request.get("seconds"),
        steps=int(request.get("steps") or prompt.PREVIEW_STEPS),
    )
    return json.dumps({"workflow": workflow, "captions": captions, "names": names})


def check_lyric(payload):
    """The checker's findings, the per-section numbers, and where each section starts."""
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
        _, built = _build_plan(
            {"template_id": template_id, "bpm": bpm, "selections": selections}
        )
        conformance = lyrics.check_template(meter, _section_tags, template, report, plan=built)

    # Where each section starts, so the editor can tell which one the caret is in. Paired by index
    # with `sections`, which walks the same boundaries.
    outline = [
        {"line": entry["line"], "role": entry.get("section")}
        for entry in found
        if entry.get("section")
    ]

    return json.dumps(
        {
            "lines": len(lines),
            "sections": meter["sections"],
            "outline": outline,
            "errors": report.errors,
            "warnings": report.warnings,
            "notes": report.notes,
            "oracle_tasks": report.oracle_tasks,
            "conformance": conformance,
        }
    )
