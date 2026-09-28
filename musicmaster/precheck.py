"""The caption's half of the pre-render check: text facts, decided in code.

The caption is the tag string the prompt will send, and it is rendered from the selections. So the
question "does the caption carry what was chosen" is not a judgement about music -- it is a
containment test over a string this repository produced, and it is exact, free and reproducible.

That matters for a reason beyond cost. A model asked whether a tag list fits a genre is comparing
the brief to itself: the tags *are* the brief, so a fluent answer cannot discover that the renderer
dropped one. Code can, and this module does.

The verdicts it returns are in the report's shape and carry the `measurement` evidence class, so the
report's "decided by measurement" count is honest about what actually decided them.

    from musicmaster import precheck, spec
    built = spec.interpret(draft)
    verdicts = precheck.caption_verdicts(built["spec"], built["state"], vocab, draft["selections"])
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from musicmaster import render

MEASUREMENT = "measurement"


def _tokens(caption: str) -> list[str]:
    """The caption as its tags. The renderer joins labels with ", ", so a tag is exact."""
    return [token.strip() for token in caption.split(",") if token.strip()]


def _verdict(requirement: Mapping[str, Any], verdict: str, note: str, value: Any = None) -> dict:
    item: dict[str, Any] = {
        "requirement_id": requirement["id"],
        "text": requirement.get("text", ""),
        "severity": requirement.get("severity", "hard"),
        "checker": requirement.get("verify", ""),
        "verdict": verdict,
        "probability": None,
        "confidence": None,
        "top2_margin": None,
        "evidence_class": MEASUREMENT,
        "supported_by": [{"class": MEASUREMENT, "source": "code", "value": value}],
        "note": note,
    }
    if value is not None:
        item["measured"] = {"value": value}
    return item


def caption_verdicts(
    spec: Mapping[str, Any],
    state: Mapping[str, Any],
    vocab: Mapping[str, Any],
    selections: Mapping[str, Any] | None = None,
) -> list[dict]:
    """One verdict per caption requirement the spec carries. The oracle is not consulted."""
    requirements = [
        requirement
        for requirement in spec.get("requirements", [])
        if str(requirement.get("verify", "")).startswith("code.caption.")
    ]
    if not requirements:
        return []

    selections = selections or {}
    rendered = render.render(vocab, selections)
    caption = str(state.get("caption") or rendered["string"])
    tags = {tag.lower() for tag in _tokens(caption)}
    verdicts: list[dict] = []

    for requirement in requirements:
        checker = requirement.get("verify", "")
        target = requirement.get("target")

        if checker == "code.caption.coverage":
            required = [str(label) for label in (target or [])]
            missing = [label for label in required if label.lower() not in tags]
            if missing:
                verdicts.append(
                    _verdict(
                        requirement,
                        "unmet",
                        "the caption does not carry: " + ", ".join(missing),
                        missing,
                    )
                )
            else:
                verdicts.append(_verdict(requirement, "met", f"all {len(required)} selected tags are in the caption"))

        elif checker == "code.caption.exclusions":
            # A substring test, not a whole-tag one: an artist's name is a name wherever it appears,
            # and "in the style of Bon Iver" is precisely how a reference would reach the generator.
            forbidden = [str(label) for label in (target or [])]
            lowered = caption.lower()
            present = [label for label in forbidden if label.lower() in lowered]
            if present:
                verdicts.append(
                    _verdict(requirement, "unmet", "the caption names what the brief excluded: " + ", ".join(present), present)
                )
            else:
                verdicts.append(_verdict(requirement, "met", "nothing excluded appears in the caption"))

        elif checker == "code.caption.coherence":
            problems = render.coherence_check(vocab, selections)
            if problems:
                verdicts.append(_verdict(requirement, "unmet", "; ".join(problems), problems))
            else:
                verdicts.append(_verdict(requirement, "met", "the selections do not contradict each other"))

        elif checker == "code.caption.budget":
            omitted = rendered.get("omitted") or []
            if omitted:
                # Soft: the budget dropping a tag is intended behaviour, and it is still worth
                # saying, because a dropped tag is a property the render will not be conditioned on.
                verdicts.append(
                    _verdict(requirement, "unmet", "the tag budget dropped: " + ", ".join(omitted), omitted)
                )
            else:
                verdicts.append(
                    _verdict(requirement, "met", f"the budget of {target} dropped nothing ({len(rendered['tags'])} tags)")
                )

    return verdicts
