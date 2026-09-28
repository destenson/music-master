"""The Jev wire format, and the transport the CLI uses for it.

TypeSafe's systemone endpoint takes a `state` and a map of typed questions and returns one
typed answer per question. That is a wire format, not a decision: pure JSON in and JSON out,
so it belongs in the text tier where the CLI and the page share one implementation of it. The
page's transport is TypeScript (``web/src/lib/jev.ts``), because the browser is where the fetch
has to happen; the CLI's is :func:`urllib_transport` below. Both hand the seam the same parsed
answers, so a difference between them is the transport and never the battery.

What Jev returns is not quite what the seam reads, and the differences are load-bearing:

  * A **score** comes back as a map keyed by 0-indexed level strings, a `legend`, and a `score`
    that can land *between* levels. The seam reads an ordered distribution and thresholds it
    ordinally, because the design's own risk table says Jev's numeric calibration is weak and
    that scores are to be used ordinally rather than interpolated. The interpolated value is
    carried through for the record and deliberately not used to decide a verdict.
  * A **choice** comes back with a probability map, a `confidence` and no companion noul. That
    is why the design requires the companion to be asked as its own question rather than read
    off the choice.
  * The response names the **model that answered**, and that is what the report records, so
    asking for an alias can never put an unpinned version into a report.

    TYPESAFE_API_KEY=... python3 vocabulary/check_compliance.py \\
        vocabulary/examples/compliance-indie-folk.json --oracle=jev
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

ENDPOINT = "https://api.typesafe.ai/v1/systemone"

# Pinned, not the `jev-latest` alias. The response is what actually enters a report either way,
# but asking for the pinned version is what makes a threshold re-measurable against a known model.
DEFAULT_MODEL = "jev-1.13.0"

RETRYABLE_STATUSES = (429, 529)


class JevError(Exception):
    """A request the service refused, or a connection that never reached it.

    ``status`` is None when nothing came back at all -- a DNS failure, a timeout, or a browser
    CORS refusal, which is the case a caller most needs told apart from a bad key.
    """

    def __init__(self, status: int | None, body: str | None = None, message: str | None = None):
        self.status = status
        self.body = body
        self.retryable = status in RETRYABLE_STATUSES
        if message is None:
            message = f"Jev returned {status}"
            if status in RETRYABLE_STATUSES:
                message += " (retryable)"
            if body:
                message += f": {body[:400]}"
        super().__init__(message)


# --- the request --------------------------------------------------------------------------

def question_payload(question: Mapping[str, Any]) -> dict:
    """One seam question in Jev's shape.

    The three types differ only in how criteria are expressed: a noul takes true/false
    descriptions, a score takes an ordered array of level descriptions, and a choice takes a map
    of option to rubric.
    """
    kind = question["type"]
    payload: dict[str, Any] = {"type": kind, "instructions": question["instructions"]}
    if kind == "noul":
        criteria = question.get("criteria") or {}
        if criteria:
            payload["criteria"] = dict(criteria)
    elif kind == "score":
        payload["criteria"] = list(question["levels"])
    elif kind == "choice":
        payload["criteria"] = {option: None for option in question["options"]}
    else:
        raise ValueError(f"unknown question type: {kind!r}")
    return payload


def project_state(state: Mapping[str, Any], questions: Mapping[str, Any]) -> dict:
    """Send only the state the questions named.

    Gating rule 5: shortlist and filter in code, because Jev's accuracy falls as unrelated detail
    grows. Each question declares the paths it reads, so the projection is the union of those and
    nothing else. A question that names `state` asks for the whole of it -- the cross-check does,
    which is why its reads list the parts it actually needs instead.
    """
    paths: set[str] = set()
    for question in questions.values():
        for path in question.get("reads") or ():
            paths.add(path)
    if not paths or "state" in paths:
        return dict(state)

    projected: dict[str, Any] = {}
    for path in sorted(paths):
        head, _, tail = path.partition(".")
        if head not in state:
            continue
        if not tail:
            projected[head] = state[head]
            continue
        value = state[head]
        if isinstance(value, Mapping) and tail in value:
            projected.setdefault(head, {})[tail] = value[tail]
    return projected


def build_request(
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    model: str = DEFAULT_MODEL,
) -> dict:
    """The exact body to POST. One request carries the whole battery."""
    return {
        "state": project_state(state, questions),
        "model": model,
        "questions": {qid: question_payload(q) for qid, q in questions.items()},
    }


# --- the response -------------------------------------------------------------------------

def _ordered(distribution: Mapping[str, Any], keys: Sequence[str]) -> list[float]:
    return [float(distribution.get(key, 0.0) or 0.0) for key in keys]


def parse_answer(question: Mapping[str, Any], answer: Mapping[str, Any]) -> dict:
    """One Jev answer in the shape the seam reads.

    A mismatched `type` is a bug in the battery rather than a verdict, so it raises and the
    caller records it instead of inventing an answer.
    """
    kind = question["type"]
    if answer.get("type") != kind:
        raise ValueError(f"asked a {kind} question and got a {answer.get('type')!r} answer")

    if kind == "noul":
        value = answer.get("noul")
        if not isinstance(value, (int, float)):
            raise ValueError("the noul answer carried no probability")
        return {"noul": float(value)}

    if kind == "score":
        probabilities = answer.get("probabilities") or {}
        legend = answer.get("legend") or {}
        # Jev keys the levels 0..n-1 as strings. Order them numerically, and fall back to the
        # legend's keys when probabilities arrived empty, so the distribution stays positional
        # against the levels we sent.
        source = probabilities or legend
        keys = sorted(source.keys(), key=lambda k: int(k) if str(k).lstrip("-").isdigit() else 0)
        out = {
            "distribution": _ordered(probabilities, keys),
            "confidence": answer.get("confidence"),
        }
        # Carried for the record only. The seam thresholds the distribution ordinally and never
        # interpolates, because a model's numeric calibration is not a measurement.
        if isinstance(answer.get("score"), (int, float)):
            out["interpolated_score"] = float(answer["score"])
        return out

    if kind == "choice":
        probabilities = answer.get("probabilities") or {}
        options = list(question.get("options") or probabilities.keys())
        out = {
            "distribution": _ordered(probabilities, options),
            "confidence": answer.get("confidence"),
        }
        if answer.get("choice") is not None:
            out["choice"] = answer["choice"]
        return out

    raise ValueError(f"unknown question type: {kind!r}")


def parse_response(response: Mapping[str, Any], questions: Mapping[str, Any]) -> dict:
    """Every answer the response carried, in the seam's shape.

    An answer that cannot be read is skipped rather than guessed at, and recorded in `problems`
    so the caller can say why that requirement came back `unverified` rather than silently
    reporting nothing.
    """
    answers_in = response.get("answers") or {}
    answers: dict[str, dict] = {}
    problems: list[str] = []

    for question_id, question in questions.items():
        raw = answers_in.get(question_id)
        if raw is None:
            problems.append(f"{question_id}: the response carried no answer")
            continue
        try:
            answers[question_id] = parse_answer(question, raw)
        except (ValueError, TypeError, AttributeError) as exc:
            problems.append(f"{question_id}: {exc}")

    return {
        "model": response.get("model"),
        "usage": response.get("usage"),
        "answers": answers,
        "problems": problems,
    }


# --- the oracle ---------------------------------------------------------------------------

class JevOracle:
    """The hosted oracle, behind whatever transport the caller has.

    The transport is one callable: a request body in, the response body out. That is the whole
    interface, which is what lets the CLI use urllib and the page use `fetch` without either
    reimplementing the battery.
    """

    kind = "jev"

    def __init__(
        self,
        transport: Callable[[dict], Mapping[str, Any]],
        *,
        model: str = DEFAULT_MODEL,
        endpoint: str = ENDPOINT,
    ):
        self.transport = transport
        self.requested_model = model
        self.model = model
        self.endpoint = endpoint
        self.reachable = True
        self.degraded_reason: str | None = None
        self.problems: list[str] = []
        self.usage: Any = None
        self.request_payload: dict | None = None

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> dict:
        payload = build_request(state, questions, self.requested_model)
        self.request_payload = payload
        try:
            response = self.transport(payload)
        except JevError as exc:
            self.reachable = False
            self.degraded_reason = _describe(exc)
            return {}
        except Exception as exc:  # a transport is allowed to fail in its own way
            self.reachable = False
            self.degraded_reason = f"{type(exc).__name__}: {exc}"
            return {}

        parsed = parse_response(response, questions)
        # Report the model that answered, never the alias that was asked for.
        self.model = parsed["model"] or self.requested_model
        self.usage = parsed["usage"]
        self.problems = parsed["problems"]
        return parsed["answers"]


def _describe(error: JevError) -> str:
    """A reason a person can act on, which a bare status code is not."""
    if error.status is None:
        return f"the oracle could not be reached at all: {error}"
    if error.status in (401, 403):
        return f"the API key was rejected ({error.status}). Check TYPESAFE_API_KEY."
    if error.status == 422:
        return (
            f"the request was rejected as malformed ({error.status}), which is a bug in a "
            f"question rather than a verdict: {error.body or ''}"[:400]
        )
    if error.status in RETRYABLE_STATUSES:
        return f"the service was busy ({error.status}) and stayed busy through the retries"
    return str(error)


# --- the CLI transport ---------------------------------------------------------------------

def urllib_transport(
    payload: Mapping[str, Any],
    *,
    key: str | None,
    endpoint: str = ENDPOINT,
    timeout: float = 60.0,
    retries: int = 2,
    sleeper: Callable[[float], None] | None = None,
) -> dict:
    """POST a request body with `urllib`, retrying only what the docs say to retry.

    429 and 529 are the two the API documents as back-off-and-retry; everything else is a
    decision and is raised. The key is read from the argument and never written anywhere.
    """
    import time
    import urllib.error
    import urllib.request

    if not key:
        raise JevError(None, None, "no API key was supplied; set TYPESAFE_API_KEY")
    sleep = sleeper or time.sleep
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    for attempt in range(retries + 1):
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            error = JevError(exc.code, detail)
            if not error.retryable or attempt == retries:
                raise error from None
            sleep(0.4 * (3**attempt))
        except urllib.error.URLError as exc:
            raise JevError(None, None, f"could not reach {endpoint}: {exc.reason}") from None
    raise JevError(None, None, "exhausted retries without a response")
