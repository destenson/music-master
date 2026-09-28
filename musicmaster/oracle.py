"""The compliance oracle seam: typed questions in, verdicts out, with the evidence named.

This is the text tier's half of the compliance battery. It owns everything that is pure --
what to ask, how to read an answer, when a probability is too weak to decide, and what the
report says -- and owns none of the transport. An oracle is anything with a ``kind``, a
``model``, a ``reachable`` flag and an ``evaluate(state, questions) -> {question_id: answer}``;
a recorded replay fixture is one implementation, a hosted Jev endpoint is another, and a local
logit readout is a third. Nothing here performs I/O, so the same code runs under the CLI and
under Pyodide.

The rules this module exists to enforce, from ``docs/design/compliance-architecture.md`` §8 and
``docs/design/evidence-classes.md`` §3-4:

  * A probability inside the uncertainty band is ``uncertain``, which is never a pass.
  * An evidence class that may not decide a severity alone caps its verdict at ``uncertain`` --
    description never decides a hard requirement, a self-report never does, and an oracle
    judgement decides one only with a top-two margin above the gate.
  * An oracle that is absent, unreachable or missing an answer leaves its requirements
    ``unverified``, which is a distinct outcome from ``met``. The pipeline never fails because
    the oracle was unavailable; it reports what it could not check.

``verify`` names the checker, not the provider: a requirement checked as ``jev.theme_adherence``
is decided by whatever oracle is configured, and the report records which one so a verdict can
be re-derived.

The question text is data, in ``vocabulary/oracle-questions.json``, keyed by checker. Adding a
semantic requirement is a bank entry plus a spec entry, not a code change.

    python3 vocabulary/check_compliance.py vocabulary/examples/compliance-indie-folk.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
QUESTION_BANK_PATH = ROOT / "vocabulary" / "oracle-questions.json"

# --- the vocabulary of the report ---------------------------------------------------------

KINDS = ("jev", "local", "replay", "none")
VERDICTS = ("met", "unmet", "uncertain", "unverified")
SEVERITIES = ("hard", "soft", "policy")
ENFORCEMENT_MODES = ("enforced", "verified", "conditioned + verified", "measured", "unverified")

MEASUREMENT = "measurement"
DESCRIPTION = "description"
SELF_REPORT = "self_report"
ORACLE = "oracle"
TRANSCRIPTION = "transcription"
EVIDENCE_CLASSES = (MEASUREMENT, DESCRIPTION, SELF_REPORT, ORACLE, TRANSCRIPTION)

# --- thresholds ---------------------------------------------------------------------------

# Re-measure these per question and per model version; they do not port between primitives,
# questions or versions. A question in the bank may override any of them, and every verdict
# records the threshold that actually decided it.
DEFAULT_THRESHOLDS = {
    "accept": 0.70,      # a noul at or above this is met
    "reject": 0.30,      # a noul at or below this is unmet
    "choice_top": 0.60,  # a choice whose top option is below this is uncertain
    "margin": 0.50,      # the top-two margin an oracle needs to decide a hard requirement
}


def thresholds_for(checker: str, bank: Mapping[str, Any] | None) -> dict:
    """The thresholds that govern a checker: the defaults, overridden by its bank entry."""
    merged = dict(DEFAULT_THRESHOLDS)
    if bank:
        entry = (bank.get("questions") or {}).get(checker) or {}
        merged.update(entry.get("thresholds") or {})
    return merged


# --- questions ----------------------------------------------------------------------------

def load_bank(path: Path | str = QUESTION_BANK_PATH) -> dict:
    return json.loads(Path(path).read_text())


def _render(template: str, params: Mapping[str, Any]) -> str:
    out = template
    for key, value in params.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _compact(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _target_params(entry: Mapping[str, Any], target: Any) -> list[dict]:
    """Split a requirement target into one parameter set per question.

    Most targets produce exactly one question. A checker whose bank entry declares
    ``target_split: axes`` is the exception: its target is a mapping of axes, and each axis is
    its own question because they are separate judgements with separate thresholds. An axis key
    ending in ``_max`` is an upper bound -- ``sadness_max: 1`` asks that the song not read as
    sad, which is not the same question as ``wistful: 3`` asking that it does read as wistful.
    """
    if entry.get("target_split") == "axes" and isinstance(target, Mapping):
        params = []
        for key, value in target.items():
            if key.endswith("_max"):
                params.append({"axis": key[:-4], "bound": "max", "bound_value": value})
            else:
                params.append({"axis": key, "bound": "min", "bound_value": value})
        return params
    params = {"target": _compact(target)}
    if entry.get("default_bound") is not None:
        params["bound"] = entry.get("default_bound_type", "min")
        params["bound_value"] = entry["default_bound"]
    return [params]


def _question_from(entry: Mapping[str, Any], requirement: Mapping[str, Any], question_id: str, params: Mapping[str, Any]) -> dict:
    question: dict[str, Any] = {
        "id": question_id,
        "requirement_id": requirement.get("id"),
        "checker": requirement.get("verify", ""),
        "type": entry["type"],
        "instructions": _render(entry["instructions"], params),
        "reads": list(entry.get("reads", [])),
        "severity": requirement.get("severity", "soft"),
    }
    if entry["type"] == "noul":
        question["criteria"] = {key: _render(value, params) for key, value in (entry.get("criteria") or {}).items()}
        # `polarity` says which way the noul points at the requirement. A `goal` question asks
        # whether the requirement is satisfied; a `violation` question asks whether it was
        # broken, which is how the battery phrases imitation and content policy. A high noul
        # then means the requirement fails, and reading it the other way would invert the
        # verdict while still looking well-formed.
        question["polarity"] = entry.get("polarity", "goal")
    elif entry["type"] == "score":
        question["levels"] = [_render(level, params) for level in entry["levels"]]
        question["bound"] = params.get("bound")
        question["bound_value"] = params.get("bound_value")
    elif entry["type"] == "choice":
        question["options"] = list(entry.get("options") or [])
        question["companion_noul"] = entry.get("companion_noul")
    else:
        raise ValueError(f"unknown question type in the bank: {entry['type']!r}")
    return question


def build_questions(spec: Mapping[str, Any], bank: Mapping[str, Any] | None = None) -> dict:
    """Turn a spec's oracle-decidable requirements into the battery's question set.

    Only requirements an oracle can answer are built: a ``code.*`` or ``audio.*`` checker is
    decided elsewhere, and a ``human.*`` one cannot be decided automatically at all.
    """
    bank = bank if bank is not None else load_bank()
    entries = bank.get("questions") or {}
    questions: dict[str, dict] = {}

    for requirement in spec.get("requirements", []):
        checker = requirement.get("verify", "")
        if not checker.startswith("jev."):
            continue
        entry = entries.get(checker)
        if entry is None:
            continue
        params_list = _target_params(entry, requirement.get("target"))
        split = entry.get("target_split") == "axes"
        for index, params in enumerate(params_list):
            # An axis question is always qualified by its axis, so adding a second axis to a
            # target does not rename the first one and invalidate its recorded answers.
            question_id = f"{requirement['id']}.{params.get('axis', index)}" if split else requirement["id"]
            questions[question_id] = _question_from(entry, requirement, question_id, params)

    # The cross-check is asked with every battery: a summary violation question that never
    # substitutes for the individual answers, because structural invariants between questions
    # do not hold.
    for checker in bank.get("always_ask") or ():
        entry = entries.get(checker)
        if entry is None:
            continue
        question = _question_from(entry, {"id": None, "verify": checker, "severity": "policy"}, checker, {})
        question["cross_check"] = True
        questions[checker] = question

    return questions


# --- reading an answer --------------------------------------------------------------------

def _distribution_top(distribution: Sequence[float]) -> tuple[int, float, float]:
    """(index of the top option, its probability, its margin over the runner-up)."""
    values = [float(x) for x in distribution]
    ranked = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    if not ranked:
        return 0, 0.0, 0.0
    top = ranked[0]
    second = values[ranked[1]] if len(ranked) > 1 else 0.0
    return top, values[top], values[top] - second


def read_noul(answer: Mapping[str, Any], thresholds: Mapping[str, float], polarity: str = "goal") -> dict:
    """A noul against the band. The band is checked first, so a probability inside it is never
    read as a pass however the accept threshold is set.

    The top-two margin of a two-way question is ``|2p - 1|``: it is the same quantity as the
    margin over the runner-up in a longer list, since the runner-up is ``1 - p``.

    ``polarity`` is which way the answer points at the requirement. A ``violation`` question is
    asked about the failure -- "does it read as an imitation" -- so a high noul means the
    requirement is *not* met. The probability is reported exactly as the oracle gave it, and
    only the verdict is turned round.
    """
    value = answer.get("noul")
    if not isinstance(value, (int, float)):
        return {"verdict": "unverified", "note": "the answer carried no noul"}
    value = float(value)
    margin = abs(2 * value - 1)
    # The band is inclusive and is checked first. The design states it as `[0.30, 0.70]`, and
    # uncertainty must never become a silent pass, so the accept threshold decides only above
    # the band's upper edge.
    if thresholds["reject"] <= value <= thresholds["accept"]:
        return {
            "verdict": "uncertain",
            "probability": value,
            "margin": margin,
            "note": f"noul {value:.3f} is inside the {thresholds['reject']:.2f}-{thresholds['accept']:.2f} band",
        }
    if value >= thresholds["accept"]:
        verdict = "met" if polarity == "goal" else "unmet"
        note = f"noul {value:.3f} at or above the {thresholds['accept']:.2f} accept threshold"
        if polarity != "goal":
            note += " on a violation question, so the requirement is not met"
        return {"verdict": verdict, "probability": value, "margin": margin, "threshold": float(thresholds["accept"]), "note": note}
    verdict = "unmet" if polarity == "goal" else "met"
    note = f"noul {value:.3f} at or below the {thresholds['reject']:.2f} reject threshold"
    if polarity != "goal":
        note += "; the violation was not confirmed"
    return {"verdict": verdict, "probability": value, "margin": margin, "threshold": float(thresholds["reject"]), "note": note}


def read_score(question: Mapping[str, Any], answer: Mapping[str, Any], thresholds: Mapping[str, float]) -> dict:
    """A score against its bound. ``bound`` of ``max`` is an upper bound, anything else a lower
    bound, which is the distinction a mood target needs. Without a bound there is nothing to
    decide against, and saying so is more useful than inventing one."""
    distribution = answer.get("distribution")
    if not isinstance(distribution, Sequence) or isinstance(distribution, (str, bytes)) or not distribution:
        return {"verdict": "unverified", "note": "the answer carried no score distribution"}
    index, top, margin = _distribution_top(distribution)
    level = index + 1
    bound, bound_value = question.get("bound"), question.get("bound_value")
    value = {"level": level, "top_probability": round(top, 6), "bound": bound_value}
    if bound_value is None:
        return {
            "verdict": "unverified",
            "probability": top,
            "margin": margin,
            "value": value,
            "note": f"level {level} scored, but the requirement names no bound to decide against",
        }
    if bound == "max":
        proposed = "met" if level <= bound_value else "unmet"
        note = f"level {level} against an upper bound of {bound_value}"
    else:
        proposed = "met" if level >= bound_value else "unmet"
        note = f"level {level} against a lower bound of {bound_value}"
    return {
        "verdict": proposed,
        "probability": top,
        "margin": margin,
        "threshold": float(bound_value),
        "value": value,
        "note": note,
    }


def read_choice(question: Mapping[str, Any], answer: Mapping[str, Any], thresholds: Mapping[str, float]) -> dict:
    """A choice, which is relative and may never be consumed without its companion noul.

    A choice always names a winner, so on its own it can say nothing about whether any option
    was acceptable. Without a companion noul the honest reading is a refusal, not a verdict.
    """
    companion = answer.get("noul")
    if companion is None:
        return {"verdict": "unverified", "note": "a choice was answered without its companion noul"}
    distribution = answer.get("distribution")
    if not isinstance(distribution, Sequence) or isinstance(distribution, (str, bytes)) or not distribution:
        return {"verdict": "unverified", "note": "the answer carried no choice distribution"}
    index, top, margin = _distribution_top(distribution)
    companion = float(companion)
    value = {"option_index": index, "top_probability": round(top, 6)}
    if companion < thresholds["accept"]:
        return {
            "verdict": "unmet",
            "probability": companion,
            "margin": margin,
            "threshold": float(thresholds["accept"]),
            "value": value,
            "note": f"no option was acceptable: companion noul {companion:.3f}",
        }
    if top < thresholds["choice_top"]:
        return {
            "verdict": "uncertain",
            "probability": companion,
            "margin": margin,
            "threshold": float(thresholds["choice_top"]),
            "value": value,
            "note": f"top option at {top:.3f}, below the {thresholds['choice_top']:.2f} choice gate",
        }
    return {
        "verdict": "met",
        "probability": companion,
        "margin": margin,
        "threshold": float(thresholds["choice_top"]),
        "value": value,
        "note": f"option {index} chosen at {top:.3f} with companion noul {companion:.3f}",
    }


# --- the evidence gate --------------------------------------------------------------------

def apply_evidence_gate(
    severity: str,
    proposed: str,
    classes: set[str],
    margin: float,
    thresholds: Mapping[str, float],
    gauge_passed: bool = False,
) -> tuple[str, str]:
    """Cap a proposed verdict by what its evidence is allowed to decide.

    This is where the project stops a fluent model from manufacturing a green tick. A verdict
    that looks decided is downgraded to ``uncertain`` when the class that produced it may not
    decide that severity alone; the note says which rule did it, so the report shows what was
    proposed and why it was not accepted.
    """
    if proposed != "met":
        return proposed, ""
    if severity == "soft":
        return proposed, ""
    if MEASUREMENT in classes:
        return proposed, ""
    if severity == "policy":
        # An oracle decides a policy requirement on its action and review bands, which were
        # already applied when the answer was read; the margin gate is a hard-requirement rule.
        if ORACLE in classes:
            return proposed, ""
        return "uncertain", "description and self-report cannot decide a policy requirement alone"
    if ORACLE in classes:
        if margin >= thresholds["margin"]:
            return proposed, ""
        return "uncertain", (
            f"oracle alone with a top-two margin of {margin:.3f}, below the {thresholds['margin']:.2f} gate"
        )
    if DESCRIPTION in classes:
        if gauge_passed:
            return proposed, ""
        return "uncertain", "description alone on a hard requirement; it corroborates but does not decide"
    if SELF_REPORT in classes:
        return "uncertain", "self-report cannot decide a hard requirement"
    return "uncertain", f"no evidence class present that may decide a {severity} requirement"


# --- verdicts and the report --------------------------------------------------------------

def verdict_for(
    requirement: Mapping[str, Any],
    question: Mapping[str, Any],
    answer: Mapping[str, Any],
    oracle: Mapping[str, Any],
    thresholds: Mapping[str, float],
    gauge_passed: bool = False,
) -> dict:
    """One requirement's verdict, with its evidence and the threshold that decided it."""
    question_type = question["type"]
    if question_type == "noul":
        read = read_noul(answer, thresholds, question.get("polarity", "goal"))
    elif question_type == "score":
        read = read_score(question, answer, thresholds)
    else:
        read = read_choice(question, answer, thresholds)

    probability = read.get("probability")
    margin = read.get("margin")
    threshold = read.get("threshold")
    classes = {ORACLE}
    if read["verdict"] == "met":
        gated, reason = apply_evidence_gate(
            requirement.get("severity", "soft"),
            read["verdict"],
            classes,
            margin if margin is not None else float("nan"),
            thresholds,
            gauge_passed,
        )
    else:
        gated, reason = read["verdict"], ""

    source = f"{oracle['kind']}@{oracle['model']}" if oracle.get("model") else str(oracle["kind"])
    item: dict[str, Any] = {"class": ORACLE, "source": source}
    if read.get("value") is not None:
        item["value"] = read["value"]
    elif probability is not None:
        item["value"] = round(float(probability), 6)
    if threshold is not None:
        item["threshold"] = threshold

    verdict: dict[str, Any] = {
        "requirement_id": requirement["id"],
        "text": requirement.get("text", ""),
        "severity": requirement.get("severity", "soft"),
        "checker": requirement.get("verify", ""),
        "verdict": gated,
        "probability": None if probability is None else round(float(probability), 6),
        "confidence": None,
        "top2_margin": None if margin is None else round(float(margin), 6),
        "evidence_class": ORACLE,
        "supported_by": [item],
        "note": reason or read.get("note", ""),
    }
    if requirement.get("enforcement"):
        verdict["enforcement"] = requirement["enforcement"]
    return verdict


