"""Derive a RequirementSpec, and the state its questions read, from what the page holds.

The page has selections, a caption, a lyric, a tempo and a duration, and nothing that says which of
them are *requirements* a check could decide. Almost all of that is already data: every bin in the
vocabulary declares `maps_to`, the checker its selection becomes an obligation for, so the spec is
the selected bins grouped by that field rather than a second hand-kept table that could disagree
with the vocabulary.

**The stage decides the checker.** A draft exists before anything is rendered, so there are exactly
two artifacts that can be wrong, and each requirement here names one of them:

  * the **caption** -- the tag string the prompt will send -- is decided in *code*, because it is
    rendered from the selections: coverage, exclusions, coherence and the tag budget are exact
    facts about a string, not judgements;
  * the **lyrics** are decided by the *oracle*, because whether a lyric is about a theme, reads as
    a mood, or stays within an explicitness limit is irreducibly a judgement.

Properties of the rendered audio -- the genre it really reads as, the instruments a listener hears
-- are deliberately absent. They need a measurement or an independent description of a file that
does not exist yet, and asking a model to judge the input's own tag list would be a green tick for
a comparison that never happened. Those belong to the fact-sheet stage and are added there.

Two things this module will not do:

  * It invents no requirement the user did not choose. A bin with nothing selected contributes
    nothing, and a theme is a requirement only when a theme was written.
  * It reports no measurement it did not take. The requested tempo and duration go into a
    `planned` block, not `measured`, so a question that reads `measured` finds nothing rather than
    reading an intention as a fact.

    python3 -c "from musicmaster import spec; print(spec.interpret({'caption': 'Trap, Wistful'}))"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"

# The sound properties the renderer emits as tags. Their pre-render obligation is coverage of the
# caption: a model cannot tell the audio from the input, but code can tell that the tag was sent.
CAPTION_CHECKERS = (
    "jev.genre_fidelity",
    "jev.era_production",
    "jev.instrumentation",
    "jev.vocal_spec",
    "jev.timbre",
    "jev.energy",
    "jev.groove_fidelity",
    "jev.tuning_fidelity",
)

# The properties that are judgements about the words. A label appearing in the caption says nothing
# about whether the lyric delivers it, which is why these are not folded into the coverage test.
LYRIC_CHECKERS = (
    "jev.theme_adherence",
    "jev.mood_axis",
    "jev.hook_payoff",
    "jev.explicitness",
    "jev.content_policy",
    "jev.absence_of",
)

# Severity is about what a failure means, not how sure we are: a policy requirement is one whose
# breach rejects the song, and a soft one is a preference whose miss is worth reporting and not
# worth failing. The lyric severity of a policy checker is set where the requirement is built.
POLICY_CHECKERS = {
    "jev.explicitness",
    "jev.content_policy",
    "jev.absence_of",
    "jev.artist_pastiche",
}

SOFT_CHECKERS = {
    "jev.hook_payoff",
}

# The bins whose labels are axis names rather than a value: each selected mood is its own question,
# because "wistful" and "late night" are separate judgements.
AXIS_CHECKERS = ("jev.mood_axis",)

# The caption checkers. Coverage, exclusions, coherence and budget are one requirement each, except
# coverage, which is one per sound dimension so a failure names the dimension that went missing.
CAPTION_COVERAGE = "code.caption.coverage"
CAPTION_EXCLUSIONS = "code.caption.exclusions"
CAPTION_COHERENCE = "code.caption.coherence"
CAPTION_BUDGET = "code.caption.budget"


def load_vocabulary(path: Path | str = VOCAB_PATH) -> dict:
    return json.loads(Path(path).read_text())


# --- reading the draft ---------------------------------------------------------------------

def _selected_ids(selections: Mapping[str, Any]) -> dict[str, list[str]]:
    """Accept both the page's `{bin: {options: [ids]}}` and a flat `{bin: [ids]}`."""
    out: dict[str, list[str]] = {}
    for bin_id, value in (selections or {}).items():
        if isinstance(value, Mapping):
            options = value.get("options") or []
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            options = list(value)
        else:
            options = []
        out[bin_id] = [str(option) for option in options]
    return out


def _label_index(vocab: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """bin id -> option id -> label, so a target carries the text the user actually saw."""
    index: dict[str, dict[str, str]] = {}
    for bin_ in vocab.get("bins", []):
        index[bin_["id"]] = {option["id"]: option["label"] for option in bin_.get("options") or []}
    return index


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text.strip().lower()).strip("_") or "axis"


