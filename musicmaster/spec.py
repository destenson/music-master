"""Derive a RequirementSpec, and the state its questions read, from what the page holds.

The design's Interpret stage turns a brief into typed requirements, and it is the one stage
that was never built: the page has selections, a caption, a lyric, a tempo and a duration, but
nothing that says which of them are *requirements* a battery could check. Without that, a
compliance oracle has nothing to ask about, which is why "no compliance report" and "no oracle
is configured" were the same sentence.

This is that stage in its deterministic form, and deliberately no more than that. Almost all of
it is already data: every bin in the vocabulary declares `maps_to`, the checker its selection
becomes an obligation for, so the spec is the selected bins grouped by that field rather than a
second hand-kept table that could disagree with the vocabulary.

Two things it will not do:

  * It invents no requirement the user did not choose. A bin with nothing selected contributes
    nothing, and the theme is a requirement only when a theme was written.
  * It reports no measurement it did not take. The requested tempo and duration go into a
    `planned` block, not `measured`, so a question that reads `measured` finds nothing and says
    so rather than reading an intention as a fact.

    python3 -c "from musicmaster import spec; print(spec.interpret({'bpm': 92}))"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"

# How each checker is treated once a selection becomes an obligation. Severity is about what a
# failure means, not how sure we are: a policy requirement is one whose breach rejects the song,
# and a soft one is a preference whose miss is worth reporting and not worth failing.
POLICY_CHECKERS = {
    "jev.explicitness",
    "jev.content_policy",
    "jev.absence_of",
    "jev.artist_pastiche",
}

# Textural choices describe a preference rather than a promise, so they are soft.
SOFT_CHECKERS = {
    "jev.timbre",
    "jev.era_production",
    "jev.groove_fidelity",
    "jev.energy",
    "jev.hook_payoff",
    "jev.tuning_fidelity",
}

# Which checkers take a target built from option labels. A checker missing from this tuple is
# silently unaskable, so it is worth checking against the bank when a bin is added.
LABEL_CHECKERS = (
    "jev.genre_fidelity",
    "jev.era_production",
    "jev.instrumentation",
    "jev.vocal_spec",
    "jev.timbre",
    "jev.groove_fidelity",
    "jev.energy",
    "jev.explicitness",
    "jev.hook_payoff",
    "jev.content_policy",
    "jev.absence_of",
    "jev.tuning_fidelity",
)

# The bins whose labels are axis names rather than a value: each selected mood is its own
# question, because "wistful" and "late night" are separate judgements.
AXIS_CHECKERS = ("jev.mood_axis",)

MECHANICAL_TARGETS = {
    "code.audio.tempo": "bpm",
    "code.audio.key": "key",
    "code.audio.meter": "time_signature",
    "code.audio.sections": "template_id",
    "code.audio.language": "language",
}


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


# --- the spec ------------------------------------------------------------------------------

def build_requirements(draft: Mapping[str, Any], vocab: Mapping[str, Any]) -> list[dict]:
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

    # The mechanical ones, from the values the page holds rather than from a bin.
    if draft.get("bpm") is not None:
        requirements.append(_requirement("tempo", "code.audio.tempo", "mechanical", "hard", "explicit", draft["bpm"]))
    if draft.get("duration_s") is not None:
        requirements.append(
            _requirement("duration", "code.audio.duration", "mechanical", "hard", "explicit", draft["duration_s"])
        )
    for checker, field in MECHANICAL_TARGETS.items():
        entry = grouped.get(checker)
        if entry is None:
            continue
        value = draft.get(field)
        if value in (None, "", []):
            # A key, meter or language bin is a target in its own right even without a draft
            # field: the selection *is* the value.
            value = ", ".join(dict.fromkeys(entry["labels"]))
        if value in (None, "", []):
            continue
        requirements.append(
            _requirement(_slug(checker.split(".")[-1]), checker, "mechanical", "hard", "explicit", value)
        )

    # The theme is an obligation whenever one was written, whether or not a `lyric_theme` bin was
    # also touched, so it is built here rather than inside the loop over selected bins.
    theme_text = (draft.get("theme") or "").strip()
    theme_labels = grouped.get("jev.theme_adherence", {}).get("labels") or []
    theme_target = theme_text or ", ".join(dict.fromkeys(theme_labels))
    if theme_target:
        requirements.append(
            _requirement("theme", "jev.theme_adherence", "semantic", "hard", "explicit", theme_target)
        )

    # The semantic ones, one requirement per checker.
    for checker, entry in grouped.items():
        if not checker.startswith("jev."):
            continue
        requirement_id = _slug(checker.split(".")[-1])
        severity = "policy" if checker in POLICY_CHECKERS else ("soft" if checker in SOFT_CHECKERS else "hard")
        kind = "policy" if checker in POLICY_CHECKERS else "semantic"

        if checker == "jev.theme_adherence":
            continue  # built above, and the dedupe below keeps that one

        if checker in AXIS_CHECKERS:
            # Each selected mood is its own question, bounded below: `{"wistful": 3}` asks that
            # the song reads at least moderately wistful.
            axes = {label.lower(): 3 for label in dict.fromkeys(entry["labels"])}
            if not axes:
                continue
            requirements.append(_requirement(requirement_id, checker, kind, severity, "explicit", axes))
            continue

        if checker not in LABEL_CHECKERS:
            continue
        target = _target_for(checker, entry["labels"], draft)
        if target in (None, "", []):
            continue
        requirements.append(_requirement(requirement_id, checker, kind, severity, "explicit", target))

    # The artist exclusion is a policy requirement with no bin of its own: it arrives as free
    # text on the brief.
    excluded = [str(name).strip() for name in draft.get("artist_references") or [] if str(name).strip()]
    if excluded:
        requirements.append(
            _requirement("no_imitation", "jev.artist_pastiche", "policy", "policy", "explicit", ", ".join(excluded))
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


def _target_for(checker: str, labels: Sequence[str], draft: Mapping[str, Any]) -> Any:
    # A comma-joined string rather than a list: several question templates quote the target inside
    # the question text, and a JSON array reads as noise there while saying no more.
    return ", ".join(dict.fromkeys(labels))


def _requirement(
    requirement_id: str,
    checker: str,
    kind: str,
    severity: str,
    source: str,
    target: Any,
) -> dict:
    return {
        "id": requirement_id,
        "text": _requirement_text(requirement_id, target),
        "kind": kind,
        "verify": checker,
        "severity": severity,
        "source": source,
        "target": target,
    }


def _requirement_text(requirement_id: str, target: Any) -> str:
    if isinstance(target, Mapping):
        rendered = ", ".join(f"{axis} at least {bound}" for axis, bound in target.items())
    elif isinstance(target, list):
        rendered = ", ".join(str(item) for item in target)
    else:
        rendered = str(target)
    return f"{requirement_id.replace('_', ' ')}: {rendered}"


# --- the state -----------------------------------------------------------------------------

def build_state(draft: Mapping[str, Any], vocab: Mapping[str, Any]) -> dict:
    """The fact sheet the questions read, carrying only what is actually known.

    `planned` is not `measured`. The page knows what tempo it asked for and has not measured the
    audio, and the difference is the whole reason the report distinguishes a measurement from a
    description, so the requested values are named for what they are.
    """
    selected = _selected_ids(draft.get("selections") or {})
    labels = _label_index(vocab)
    bins = {bin_["id"]: bin_ for bin_ in vocab.get("bins", [])}

    def names(bin_id: str) -> list[str]:
        return [labels.get(bin_id, {}).get(option, option) for option in selected.get(bin_id, [])]

    brief: dict[str, Any] = {}
    theme = (draft.get("theme") or "").strip()
    if theme:
        brief["theme"] = theme
    genre = ", ".join(dict.fromkeys(names("genre") + names("fusion") + names("regional_feel")))
    if genre:
        brief["genre"] = genre
    era = ", ".join(dict.fromkeys(names("era")))
    if era:
        brief["era"] = era
    artist = [str(name).strip() for name in draft.get("artist_references") or [] if str(name).strip()]
    if artist:
        brief["exclude_artist"] = ", ".join(artist)
    language = ", ".join(dict.fromkeys(names("language")))
    if language:
        brief["language"] = language
    tuning = ", ".join(dict.fromkeys(names("tuning")))
    if tuning:
        brief["tuning"] = tuning

    # `avoid` is the one bin whose labels are things that must *not* appear, and it is the only
    # place the vocabulary records a polarity, so the brief states it in the negative.
    avoid = names("avoid")
    if avoid:
        brief["avoid"] = ", ".join(dict.fromkeys(avoid))

    planned = {}
    if draft.get("bpm") is not None:
        planned["tempo_bpm"] = draft["bpm"]
    if draft.get("duration_s") is not None:
        planned["duration_s"] = draft["duration_s"]

    state: dict[str, Any] = {"brief": brief}
    if draft.get("caption"):
        state["caption"] = draft["caption"]
    if draft.get("chords"):
        state["chords"] = draft["chords"]
    if draft.get("lyrics"):
        state["lyrics"] = draft["lyrics"]
    if planned:
        state["planned"] = planned
    return state


def interpret(draft: Mapping[str, Any], vocab: Mapping[str, Any] | None = None) -> dict:
    """A spec and the state its questions read, built together so they cannot disagree."""
    vocab = vocab if vocab is not None else load_vocabulary()
    return {
        "spec": {
            "spec_version": "1",
            "lane": "audio_first",
            "oracle": "jev",
            "requirements": build_requirements(draft, vocab),
        },
        "state": build_state(draft, vocab),
    }
