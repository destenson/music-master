"""Tests for the Jev wire format and the hosted oracle.

The wire format is where a hosted provider's assumptions meet this project's, and the two do not
match on three points that would each be silent if they were wrong: a score arrives as a 0-indexed
map plus an interpolated value the design says not to trust, a choice arrives with no companion
noul, and the response names the model that answered rather than the one that was asked for.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import jev, oracle  # noqa: E402

EXAMPLES = REPO / "vocabulary" / "examples"


def noul_question(**rest) -> dict:
    out = {
        "id": "theme",
        "type": "noul",
        "instructions": "Does it convey the theme?",
        "criteria": {"true": "yes", "false": "no"},
        "reads": ["brief.theme", "lyrics"],
        "severity": "hard",
    }
    out.update(rest)
    return out


def score_question(**rest) -> dict:
    out = {
        "id": "genre",
        "type": "score",
        "instructions": "How well does it fit?",
        "levels": ["wrong", "family", "recognisable", "clear", "textbook"],
        "reads": ["caption"],
        "severity": "hard",
    }
    out.update(rest)
    return out


class RequestShapeTest(unittest.TestCase):
    def test_a_noul_question_carries_its_criteria(self) -> None:
        payload = jev.question_payload(noul_question())
        self.assertEqual(payload["type"], "noul")
        self.assertEqual(payload["criteria"]["true"], "yes")

    def test_a_score_question_sends_its_levels_as_an_ordered_array(self) -> None:
        # Jev's score criteria is an array of level descriptions, not a map: the order is what
        # the 0-indexed probabilities in the response refer back to.
        payload = jev.question_payload(score_question())
        self.assertEqual(payload["criteria"], ["wrong", "family", "recognisable", "clear", "textbook"])

    def test_a_choice_question_sends_an_option_map(self) -> None:
        payload = jev.question_payload(
            {"type": "choice", "instructions": "Which?", "options": ["a", "b"]}
        )
        self.assertEqual(payload["criteria"], {"a": None, "b": None})

    def test_structured_instructions_are_passed_through_unchanged(self) -> None:
        # A question whose data travels as a field is sent as an object. Flattening it to a string
        # would splice the label into the sentence, which is the mistake the object avoids.
        instructions = {"axis": "Night Drive", "question": "How far does it convey `axis`?"}
        question = {"type": "score", "instructions": instructions, "levels": ["a", "b"]}
        self.assertEqual(jev.question_payload(question)["instructions"], instructions)

    def test_the_request_carries_the_state_a_model_and_the_questions(self) -> None:
        request = jev.build_request({"caption": "x"}, {"genre": score_question()})
        self.assertEqual(set(request), {"state", "model", "questions"})
        self.assertEqual(request["model"], jev.DEFAULT_MODEL)
        self.assertIn("genre", request["questions"])


class StateProjectionTest(unittest.TestCase):
    def test_only_the_paths_the_questions_read_are_sent(self) -> None:
        state = {"brief": {"theme": "autumn", "genre": "folk"}, "caption": "x", "lyrics": "y", "secret": "z"}
        projected = jev.project_state(state, {"theme": noul_question()})
        self.assertEqual(set(projected), {"brief", "lyrics"})
        self.assertEqual(projected["brief"], {"theme": "autumn"})

    def test_a_question_naming_a_bare_top_level_path_gets_all_of_it(self) -> None:
        state = {"caption": "x", "lyrics": "y"}
        projected = jev.project_state(state, {"c": score_question(reads=["caption"])})
        self.assertEqual(projected, {"caption": "x"})

    def test_a_question_that_asks_for_the_whole_state_gets_it(self) -> None:
        # The escape hatch is deliberate: a cross-check that must see everything says `state`.
        state = {"caption": "x", "lyrics": "y"}
        projected = jev.project_state(state, {"v": noul_question(reads=["state"])})
        self.assertEqual(projected, state)

    def test_paths_the_state_does_not_carry_are_not_invented(self) -> None:
        # `measured` is absent until something measures the audio, and the projection must not
        # manufacture an empty block that a question would read as a fact.
        state = {"caption": "x"}
        projected = jev.project_state(state, {"g": score_question(reads=["caption", "measured.lufs"])})
        self.assertEqual(projected, {"caption": "x"})


class ParseAnswerTest(unittest.TestCase):
    def test_a_noul_comes_back_as_the_seam_reads_it(self) -> None:
        parsed = jev.parse_answer(noul_question(), {"type": "noul", "noul": 0.93})
        self.assertEqual(parsed, {"noul": 0.93})

    def test_a_score_map_becomes_a_positional_distribution(self) -> None:
        answer = {
            "type": "score",
            "score": 3.05,
            "legend": {"0": "wrong", "1": "family", "2": "recognisable", "3": "clear", "4": "textbook"},
            "probabilities": {"0": 0.0, "1": 0.05, "2": 0.1, "3": 0.6, "4": 0.25},
            "confidence": 0.9,
        }
        parsed = jev.parse_answer(score_question(), answer)
        self.assertEqual(parsed["distribution"], [0.0, 0.05, 0.1, 0.6, 0.25])
        self.assertEqual(parsed["confidence"], 0.9)

    def test_the_interpolated_score_is_carried_but_the_seam_does_not_read_it(self) -> None:
        # The design's risk table says a model's numeric calibration is weak and that scores are
        # used ordinally. The value is kept for the record; the argmax is what decides.
        answer = {
            "type": "score",
            "score": 1.05,
            "legend": {"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"},
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05, "3": 0.0, "4": 0.0},
        }
        parsed = jev.parse_answer(score_question(), answer)
        self.assertEqual(parsed["interpolated_score"], 1.05)
        read = oracle.read_score(
            score_question(bound="min", bound_value=2), parsed, dict(oracle.DEFAULT_THRESHOLDS)
        )
        self.assertEqual(read["value"]["level"], 2)

    def test_a_score_with_levels_missing_from_the_map_still_lines_up(self) -> None:
        answer = {"type": "score", "legend": {"0": "a", "1": "b"}, "probabilities": {"0": 0.7, "1": 0.3}}
        parsed = jev.parse_answer(score_question(levels=["a", "b"]), answer)
        self.assertEqual(parsed["distribution"], [0.7, 0.3])

    def test_a_choice_lines_up_against_the_options_that_were_asked(self) -> None:
        question = {"type": "choice", "instructions": "?", "options": ["a", "b", "c"]}
        answer = {"type": "choice", "choice": "b", "probabilities": {"a": 0.2, "c": 0.1}, "confidence": 0.5}
        parsed = jev.parse_answer(question, answer)
        self.assertEqual(parsed["distribution"], [0.2, 0.0, 0.1])
        self.assertEqual(parsed["choice"], "b")

    def test_an_answer_of_the_wrong_type_is_a_bug_not_a_verdict(self) -> None:
        with self.assertRaises(ValueError):
            jev.parse_answer(noul_question(), {"type": "score", "probabilities": {}})

    def test_a_noul_without_a_probability_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            jev.parse_answer(noul_question(), {"type": "noul"})


class ParseResponseTest(unittest.TestCase):
    def test_the_response_names_the_model_that_answered(self) -> None:
        parsed = jev.parse_response(
            {"model": "jev-1.13.0", "usage": {"input_tokens": 10}, "answers": {"theme": {"type": "noul", "noul": 0.9}}},
            {"theme": noul_question()},
        )
        self.assertEqual(parsed["model"], "jev-1.13.0")
        self.assertEqual(parsed["usage"], {"input_tokens": 10})
        self.assertEqual(parsed["answers"]["theme"], {"noul": 0.9})
        self.assertEqual(parsed["problems"], [])

    def test_a_missing_answer_is_recorded_rather_than_defaulted(self) -> None:
        parsed = jev.parse_response({"answers": {}}, {"theme": noul_question()})
        self.assertEqual(parsed["answers"], {})
        self.assertEqual(len(parsed["problems"]), 1)
        self.assertIn("no answer", parsed["problems"][0])

    def test_one_unreadable_answer_does_not_lose_the_others(self) -> None:
        parsed = jev.parse_response(
            {"answers": {"theme": {"type": "noul", "noul": 0.9}, "genre": {"type": "noul"}}},
            {"theme": noul_question(), "genre": score_question()},
        )
        self.assertIn("theme", parsed["answers"])
        self.assertIn("genre", parsed["problems"][0])


class JevOracleTest(unittest.TestCase):
    def test_the_report_records_the_answering_model_not_the_alias(self) -> None:
        # The alias is what we ask for; the response is what a report is allowed to record, so a
        # report can never name a version that did not answer.
        seen: list[str] = []

        def transport(payload):
            seen.append(payload["model"])
            return {"model": "jev-1.13.0", "answers": {"theme": {"type": "noul", "noul": 0.95}}}

        spec = {"spec_version": "1", "oracle": "jev", "requirements": [
            {"id": "theme", "text": "t", "kind": "semantic", "verify": "jev.theme_adherence",
             "severity": "hard", "source": "explicit", "target": "autumn"}
        ]}
        host = jev.JevOracle(transport, model="jev-latest")
        report = oracle.evaluate(spec, {"brief": {"theme": "autumn"}}, host)
        self.assertEqual(seen, ["jev-latest"])
        self.assertEqual(host.model, "jev-1.13.0")
        self.assertEqual(report["oracle"]["model"], "jev-1.13.0")
        self.assertEqual(report["verdicts"][0]["verdict"], "met")
        self.assertEqual(report["verdicts"][0]["supported_by"][0]["source"], "jev@jev-1.13.0")

    def _report_for(self, transport) -> dict:
        spec = {"spec_version": "1", "oracle": "jev", "requirements": [
            {"id": "theme", "text": "t", "kind": "semantic", "verify": "jev.theme_adherence",
             "severity": "hard", "source": "explicit", "target": "autumn"}
        ]}
        return oracle.evaluate(spec, {"brief": {"theme": "autumn"}}, jev.JevOracle(transport))

    def test_a_rejected_key_degrades_to_unverified_with_a_readable_reason(self) -> None:
        def transport(payload):
            raise jev.JevError(401, "unauthorized")

        report = self._report_for(transport)
        self.assertFalse(report["oracle"]["reachable"])
        self.assertIn("API key was rejected", report["oracle"]["degraded_reason"])
        self.assertIn("TYPESAFE_API_KEY", report["oracle"]["degraded_reason"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")
        self.assertEqual(report["overall"], "unverified")

    def test_a_malformed_request_is_reported_as_our_bug_not_a_verdict(self) -> None:
        def transport(payload):
            raise jev.JevError(422, "questions.theme.criteria: bad")

        report = self._report_for(transport)
        self.assertIn("bug in a question", report["oracle"]["degraded_reason"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")

    def test_an_unreachable_service_is_reported_as_unreachable(self) -> None:
        def transport(payload):
            raise jev.JevError(None, None, "could not reach https://api.typesafe.ai: connection refused")

        report = self._report_for(transport)
        self.assertIn("could not be reached at all", report["oracle"]["degraded_reason"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")

    def test_a_transport_that_raises_anything_at_all_still_degrades(self) -> None:
        def transport(payload):
            raise RuntimeError("boom")

        report = self._report_for(transport)
        self.assertIn("RuntimeError", report["oracle"]["degraded_reason"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")

    def test_a_partial_response_names_the_questions_it_could_not_answer(self) -> None:
        def transport(payload):
            return {"model": "jev-1.13.0", "answers": {}}

        report = self._report_for(transport)
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")
        self.assertIn("no answer", report["verdicts"][0]["note"])

    def test_a_given_oracle_carries_an_error_into_every_requirement(self) -> None:
        # This is the page's path: it fetches in TypeScript and hands the failure back in.
        spec = {"spec_version": "1", "oracle": "jev", "requirements": [
            {"id": "theme", "text": "t", "kind": "semantic", "verify": "jev.theme_adherence",
             "severity": "hard", "source": "explicit", "target": "autumn"}
        ]}
        report = oracle.evaluate(
            spec,
            {"brief": {"theme": "autumn"}},
            oracle.GivenOracle({}, kind="jev", error="the API did not allow this page's origin"),
        )
        self.assertFalse(report["oracle"]["reachable"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")
        self.assertIn("origin", report["verdicts"][0]["note"])


class UrlLibTransportTest(unittest.TestCase):
    class Response:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def http_error(self, code: int, body: bytes = b'{"error":"x"}') -> urllib.error.HTTPError:
        return urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", code, "err", {}, io.BytesIO(body))

    def test_a_missing_key_never_reaches_the_network(self) -> None:
        with mock.patch.object(urllib.request, "urlopen") as urlopen:
            with self.assertRaises(jev.JevError) as caught:
                jev.urllib_transport({"state": "x"}, key=None)
        urlopen.assert_not_called()
        self.assertIn("TYPESAFE_API_KEY", str(caught.exception))

    def test_a_successful_call_returns_the_body(self) -> None:
        with mock.patch.object(urllib.request, "urlopen", return_value=self.Response({"model": "jev-1.13.0"})):
            out = jev.urllib_transport({"state": "x"}, key="k")
        self.assertEqual(out["model"], "jev-1.13.0")

    def test_a_busy_service_is_retried_and_then_succeeds(self) -> None:
        slept: list[float] = []
        side = [self.http_error(429), self.Response({"model": "jev-1.13.0"})]
        with mock.patch.object(urllib.request, "urlopen", side_effect=side):
            out = jev.urllib_transport({"state": "x"}, key="k", sleeper=slept.append)
        self.assertEqual(out["model"], "jev-1.13.0")
        self.assertEqual(len(slept), 1)

    def test_a_rejected_key_is_not_retried(self) -> None:
        with mock.patch.object(urllib.request, "urlopen", side_effect=self.http_error(401)) as urlopen:
            with self.assertRaises(jev.JevError) as caught:
                jev.urllib_transport({"state": "x"}, key="k", sleeper=lambda _: None)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(caught.exception.status, 401)

    def test_retries_run_out_and_the_last_error_is_raised(self) -> None:
        with mock.patch.object(urllib.request, "urlopen", side_effect=self.http_error(529)) as urlopen:
            with self.assertRaises(jev.JevError) as caught:
                jev.urllib_transport({"state": "x"}, key="k", retries=2, sleeper=lambda _: None)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(caught.exception.status, 529)

    def test_a_connection_failure_says_so_rather_than_showing_a_status(self) -> None:
        failure = urllib.error.URLError("Connection refused")
        with mock.patch.object(urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(jev.JevError) as caught:
                jev.urllib_transport({"state": "x"}, key="k")
        self.assertIsNone(caught.exception.status)
        self.assertIn("could not reach", str(caught.exception))


class CliTest(unittest.TestCase):
    def run_cli(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        import os

        environment = dict(os.environ)
        environment.pop("TYPESAFE_API_KEY", None)
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, "vocabulary/check_compliance.py", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_print_request_shows_the_bytes_that_would_leave_the_machine(self) -> None:
        done = self.run_cli(str(EXAMPLES / "compliance-indie-folk.json"), "--print-request")
        self.assertEqual(done.returncode, 0)
        request = json.loads(done.stdout)
        self.assertEqual(set(request), {"state", "model", "questions"})
        self.assertIn("theme", request["questions"])
        # The projection invents nothing: every key it sends came from the state, and the
        # questions it asks are the ones the spec declared.
        fixture_state = json.loads((EXAMPLES / "compliance-indie-folk.json").read_text())["state"]
        self.assertEqual(set(request["state"]) - set(fixture_state), set())

    def test_the_jev_oracle_without_a_key_reports_rather_than_failing(self) -> None:
        # No key is set in this environment, so the whole Jev path has to degrade honestly.
        done = self.run_cli(str(EXAMPLES / "compliance-indie-folk.json"), "--oracle=jev")
        self.assertEqual(done.returncode, 0)
        self.assertIn("TYPESAFE_API_KEY", done.stdout)
        self.assertIn("unverified", done.stdout)

    def test_an_unknown_option_is_a_usage_error(self) -> None:
        done = self.run_cli(str(EXAMPLES / "compliance-indie-folk.json"), "--nonsense")
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