def _negative_element(label: str) -> str:
    """The thing a negative label names, rather than the label itself.

    An `avoid` option reads "No Synthesizers", and the requirement is that the song does not
    contain *synthesizers*. A question that asked whether the song keeps "No Synthesizers" out
    would be asking the opposite of what was chosen.
    """
    text = str(label).strip()
    return text[3:].strip() if text.lower().startswith("no ") else text


def _consistency_tasks(draft: Mapping[str, Any]) -> list[dict]:
    """The caption/lyric consistency rules the lyric leaves in scope.

    The lyric checker already decides which rules apply and which tags the lyric carries; this asks
    it, rather than re-deriving the rules from the vocabulary a second time. The same dicts drive the
    Lyrics tab's deferred list and the requirements below, so the two cannot disagree.
    """
    text = draft.get("lyrics") or ""
    if not text.strip():
        return []
    from musicmaster import lyrics as lyric_check, timeline

    section_tags = timeline.load(timeline.SECTION_TAGS_PATH)
    found = lyric_check.analyse(text.splitlines(), section_tags, lyric_check.Report())
    return lyric_check.consistency_tasks(found, section_tags, draft.get("selections") or {})


# --- the spec ------------------------------------------------------------------------------

def build_requirements(
    draft: Mapping[str, Any],
    vocab: Mapping[str, Any],
    consistency: Sequence[Mapping[str, Any]] = (),
) -> list[dict]:
    selected = _selected_ids(draft.get("selections") or {})
    labels = _label_index(vocab)
    bins = {bin_["id"]: bin_ for bin_ in vocab.get("bins", [])}

    # Every selected bin grouped by the checker it obliges, so three instrument bins make one
    # requirement rather than three that would ask the same question under different ids.
    grouped: dict[str, dict[str, Any]] = {}
    for bin_id, option_ids in selected.items():
        if not option_ids:
            continue
        bin_ = bins.get(bin_id)
        if bin_ is None:
            continue
        checker = bin_.get("maps_to")
        if not checker:
            continue
        names = [labels.get(bin_id, {}).get(option, option) for option in option_ids]
        entry = grouped.setdefault(checker, {"labels": [], "bins": []})
        entry["labels"].extend(names)
        entry["bins"].append(bin_id)

    requirements: list[dict] = []
    anything_selected = any(option_ids for option_ids in selected.values())

    # --- the caption, in code -----------------------------------------------------------------

    for checker in CAPTION_CHECKERS:
        entry = grouped.get(checker)
        if entry is None:
            continue
        required = list(dict.fromkeys(entry["labels"]))
        dimension = checker.split(".")[-1].replace("_", " ")
        requirements.append(
            _requirement(
                "caption_" + checker.split(".")[-1],
                CAPTION_COVERAGE,
                "mechanical",
                "hard",
                "explicit",
                required,
                stage="plan",
                text=f"the caption names every selected {dimension}: {', '.join(required)}",
            )
        )

    # What must not appear: the negative bins' elements, and any artist the brief excludes, because
    # a name in the tag string is how an artist reference actually reaches the generator.
    forbidden: list[str] = []
    for bin_id, option_ids in selected.items():
        bin_ = bins.get(bin_id)
        if bin_ is None or bin_.get("polarity", "positive") != "negative":
            continue
        forbidden.extend(_negative_element(labels.get(bin_id, {}).get(option, option)) for option in option_ids)
    forbidden.extend(str(name).strip() for name in draft.get("artist_references") or [] if str(name).strip())
    if forbidden:
        requirements.append(
            _requirement(
                "caption_exclusions",
                CAPTION_EXCLUSIONS,
                "policy",
                "policy",
                "explicit",
                list(dict.fromkeys(forbidden)),
                stage="plan",
                text="the caption names nothing the brief excluded: " + ", ".join(dict.fromkeys(forbidden)),
            )
        )

    if anything_selected:
        requirements.append(
            _requirement(
                "caption_coherence",
                CAPTION_COHERENCE,
                "mechanical",
                "hard",
                "explicit",
                None,
                stage="plan",
                text="the selected tags do not contradict each other, exceed a limit, or name an unknown option",
            )
        )
        budget = vocab.get("tag_budget")
        requirements.append(
            _requirement(
                "caption_budget",
                CAPTION_BUDGET,
                "mechanical",
                "soft",
                "explicit",
                budget,
                stage="plan",
                text=f"the tag budget of {budget} drops nothing that was selected",
            )
        )

    # --- the lyrics, judged -------------------------------------------------------------------

    # The theme is an obligation whenever one was written, whether as free text or as a lyric_theme
    # selection, so it is built here rather than inside the loop over selected bins.
    theme_target = (draft.get("theme") or "").strip() or ", ".join(
        dict.fromkeys(grouped.get("jev.theme_adherence", {}).get("labels") or [])
    )
    if theme_target:
        requirements.append(
            _requirement(
                "theme",
                "jev.theme_adherence",
                "semantic",
                "hard",
                "explicit",
                theme_target,
                stage="lyrics",
                text=f"the lyrics are about: {theme_target}",
            )
        )

    for checker in LYRIC_CHECKERS:
        if checker == "jev.theme_adherence":
            continue  # built above
        entry = grouped.get(checker)
        if entry is None:
            continue
        severity = "policy" if checker in POLICY_CHECKERS else ("soft" if checker in SOFT_CHECKERS else "hard")
        kind = "policy" if checker in POLICY_CHECKERS else "semantic"
        requirement_id = _slug(checker.split(".")[-1])

        if checker in AXIS_CHECKERS:
            # Each selected mood is its own question, bounded below: `{"wistful": 3}` asks that the
            # lyric reads at least moderately wistful.
            axes = {label.lower(): 3 for label in dict.fromkeys(entry["labels"])}
            if axes:
                requirements.append(
                    _requirement(
                        requirement_id,
                        checker,
                        kind,
                        severity,
                        "explicit",
                        axes,
                        stage="lyrics",
                        text="the lyrics read as asked on each axis: "
                        + ", ".join(f"{axis} at least {bound}" for axis, bound in axes.items()),
                    )
                )
            continue

        if checker in ("jev.content_policy", "jev.absence_of"):
            # One requirement and one question per excluded thing, because "does the lyric avoid
            # what I excluded" is only answerable one thing at a time; a single question over a
            # list would let one satisfied exclusion hide an unmet one.
            for bin_id in entry["bins"]:
                for option_id in selected.get(bin_id, []):
                    label = labels.get(bin_id, {}).get(option_id, option_id)
                    if checker == "jev.content_policy" and option_id == "no_artist_imitation":
                        # Imitation is a policy with its own checker and its own target; the artist
                        # names reach `caption_exclusions` and `no_imitation` instead.
                        continue
                    element = _negative_element(label)
                    item_id = ("content_" if checker == "jev.content_policy" else "avoid_") + option_id
                    text = (
                        f"the lyrics do not contain {element.lower()}"
                        if checker == "jev.content_policy"
                        else f"the lyrics do not name {element.lower()}"
                    )
                    requirements.append(
                        _requirement(item_id, checker, kind, severity, "explicit", element, stage="lyrics", text=text)
                    )
            continue

        target = ", ".join(dict.fromkeys(entry["labels"]))
        if not target:
            continue
        if checker == "jev.explicitness" and target.strip().lower() == "not applicable":
            # "Not Applicable" is a statement that no limit was set, so there is nothing to ask.
            continue
        requirements.append(
            _requirement(requirement_id, checker, kind, severity, "explicit", target, stage="lyrics")
        )

    # The artist exclusion is a policy requirement that arrives as free text on the brief, and it is
    # also covered by `caption_exclusions`, which stops the name reaching the tags at all.
    excluded = [str(name).strip() for name in draft.get("artist_references") or [] if str(name).strip()]
    if excluded:
        requirements.append(
            _requirement(
                "no_imitation",
                "jev.artist_pastiche",
                "policy",
                "policy",
                "explicit",
                ", ".join(excluded),
                stage="lyrics",
                text="the song does not imitate: " + ", ".join(excluded),
            )
        )

    # --- the caption against the lyric: the rules the checker can pose but not answer -------------
    # One requirement per rule in scope, never one over all of them, because a single answer would
    # let a satisfied rule hide a violated one. A rule whose caption bins are not selected is not an
    # obligation the user chose, so it is not asked.
    for task in consistency:
        requirements.append(
            _requirement(
                "consistency_" + str(task["rule"]),
                "jev.caption_lyric_consistency",
                "semantic",
                "hard",
                "explicit",
                {
                    "rule": task["rule"],
                    "caption_bins": task["caption_bins"],
                    "pool": task["pool"],
                    "rule_text": task["rule_text"],
                },
                stage="lyrics",
                text=f"caption/lyric consistency: {str(task['rule']).replace('_', ' ')}",
            )
        )

    # A value the page holds and a bin that maps to the same checker would otherwise produce the
    # same requirement twice, which would put the same obligation in the report two ways.
    seen: set[str] = set()
    unique: list[dict] = []
    for requirement in requirements:
        if requirement["id"] in seen:
            continue
        seen.add(requirement["id"])
        unique.append(requirement)
    return unique