def unverified_verdict(requirement: Mapping[str, Any], reason: str) -> dict:
    """A requirement nothing could decide. Never a pass, and never a failure either."""
    return {
        "requirement_id": requirement["id"],
        "text": requirement.get("text", ""),
        "severity": requirement.get("severity", "soft"),
        "checker": requirement.get("verify", ""),
        "verdict": "unverified",
        "probability": None,
        "confidence": None,
        "top2_margin": None,
        "evidence_class": None,
        "supported_by": [],
        "note": reason,
    }


def normalise_mechanical(verdict: Mapping[str, Any]) -> dict:
    """A caller-supplied code or audio verdict, filled out to the report's shape.

    These are decided outside this module -- by the lyric checker, the timeline, or a
    measurement pass -- and arrive already computed. They default to the ``measurement`` class,
    because that is what a code or audio checker is.
    """
    out: dict[str, Any] = {
        "requirement_id": verdict["requirement_id"],
        "text": verdict.get("text", ""),
        "severity": verdict.get("severity", "hard"),
        "checker": verdict.get("checker", ""),
        "verdict": verdict["verdict"],
        "probability": verdict.get("probability"),
        "confidence": verdict.get("confidence"),
        "top2_margin": verdict.get("top2_margin"),
        "evidence_class": verdict.get("evidence_class", MEASUREMENT),
        "supported_by": list(verdict.get("supported_by") or []),
        "note": verdict.get("note", ""),
    }
    if verdict.get("measured") is not None:
        out["measured"] = verdict["measured"]
    if verdict.get("evidence"):
        out["evidence"] = list(verdict["evidence"])
    if verdict.get("enforcement"):
        out["enforcement"] = verdict["enforcement"]
    return out


