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

from musicmaster import repairs

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
#
# A bounded score is decided on `score_accept` against the mass on the *passing side* of its bound,
# not on the top-two margin. Jev puts most of a score's mass on the two adjacent levels, so a margin
# a two-way noul clears easily is nearly unreachable for a score: measured against the live service,
# a genre question with 0.79 of its mass on the passing levels came back with a 0.13 top-two margin,
# and one with no doubt about the answer came back at 0.03. The margin asks which of two neighbouring
# levels won, which is not the question a bound asks. The passing mass asks the bound's own question,
# and it is what a score verdict is decided on.
DEFAULT_THRESHOLDS = {
    "accept": 0.70,        # a noul at or above this is met
    "reject": 0.30,        # a noul at or below this is unmet
    "choice_top": 0.60,    # a choice whose top option is below this is uncertain
    "margin": 0.50,        # the top-two margin an oracle needs to decide a hard noul requirement
    "score_accept": 0.70,  # the mass a bounded score needs on the passing side of its bound
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


def _render(template: Any, params: Mapping[str, Any]) -> Any:
    """Substitute `{placeholders}` anywhere in a value, leaving its shape alone.

    Instructions may be a string or a structured object, which is what lets an axis be *data* the
    question refers to by backticked name rather than a word spliced into a sentence: "How {axis}
    does `caption` read?" is ungrammatical for a scene label like "Night Drive", while a question
    that points at `axis` reads the same for a mood and a setting alike.
    """
    if isinstance(template, str):
        out = template
        for key, value in params.items():
            out = out.replace("{" + key + "}", str(value))
        return out
    if isinstance(template, Mapping):
        return {key: _render(value, params) for key, value in template.items()}
    if isinstance(template, Sequence) and not isinstance(template, (str, bytes)):
        return [_render(item, params) for item in template]
    return template


def _with_rules(instructions: Any, rules: str | None) -> Any:
    """Attach the bank's judging rules to a question, wherever its text lives."""
    if not rules:
        return instructions
    if isinstance(instructions, str):
        return f"{instructions}\n\n{rules}"
    if isinstance(instructions, Mapping) and isinstance(instructions.get("question"), str):
        return {**instructions, "question": f"{instructions['question']}\n\n{rules}"}
    return instructions


def _compact(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _slug(text: str) -> str:
    """A question id is a key in a recorded fixture, so an axis name becomes a usable one."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(text).strip().lower()).strip("_") or "axis"


def _target_params(entry: Mapping[str, Any], target: Any, requirement_id: str | None = None) -> list[dict]:
    """Split a requirement target into one parameter set per question.

    Most targets produce exactly one question. A checker whose bank entry declares
    ``target_split: axes`` is the exception: its target is a mapping of axes, and each axis is
    its own question because they are separate judgements with separate thresholds. An axis key
    ending in ``_max`` is an upper bound -- ``sadness_max: 1`` asks that the song not read as
    sad, which is not the same question as ``wistful: 3`` asking that it does read as wistful.

    Every set carries ``requirement_id``, so a question's ``reads`` can name the target that
    belongs to its own requirement -- `targets.{requirement_id}` -- rather than the whole map.
    """
    if entry.get("target_split") == "axes" and isinstance(target, Mapping):
        params = []
        for key, value in target.items():
            axis = key[:-4] if key.endswith("_max") else key
            params.append(
                {
                    # `axis` is what the question says; `axis_id` is what the question is called.
                    # They differ because a spec's axis may be a label with spaces in it, while a
                    # question id has to survive being a JSON key in a recorded fixture.
                    "axis": axis,
                    "axis_id": _slug(axis),
                    "bound": "max" if key.endswith("_max") else "min",
                    "bound_value": value,
                    "requirement_id": requirement_id,
                }
            )
        return params
    params = {"target": _compact(target), "requirement_id": requirement_id}
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
        "reads": [_render(path, params) for path in entry.get("reads", [])],
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
    rules = bank.get("judging_rules")
    questions: dict[str, dict] = {}

    for requirement in spec.get("requirements", []):
        checker = requirement.get("verify", "")
        if not checker.startswith("jev."):
            continue
        entry = entries.get(checker)
        if entry is None:
            continue
        params_list = _target_params(entry, requirement.get("target"), requirement.get("id"))
        split = entry.get("target_split") == "axes"
        for index, params in enumerate(params_list):
            # An axis question is always qualified by its axis, so adding a second axis to a
            # target does not rename the first one and invalidate its recorded answers.
            question_id = (
                f"{requirement['id']}.{params.get('axis_id', index)}" if split else requirement["id"]
            )
            question = _question_from(entry, requirement, question_id, params)
            question["instructions"] = _with_rules(question["instructions"], rules)
            questions[question_id] = question

    # The cross-check is asked with every battery: a summary violation question that never
    # substitutes for the individual answers, because structural invariants between questions
    # do not hold.
    for checker in bank.get("always_ask") or ():
        entry = entries.get(checker)
        if entry is None:
            continue
        question = _question_from(entry, {"id": None, "verify": checker, "severity": "policy"}, checker, {})
        question["instructions"] = _with_rules(question["instructions"], rules)
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
    """A score against its bound, decided on the mass on the passing side of that bound.

    ``bound`` of ``max`` is an upper bound, anything else a lower bound, which is the distinction a
    mood target needs. The top level is reported for the record and does not decide: two adjacent
    levels of a bounded scale are two ways of saying the same thing, and which of them won is not
    the question a bound asks. Without a bound there is nothing to decide against, and saying so is
    more useful than inventing one.
    """
    distribution = answer.get("distribution")
    if not isinstance(distribution, Sequence) or isinstance(distribution, (str, bytes)) or not distribution:
        return {"verdict": "unverified", "note": "the answer carried no score distribution"}
    values = [float(value) for value in distribution]
    index, top, margin = _distribution_top(values)
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
        passing_mass = sum(value for position, value in enumerate(values, start=1) if position <= bound_value)
    else:
        passing_mass = sum(value for position, value in enumerate(values, start=1) if position >= bound_value)
    value["passing_mass"] = round(passing_mass, 6)
    accept = float(thresholds.get("score_accept", thresholds["accept"]))

    if passing_mass >= accept:
        proposed = "met"
        note = f"{passing_mass:.2f} of the mass is on the passing side of bound {bound_value} (top level {level})"
    elif 1.0 - passing_mass >= accept:
        proposed = "unmet"
        note = f"only {passing_mass:.2f} of the mass is on the passing side of bound {bound_value} (top level {level})"
    else:
        proposed = "uncertain"
        note = f"the passing side of bound {bound_value} holds {passing_mass:.2f}, inside the band (top level {level})"
    return {
        "verdict": proposed,
        "probability": passing_mass,
        "margin": passing_mass,
        "threshold": accept,
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
    # A bounded score already decided itself on the passing-side mass, so the top-two margin gate --
    # which is about which of two adjacent levels won -- is not applied to it. Applying both would
    # cap a well-supported bound at uncertain for a reason that does not bear on the bound.
    if read["verdict"] == "met" and question_type != "score":
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
    # The report's numbers are evidence; this is the sentence a person can act on. It is built in
    # code from the requirement and the answer, never written by the model.
    advice = repairs.advise(requirement, verdict, question=question)
    verdict["suggestion"] = advice["suggestion"]
    verdict["repair_instruction"] = advice["repair_instruction"]
    return verdict


def unverified_verdict(requirement: Mapping[str, Any], reason: str) -> dict:
    """A requirement nothing could decide. Never a pass, and never a failure either."""
    verdict: dict[str, Any] = {
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
    advice = repairs.advise(requirement, verdict)
    verdict["suggestion"] = advice["suggestion"]
    verdict["repair_instruction"] = advice["repair_instruction"]
    return verdict


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
    """What the system could not satisfy or could not check, and what to do about it."""
    out = []
    for verdict in verdicts:
        if verdict["verdict"] != "met":
            label = verdict.get("text") or verdict["requirement_id"]
            line = f"{verdict['requirement_id']} ({verdict.get('severity', '?')}, {verdict['verdict']}): {label}"
            if verdict.get("suggestion"):
                line += f" — {verdict['suggestion']}"
            out.append(line)
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


class GivenOracle:
    """Answers produced somewhere the text tier does not reach.

    The page fetches from TypeScript, so its answers arrive already parsed; this hands them to the
    seam with the provenance a report needs without pretending the text tier made the call. `kind`
    names the provider rather than the mechanism, so a report cannot describe a local readout as a
    hosted one. An `error` records why the answers are missing, which is what turns into the
    ``unverified`` reason on every requirement the oracle was supposed to decide.
    """

    def __init__(
        self,
        answers: Mapping[str, Any] | None = None,
        *,
        kind: str = "jev",
        model: str | None = None,
        reachable: bool = True,
        error: str | None = None,
        problems: Sequence[str] = (),
    ):
        self.answers = dict(answers or {})
        self.kind = kind
        self.model = model
        self.reachable = reachable and not error
        self.degraded_reason = error
        self.problems = list(problems)

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
        # A transport can fail inside the call rather than raising out of it -- a refused
        # connection, a rejected key, a CORS block -- and it records why on itself. Take that
        # reason, or every requirement would report only that no answer came back.
        reason_after_the_call = getattr(oracle, "degraded_reason", None)
        if reason_after_the_call:
            degraded_reason = reason_after_the_call
            answers = {}

    # An oracle that could answer most questions and not this one says which and why; carrying
    # that into the verdict beats a generic "no answer".
    problems: dict[str, str] = {}
    for entry in getattr(oracle, "problems", None) or ():
        question_id, _, detail = str(entry).partition(":")
        problems[question_id.strip()] = detail.strip() or str(entry)

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
                    unverified_verdict(
                        requirement,
                        problems.get(question["id"]) or f"the oracle returned no answer for {question['id']}",
                    )
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

    oracle_info = {
        "kind": getattr(oracle, "kind", "none"),
        "model": getattr(oracle, "model", None),
        "reachable": bool(getattr(oracle, "reachable", False)),
        "degraded_reason": degraded_reason,
    }
    report: dict[str, Any] = {
        "report_version": "1",
        "song_id": song_id,
        "oracle": oracle_info,
        "verdicts": verdicts,
        "overall": overall_verdict(verdicts),
        "summary": repairs.summary(verdicts, oracle_info),
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


def _oracle_for(kind: str, fixture: Mapping[str, Any], *, model: str | None = None, endpoint: str | None = None) -> Any:
    """Build the oracle a fixture asks for, degrading rather than crashing when it is absent.

    The key is read from the environment and passed straight to the transport. It is never
    written to the fixture, to a report, or to stdout.
    """
    if kind == "jev":
        import os

        from musicmaster import jev

        resolved = endpoint or jev.ENDPOINT
        return jev.JevOracle(
            lambda payload: jev.urllib_transport(
                payload, key=os.environ.get("TYPESAFE_API_KEY"), endpoint=resolved
            ),
            model=model or jev.DEFAULT_MODEL,
            endpoint=resolved,
        )
    if kind == "replay":
        return ReplayOracle(fixture.get("answers") or {}, fixture.get("oracle_model"))
    if kind == "none":
        return NoOracle()
    return GivenOracle({}, kind=kind, error=f"the {kind} oracle is not implemented yet")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2

    positional: list[str] = []
    want_json = False
    strict = False
    print_request = False
    oracle_kind: str | None = None
    model: str | None = None
    endpoint: str | None = None
    for arg in args:
        if arg == "--json":
            want_json = True
        elif arg == "--strict":
            strict = True
        elif arg == "--print-request":
            print_request = True
        elif arg.startswith("--oracle="):
            oracle_kind = arg.split("=", 1)[1]
        elif arg.startswith("--model="):
            model = arg.split("=", 1)[1]
        elif arg.startswith("--endpoint="):
            endpoint = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            print(f"unknown option {arg}\n")
            print(__doc__)
            return 2
        else:
            positional.append(arg)
    if not positional:
        print(__doc__)
        return 2

    path = Path(positional[0])
    fixture = json.loads(path.read_text())
    spec = fixture.get("spec") or {}
    state = fixture.get("state") or {}

    if print_request:
        # Exactly the bytes that would leave the machine, so the egress statement is something a
        # person can read rather than something they are asked to trust.
        from musicmaster import jev

        request = jev.build_request(state, build_questions(spec), model or jev.DEFAULT_MODEL)
        print(json.dumps(request, indent=2, ensure_ascii=False))
        return 0

    kind = oracle_kind or spec.get("oracle") or "none"
    report = evaluate(
        spec,
        state,
        _oracle_for(kind, fixture, model=model, endpoint=endpoint),
        mechanical=fixture.get("mechanical") or (),
        song_id=fixture.get("song_id", path.stem),
        generated_at=fixture.get("generated_at"),
    )
    if want_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(report))
    # A reporter by default: the report is the product, and an uncertain or unverified
    # requirement is an outcome to read rather than a shell failure. `--strict` turns the
    # report into a gate for a CI job that only wants to pass a compliant song.
    if strict:
        return 0 if report["overall"] in ("compliant", "compliant_with_unmet_soft") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