def _requirement(
    requirement_id: str,
    checker: str,
    kind: str,
    severity: str,
    source: str,
    target: Any,
    *,
    stage: str,
    text: str | None = None,
) -> dict:
    return {
        "id": requirement_id,
        "text": text if text is not None else _requirement_text(requirement_id, target),
        "kind": kind,
        "verify": checker,
        "severity": severity,
        "source": source,
        "target": target,
        "stage_enforced": stage,
    }


def _requirement_text(requirement_id: str, target: Any) -> str:
    if isinstance(target, Mapping):
        rendered = ", ".join(f"{axis} at least {bound}" for axis, bound in target.items())
    elif isinstance(target, Sequence) and not isinstance(target, (str, bytes)):
        rendered = ", ".join(str(item) for item in target)
    else:
        rendered = str(target)
    return f"{requirement_id.replace('_', ' ')}: {rendered}"


# --- the state -----------------------------------------------------------------------------

def build_state(
    draft: Mapping[str, Any],
    vocab: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]] = (),
    consistency: Sequence[Mapping[str, Any]] = (),
) -> dict:
    """The fact sheet the questions read, carrying only what is actually known.

    The requirement targets travel in the state under `targets.<requirement_id>`, because a question
    that says "the vocal the brief asked for in `targets.vocal_spec`" is only answerable if that
    path resolves. A target built by the spec and left out of the state is how a model ends up
    answering a comparison it was never given.

    `planned` is not `measured`. The page knows what tempo it asked for and has not measured the
    audio, and that difference is why the requested values are named for what they are.
    """
    selected = _selected_ids(draft.get("selections") or {})
    labels = _label_index(vocab)

    def names(bin_id: str) -> list[str]:
        return [labels.get(bin_id, {}).get(option, option) for option in selected.get(bin_id, [])]

    def target_of(requirement_id: str) -> Any:
        for requirement in requirements:
            if requirement.get("id") == requirement_id:
                return requirement.get("target")
        return None

    brief: dict[str, Any] = {}
    theme = target_of("theme") or (draft.get("theme") or "").strip()
    if theme:
        brief["theme"] = theme
    language = ", ".join(dict.fromkeys(names("language")))
    if language:
        brief["language"] = language
    excluded = [str(name).strip() for name in draft.get("artist_references") or [] if str(name).strip()]
    if excluded:
        brief["exclude_artist"] = ", ".join(excluded)

    state: dict[str, Any] = {}
    if brief:
        state["brief"] = brief

    caption = draft.get("caption")
    if not caption and selected:
        from musicmaster import render as tag_render

        caption = tag_render.render(vocab, draft.get("selections") or {})["string"]
    if caption:
        state["caption"] = caption
    if draft.get("lyrics"):
        state["lyrics"] = draft["lyrics"]

    targets = {r["id"]: r["target"] for r in requirements if r.get("target") is not None}
    if targets:
        state["targets"] = targets
    # The tags the lyric actually carries, per pool, so a consistency question compares the caption
    # against what the lyric says rather than asking the model to parse the tag grammar itself.
    if consistency:
        state["lyric_tags"] = {str(task["pool"]): list(task["lyric_tags"]) for task in consistency}
        state["lyric_surfaces"] = sorted(
            {str(surface) for task in consistency for surface in task.get("surfaces") or []}
        )
    if requirements:
        state["requirements"] = [{"id": r["id"], "text": r["text"]} for r in requirements]

    planned = {}
    if draft.get("bpm") is not None:
        planned["tempo_bpm"] = draft["bpm"]
    if draft.get("duration_s") is not None:
        planned["duration_s"] = draft["duration_s"]
    if planned:
        state["planned"] = planned
    return state


def interpret(draft: Mapping[str, Any], vocab: Mapping[str, Any] | None = None) -> dict:
    """A spec and the state its questions read, built together so they cannot disagree."""
    vocab = vocab if vocab is not None else load_vocabulary()
    consistency = _consistency_tasks(draft)
    requirements = build_requirements(draft, vocab, consistency)
    return {
        "spec": {
            "spec_version": "1",
            "lane": "audio_first",
            "oracle": "jev",
            "requirements": requirements,
        },
        "state": build_state(draft, vocab, requirements, consistency),
    }