def overall_verdict(verdicts: Sequence[Mapping[str, Any]]) -> str:
    """The report's headline, in precedence order: a known failure outranks an unknown.

    ``compliant`` requires every hard and policy requirement met and nothing uncertain, so one
    unmet or uncertain hard requirement stops it. A requirement that was merely not checked
    leaves the whole report ``unverified`` rather than blaming the song for our inability to
    check it.
    """
    if not verdicts:
        return "unverified"
    decisive = [v for v in verdicts if v.get("severity") in ("hard", "policy")]
    if any(v["verdict"] == "unmet" for v in decisive):
        return "non_compliant"
    if any(v["verdict"] == "uncertain" for v in decisive):
        return "non_compliant"
    if any(v["verdict"] == "unverified" for v in decisive):
        return "unverified"
    if any(v["verdict"] != "met" for v in verdicts):
        return "compliant_with_unmet_soft"
    return "compliant"


def counts(verdicts: Sequence[Mapping[str, Any]]) -> dict:
    """The two headline counts. 'Twelve met, six of them on description' is a different
    document from 'twelve met', and only one of them is honest."""
    met = [v for v in verdicts if v["verdict"] == "met"]
    return {
        "met": len(met),
        "total": len(verdicts),
        "decided_by_measurement": sum(1 for v in met if v.get("evidence_class") == MEASUREMENT),
        "decided_by_description": sum(1 for v in met if v.get("evidence_class") == DESCRIPTION),
        "uncertain": sum(1 for v in verdicts if v["verdict"] == "uncertain"),
        "unverified": sum(1 for v in verdicts if v["verdict"] == "unverified"),
    }


