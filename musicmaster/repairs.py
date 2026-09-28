"""Turn a verdict into an action: what to change, and where.

A report of probabilities is evidence, not guidance. "noul 0.460 is inside the 0.30-0.70 band" is the
sentence a person needs when the verdict is being traced back to its input, and the wrong sentence
when the question is what to do next. This module produces the second sentence: one concrete change
per requirement that did not pass, in code.

**Code writes the repair, never the model.** The design says it plainly -- the oracle localises the
failure and a generative model performs the repair, routed by code from the failed check. A model
asked to critique its own judgement is exactly the failure the typed interface exists to avoid, and
a repair it wrote would be as unverifiable as the verdict it was explaining. Every string here is a
function of the requirement, the checker and the measured failure, so it can be tested and cannot
drift from what was actually checked.

Two outputs, because the reader and the writer want different sentences:

  * ``suggestion`` is for the person: what is wrong and where to change it.
  * ``repair_instruction`` is for the lyric generator: an imperative it can act on. It is present
    only for the requirements a rewrite can satisfy; a caption problem is code's to fix and carries
    none.

    from musicmaster import repairs
    repairs.advise(requirement, verdict, question=question)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _clean(value: Any) -> str:
    return str(value or "").strip()


def caption_advice(requirement: Mapping[str, Any], verdict: Mapping[str, Any], detail: Mapping[str, Any] | None = None) -> dict:
    """The suggestion for one caption requirement. A rewrite cannot fix a string, so no instruction."""
    detail = detail or {}
    checker = _clean(requirement.get("verify"))
    state = verdict.get("verdict")

    if state == "met":
        return {"suggestion": None, "repair_instruction": None}
    if state == "unverified":
        return {"suggestion": f"Not checked: {_clean(verdict.get('note'))}", "repair_instruction": None}

    if checker == "code.caption.coverage":
        missing = ", ".join(detail.get("missing") or [])
        return {
            "suggestion": (
                f"The caption does not carry {missing}. The caption is rendered from the selections, so the "
                "draft and the caption have drifted apart: regenerate the prompt, or reselect the tag if it "
                "was meant to be dropped."
            ),
            "repair_instruction": None,
        }

    if checker == "code.caption.exclusions":
        present = ", ".join(detail.get("present") or [])
        return {
            "suggestion": f"The caption names {present}, which the brief excludes. Remove it from the free-text tags.",
            "repair_instruction": None,
        }

    if checker == "code.caption.coherence":
        problems = detail.get("problems") or []
        joined = " ".join(problems) if problems else _clean(verdict.get("note"))
        return {
            "suggestion": f"The selections conflict: {joined} Drop one of each pair.",
            "repair_instruction": None,
        }

    if checker == "code.caption.budget":
        omitted = detail.get("omitted") or []
        budget = detail.get("budget")
        return {
            "suggestion": (
                f"{', '.join(omitted)} did not fit the {budget}-tag budget, so the render is not conditioned "
                "on them. Deselect them, or raise the budget if they matter."
            ),
            "repair_instruction": None,
        }

    return {"suggestion": f"This did not hold: {_clean(verdict.get('note'))}", "repair_instruction": None}


def lyric_advice(requirement: Mapping[str, Any], verdict: Mapping[str, Any], question: Mapping[str, Any] | None = None) -> dict:
    """The suggestion for a lyric requirement, and the instruction a rewrite can act on."""
    state = verdict.get("verdict")
    if state == "met":
        return {"suggestion": None, "repair_instruction": None}
    if state == "unverified":
        return {
            "suggestion": f"Not checked, so this is neither a pass nor a fail: {_clean(verdict.get('note'))}",
            "repair_instruction": None,
        }

    checker = _clean(requirement.get("verify"))
    target = _clean(requirement.get("target"))
    instructions = (question or {}).get("instructions")
    axis = _clean(instructions.get("axis")) if isinstance(instructions, Mapping) else ""
    upper = (question or {}).get("bound") == "max"
    lead = "The check is not certain, but " if state == "uncertain" else ""

    if checker == "jev.theme_adherence":
        return {
            "suggestion": (
                f"{lead}the lyrics do not clearly read as “{target}”. Put one concrete thing from it — an "
                "object, a place or a moment — into the chorus, rather than a mood word."
            ),
            "repair_instruction": (
                f"The lyric does not clearly address the theme “{target}”. Add a concrete, specific image of "
                "it to the chorus."
            ),
        }

    if checker == "jev.mood_axis":
        if upper:
            return {
                "suggestion": f"{lead}“{axis}” reads stronger than the brief allows. Remove the details that carry it.",
                "repair_instruction": f"The lyric reads too much as “{axis}”. Remove the images and word choices that carry it.",
            }
        return {
            "suggestion": f"{lead}“{axis}” reads weaker than asked. Give it more than one supporting detail in the same section.",
            "repair_instruction": f"The lyric does not read as “{axis}”. Add details that carry it, and cut what pulls the other way.",
        }

    if checker == "jev.hook_payoff":
        return {
            "suggestion": (
                f"{lead}the hook is not landing as “{target}”. Make one short line in the hook section "
                "repeatable and memorable — the line a listener would carry away."
            ),
            "repair_instruction": (
                f"The hook does not land as “{target}”. Rewrite the hook line so it is short, repeatable and "
                "the one the listener remembers."
            ),
        }

    if checker == "jev.explicitness":
        return {
            "suggestion": (
                f"{lead}the language sits at the edge of “{target}”. Replace the explicit phrase or the double "
                "meaning with a concrete image."
            ),
            "repair_instruction": f"The lyric is at the edge of the “{target}” limit. Replace the explicit or double-meaning phrase.",
        }

    if checker == "jev.content_policy":
        return {
            "suggestion": f"{lead}the lyrics contain {target}, which the brief excludes. Replace the line that carries it.",
            "repair_instruction": f"The lyric contains {target}, which the brief excludes. Replace the line that carries it.",
        }

    if checker == "jev.absence_of":
        return {
            "suggestion": f"{lead}the lyrics name {target}, which the brief avoids. Name a different instrument or sound instead.",
            "repair_instruction": f"The lyric names {target}, which the brief excludes. Replace it with another instrument or sound.",
        }

    if checker == "jev.artist_pastiche":
        return {
            "suggestion": (
                f"{lead}it reads as an imitation of {target}. Remove the traits that identify them: sharing a "
                "genre is fine, copying two signature traits is not."
            ),
            "repair_instruction": f"The lyric imitates {target}. Remove the identifying traits while keeping the genre.",
        }

    return {
        "suggestion": f"{lead}“{_clean(requirement.get('text'))}” did not hold. Revise the lyrics to satisfy it.",
        "repair_instruction": f"Revise the lyric so it satisfies: {_clean(requirement.get('text'))}.",
    }


def advise(
    requirement: Mapping[str, Any],
    verdict: Mapping[str, Any],
    *,
    question: Mapping[str, Any] | None = None,
    detail: Mapping[str, Any] | None = None,
) -> dict:
    """The suggestion and the repair instruction for one verdict.

    A met verdict carries neither: there is nothing to change, and an empty suggestion is better than
    a reassuring one.
    """
    checker = _clean(requirement.get("verify"))
    if checker.startswith("code.caption."):
        return caption_advice(requirement, verdict, detail)
    return lyric_advice(requirement, verdict, question)


def summary(verdicts: Sequence[Mapping[str, Any]], oracle: Mapping[str, Any] | None = None) -> str:
    """One paragraph a person reads first: what stands, what does not, and what to do about it.

    Counts are a table; this is the sentence. It leads with what is already right, because a check
    that only ever says what is wrong teaches the user to ignore it.
    """
    oracle = oracle or {}
    if not verdicts:
        return "Nothing was selected, so there is nothing to check yet."

    hard = [v for v in verdicts if v.get("severity") in ("hard", "policy")]
    unmet = [v for v in hard if v.get("verdict") == "unmet"]
    uncertain = [v for v in hard if v.get("verdict") == "uncertain"]
    unverified = [v for v in hard if v.get("verdict") == "unverified"]
    soft = [v for v in verdicts if v.get("verdict") != "met" and v.get("severity") == "soft"]
    met = [v for v in verdicts if v.get("verdict") == "met"]

    def names(items: Sequence[Mapping[str, Any]]) -> str:
        listed = ", ".join(str(v.get("text") or v.get("requirement_id")) for v in items[:4])
        return listed + ("…" if len(items) > 4 else "")

    if not unmet and not uncertain and not unverified:
        if soft:
            return f"Everything the brief insists on holds. {len(soft)} preference(s) fell a little short: {names(soft)}."
        return (
            f"All {len(verdicts)} requirements hold: the caption carries every selected tag, and the "
            "lyrics stand up. Ready to render."
        )

    parts = []
    if unmet:
        parts.append(f"{len(unmet)} requirement(s) failed: {names(unmet)}")
    if uncertain:
        parts.append(f"{len(uncertain)} could not be decided either way: {names(uncertain)}")
    if unverified:
        reason = _clean(oracle.get("degraded_reason")) or "the oracle did not answer"
        parts.append(f"{len(unverified)} could not be checked ({reason})")
    lead = f"{len(met)} of {len(verdicts)} requirements already hold. " if met else ""
    return lead + "Before rendering: " + "; ".join(parts) + "."