def unmet_list(verdicts: Sequence[Mapping[str, Any]]) -> list[str]:
    """What the system could not satisfy or could not check, stated in the report."""
    out = []
    for verdict in verdicts:
        if verdict["verdict"] != "met":
            label = verdict.get("text") or verdict["requirement_id"]
            out.append(f"{verdict['requirement_id']} ({verdict.get('severity', '?')}, {verdict['verdict']}): {label}")
    return out


# --- oracles ------------------------------------------------------------------------------

class NoOracle:
    """The ``none`` mode: deterministic gates only, every semantic requirement unverified."""

    kind = "none"
    model = None
    reachable = False
    degraded_reason = "no oracle is configured"

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> dict:
        return {}


class ReplayOracle:
    """Recorded answers, keyed by question id.

    This makes the whole battery testable with no network, no key and no GPU, and it makes a
    threshold change reproducible: the same answers re-gated must produce the same verdicts. A
    question the fixture does not answer comes back missing, which the caller reports as
    ``unverified`` rather than filling in a default.
    """

    kind = "replay"

    def __init__(self, answers: Mapping[str, Any], model: str | None = None, reachable: bool = True):
        self.answers = dict(answers)
        self.model = model
        self.reachable = reachable
        self.degraded_reason = None if reachable else "the replay fixture was marked unreachable"

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> dict:
        if not self.reachable:
            return {}
        return {qid: self.answers[qid] for qid in questions if qid in self.answers}


def as_oracle(oracle: Any) -> Any:
    """Accept either an oracle object or a plain mapping, so a fixture can carry one inline."""
    if hasattr(oracle, "evaluate"):
        return oracle
    kind = oracle.get("kind", "none")
    if kind == "none":
        return NoOracle()
    if kind == "replay":
        return ReplayOracle(oracle.get("answers") or {}, oracle.get("model"))
    raise ValueError(
        f"oracle kind {kind!r} has no transport in the text tier; a networked oracle is supplied by the execute tier"
    )


# --- the battery --------------------------------------------------------------------------

def evaluate(
    spec: Mapping[str, Any],
    state: Mapping[str, Any],
    oracle: Any = None,
    *,
    bank: Mapping[str, Any] | None = None,
    mechanical: Iterable[Mapping[str, Any]] = (),
    capabilities: Mapping[str, Any] | None = None,
    song_id: str = "unknown",
    artifacts: Mapping[str, Any] | None = None,
    iterations: int = 0,
    generated_at: str | None = None,
) -> dict:
    """Run the battery and assemble the report.

    ``oracle`` defaults to the spec's own declaration: a spec that permits ``none`` gets no
    semantic verdicts at all rather than a silently missing section. ``mechanical`` carries the
    verdicts code and audio checkers already produced, which this module does not recompute.
    """
    bank = bank if bank is not None else load_bank()
    capabilities = capabilities or {}

    if oracle is None:
        oracle = NoOracle() if spec.get("oracle", "none") == "none" else {"kind": spec["oracle"]}
    oracle = as_oracle(oracle)

    by_requirement = {v["requirement_id"]: normalise_mechanical(v) for v in mechanical}
    questions = build_questions(spec, bank)

    answers: dict[str, Any] = {}
    degraded_reason = getattr(oracle, "degraded_reason", None)
    if getattr(oracle, "reachable", False) and not degraded_reason:
        try:
            answers = dict(oracle.evaluate(state, questions) or {})
        except Exception as exc:  # an unreachable oracle degrades; it never fails the run
            answers = {}
            degraded_reason = f"{type(exc).__name__}: {exc}"

    verdicts: list[dict] = []
    for requirement in spec.get("requirements", []):
        requirement_id = requirement["id"]
        if requirement_id in by_requirement:
            verdicts.append(by_requirement[requirement_id])
            continue

        checker = requirement.get("verify", "")
        if not checker.startswith("jev."):
            verdicts.append(
                unverified_verdict(requirement, "no automatic checker ran for " + (checker or "an unnamed checker"))
            )
            continue

        mine = [q for q in questions.values() if q.get("requirement_id") == requirement_id]
        if not mine:
            verdicts.append(unverified_verdict(requirement, f"no battery question is defined for {checker}"))
            continue
        if not getattr(oracle, "reachable", False) or degraded_reason:
            verdicts.append(unverified_verdict(requirement, degraded_reason or "the oracle was unreachable"))
            continue

        produced = []
        for question in mine:
            answer = answers.get(question["id"])
            if answer is None:
                produced.append(
                    unverified_verdict(requirement, f"the oracle returned no answer for {question['id']}")
                )
                continue
            produced.append(
                verdict_for(
                    requirement,
                    question,
                    answer,
                    {"kind": getattr(oracle, "kind", "none"), "model": getattr(oracle, "model", None)},
                    thresholds_for(question["checker"], bank),
                    bool(capabilities.get("description_gauge_passed")),
                )
            )

        # A requirement with several questions is as weak as its weakest answer: one axis
        # failing its bound fails the requirement.
        order = {"unmet": 0, "uncertain": 1, "unverified": 2, "met": 3}
        produced.sort(key=lambda v: order.get(v["verdict"], 4))
        verdicts.append(produced[0])

    # The summary violation question is read, never trusted over the individual answers.
    cross_check = None
    summary = questions.get("jev.any_serious_violation")
    if summary is not None and answers.get(summary["id"]) is not None:
        read = read_noul(answers[summary["id"]], thresholds_for("jev.any_serious_violation", bank))
        fired = read["verdict"] == "met"
        agreed = fired == any(v["verdict"] == "unmet" for v in verdicts)
        if agreed:
            note = "the summary question and the individual verdicts agree"
        elif fired:
            note = "the summary question reports a serious violation that no individual verdict records"
        else:
            note = "individual verdicts record a failure that the summary question does not"
        cross_check = {
            "noul": read.get("probability"),
            "fired": fired,
            "agrees_with_individual_verdicts": agreed,
            "note": note,
        }

    report: dict[str, Any] = {
        "report_version": "1",
        "song_id": song_id,
        "oracle": {
            "kind": getattr(oracle, "kind", "none"),
            "model": getattr(oracle, "model", None),
            "reachable": bool(getattr(oracle, "reachable", False)),
            "degraded_reason": degraded_reason,
        },
        "verdicts": verdicts,
        "overall": overall_verdict(verdicts),
        "unmet": unmet_list(verdicts),
        "counts": counts(verdicts),
        "iterations": iterations,
    }
    if generated_at:
        report["generated_at"] = generated_at
    if artifacts:
        report["artifacts"] = dict(artifacts)
    if cross_check is not None:
        report["cross_check"] = cross_check
    return report


# --- CLI ----------------------------------------------------------------------------------

def render_text(report: Mapping[str, Any]) -> str:
    """The report as a person reads it. The uncertain and unverified rows are not hidden."""
    lines = []
    oracle = report.get("oracle", {})
    lines.append(
        f"song {report.get('song_id')}  oracle {oracle.get('kind')}"
        + (f"@{oracle.get('model')}" if oracle.get("model") else "")
        + ("" if oracle.get("reachable") else "  (unreachable)")
    )
    if oracle.get("degraded_reason"):
        lines.append(f"  degraded: {oracle['degraded_reason']}")
    lines.append("")
    width = max((len(v["requirement_id"]) for v in report["verdicts"]), default=10)
    for verdict in report["verdicts"]:
        lines.append(
            f"  {verdict['requirement_id']:<{width}}  {verdict['verdict']:<10} "
            f"{verdict.get('severity', ''):<7} {verdict.get('checker', ''):<22} {verdict.get('note', '')}"
        )
    counts_ = report.get("counts", {})
    lines.append("")
    lines.append(f"  overall: {report['overall']}")
    lines.append(
        f"  met {counts_.get('met', 0)}/{counts_.get('total', 0)}  "
        f"by measurement {counts_.get('decided_by_measurement', 0)}  "
        f"by description {counts_.get('decided_by_description', 0)}  "
        f"uncertain {counts_.get('uncertain', 0)}  unverified {counts_.get('unverified', 0)}"
    )
    cross = report.get("cross_check")
    if cross is not None and not cross.get("agrees_with_individual_verdicts"):
        lines.append(f"  cross-check: {cross['note']}")
    if report.get("unmet"):
        lines.append("")
        lines.append("  not satisfied or not checked:")
        for item in report["unmet"]:
            lines.append(f"    {item}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2

    fixture = json.loads(Path(args[0]).read_text())
    oracle = fixture.get("answers")
    if oracle is not None:
        oracle = ReplayOracle(oracle, fixture.get("oracle_model"))

    report = evaluate(
        fixture.get("spec") or {},
        fixture.get("state") or {},
        oracle,
        mechanical=fixture.get("mechanical") or (),
        song_id=fixture.get("song_id", Path(args[0]).stem),
        generated_at=fixture.get("generated_at"),
    )
    if "--json" in args:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(report))
    # A reporter by default: the report is the product, and an uncertain or unverified
    # requirement is an outcome to read rather than a shell failure. `--strict` turns the
    # report into a gate for a CI job that only wants to pass a compliant song.
    if "--strict" in args:
        return 0 if report["overall"] in ("compliant", "compliant_with_unmet_soft") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
