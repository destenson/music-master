"""Tests for the compliance oracle seam: the gate, the band, and the report's honesty.

The seam is the part of the compliance battery that decides whether an answer may decide a
requirement, so these tests are mostly about the ways a verdict can be *wrong while looking
right*: a probability inside the band read as a pass, a high noul on a violation question read
as satisfaction, a choice consumed without its companion, a description deciding a hard
requirement, or an unreachable oracle quietly turning into silence instead of `unverified`.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import oracle  # noqa: E402

EXAMPLES = REPO / "vocabulary" / "examples"


def spec_with(*requirements: dict, oracle_kind: str = "replay") -> dict:
    return {"spec_version": "1", "oracle": oracle_kind, "requirements": list(requirements)}


def requirement(req_id: str, verify: str, severity: str = "hard", **rest) -> dict:
    out = {"id": req_id, "text": req_id, "kind": "semantic", "verify": verify, "severity": severity, "source": "explicit"}
    out.update(rest)
    return out


NOUL = {"type": "noul", "instructions": "?", "criteria": {}}
SCORE = {"type": "score", "instructions": "?", "levels": ["a", "b", "c", "d", "e"]}


class BandTest(unittest.TestCase):
    """A probability inside the band is uncertain. It is never a pass, whatever the wording."""

    def read(self, value: float, polarity: str = "goal") -> dict:
        return oracle.read_noul({"noul": value}, dict(oracle.DEFAULT_THRESHOLDS), polarity)

    def test_above_accept_is_met(self) -> None:
        self.assertEqual(self.read(0.71)["verdict"], "met")

    def test_below_reject_is_unmet(self) -> None:
        self.assertEqual(self.read(0.29)["verdict"], "unmet")

    def test_inside_the_band_is_uncertain(self) -> None:
        for value in (0.30, 0.3001, 0.5, 0.6999, 0.70):
            with self.subTest(value=value):
                self.assertEqual(self.read(value)["verdict"], "uncertain")

    def test_the_band_is_checked_before_the_accept_threshold(self) -> None:
        # The two thresholds touch at 0.70; the band must win, or the same answer would be a
        # pass under one reading and a review under another.
        self.assertEqual(self.read(0.70)["verdict"], "uncertain")

    def test_margin_is_the_same_quantity_as_a_runner_up_margin(self) -> None:
        self.assertAlmostEqual(self.read(0.8)["margin"], 0.6)
        self.assertAlmostEqual(self.read(0.5)["margin"], 0.0)

    def test_missing_noul_is_unverified_not_unmet(self) -> None:
        self.assertEqual(oracle.read_noul({}, dict(oracle.DEFAULT_THRESHOLDS))["verdict"], "unverified")


class PolarityTest(unittest.TestCase):
    """A violation question points the opposite way at its requirement."""

    def test_high_noul_on_a_violation_question_fails_the_requirement(self) -> None:
        read = oracle.read_noul({"noul": 0.95}, dict(oracle.DEFAULT_THRESHOLDS), "violation")
        self.assertEqual(read["verdict"], "unmet")
        self.assertIn("violation question", read["note"])

    def test_low_noul_on_a_violation_question_satisfies_the_requirement(self) -> None:
        read = oracle.read_noul({"noul": 0.05}, dict(oracle.DEFAULT_THRESHOLDS), "violation")
        self.assertEqual(read["verdict"], "met")

    def test_the_probability_is_reported_as_asked_even_when_inverted(self) -> None:
        read = oracle.read_noul({"noul": 0.95}, dict(oracle.DEFAULT_THRESHOLDS), "violation")
        self.assertAlmostEqual(read["probability"], 0.95)

    def test_a_violation_question_still_respects_the_band(self) -> None:
        read = oracle.read_noul({"noul": 0.5}, dict(oracle.DEFAULT_THRESHOLDS), "violation")
        self.assertEqual(read["verdict"], "uncertain")

    def test_the_bank_marks_the_violation_shaped_questions(self) -> None:
        bank = oracle.load_bank()
        entries = bank["questions"]
        for checker in ("jev.artist_pastiche", "jev.content_policy", "jev.plagiarism_risk"):
            with self.subTest(checker=checker):
                self.assertEqual(entries[checker].get("polarity"), "violation")
        self.assertNotIn("polarity", entries["jev.theme_adherence"])


class ScoreAndChoiceTest(unittest.TestCase):
    def read_score(self, distribution: list[float], bound: str | None, value: int | None) -> dict:
        question = {"type": "score", "levels": ["1", "2", "3", "4", "5"], "bound": bound, "bound_value": value}
        return oracle.read_score(question, {"distribution": distribution}, dict(oracle.DEFAULT_THRESHOLDS))

    def test_a_lower_bound_is_met_at_or_above_it(self) -> None:
        self.assertEqual(self.read_score([0, 0, 0.1, 0.6, 0.3], "min", 3)["verdict"], "met")
        self.assertEqual(self.read_score([0.4, 0.3, 0.2, 0.1, 0], "min", 3)["verdict"], "unmet")

    def test_an_upper_bound_is_met_at_or_below_it(self) -> None:
        # `sadness_max: 1` is the case that makes direction matter: level 1 is the pass.
        self.assertEqual(self.read_score([0.7, 0.2, 0.1, 0, 0], "max", 1)["verdict"], "met")
        self.assertEqual(self.read_score([0, 0, 0.3, 0.5, 0.2], "max", 1)["verdict"], "unmet")

    def test_a_score_with_no_bound_is_unverified_rather_than_invented(self) -> None:
        read = self.read_score([0, 0, 0.1, 0.6, 0.3], None, None)
        self.assertEqual(read["verdict"], "unverified")
        self.assertIn("no bound", read["note"])

    def test_the_reported_probability_is_the_top_option_not_the_level(self) -> None:
        read = self.read_score([0, 0, 0.1, 0.6, 0.3], "min", 3)
        self.assertAlmostEqual(read["probability"], 0.6)

    def test_a_choice_without_its_companion_noul_is_refused(self) -> None:
        # A choice always names a winner, so alone it cannot say whether any option was good.
        question = {"type": "choice", "options": ["a", "b"], "levels": []}
        read = oracle.read_choice(question, {"distribution": [0.9, 0.1]}, dict(oracle.DEFAULT_THRESHOLDS))
        self.assertEqual(read["verdict"], "unverified")
        self.assertIn("companion noul", read["note"])

    def test_a_choice_with_a_low_companion_noul_is_unmet(self) -> None:
        question = {"type": "choice", "options": ["a", "b"]}
        read = oracle.read_choice(question, {"distribution": [0.9, 0.1], "noul": 0.1}, dict(oracle.DEFAULT_THRESHOLDS))
        self.assertEqual(read["verdict"], "unmet")

    def test_a_choice_below_the_top_gate_is_uncertain(self) -> None:
        question = {"type": "choice", "options": ["a", "b"]}
        read = oracle.read_choice(question, {"distribution": [0.45, 0.4], "noul": 0.8}, dict(oracle.DEFAULT_THRESHOLDS))
        self.assertEqual(read["verdict"], "uncertain")

    def test_a_choice_with_a_companion_above_the_gate_is_met(self) -> None:
        question = {"type": "choice", "options": ["a", "b"]}
        read = oracle.read_choice(question, {"distribution": [0.8, 0.15], "noul": 0.8}, dict(oracle.DEFAULT_THRESHOLDS))
        self.assertEqual(read["verdict"], "met")


class EvidenceGateTest(unittest.TestCase):
    """What each class may decide alone, from evidence-classes.md §3."""

    thresholds = dict(oracle.DEFAULT_THRESHOLDS)

    def gate(self, severity: str, classes: set[str], margin: float = 0.9, gauge: bool = False) -> tuple[str, str]:
        return oracle.apply_evidence_gate(severity, "met", classes, margin, self.thresholds, gauge)

    def test_measurement_may_decide_a_hard_requirement(self) -> None:
        self.assertEqual(self.gate("hard", {oracle.MEASUREMENT})[0], "met")

    def test_description_alone_may_not_decide_a_hard_requirement(self) -> None:
        verdict, reason = self.gate("hard", {oracle.DESCRIPTION})
        self.assertEqual(verdict, "uncertain")
        self.assertIn("corroborates", reason)

    def test_a_gauge_passed_description_may_decide_a_hard_requirement(self) -> None:
        self.assertEqual(self.gate("hard", {oracle.DESCRIPTION}, gauge=True)[0], "met")

    def test_a_self_report_never_decides_a_hard_requirement(self) -> None:
        self.assertEqual(self.gate("hard", {oracle.SELF_REPORT})[0], "uncertain")

    def test_an_oracle_needs_its_margin_to_decide_a_hard_requirement(self) -> None:
        self.assertEqual(self.gate("hard", {oracle.ORACLE}, margin=0.5)[0], "met")
        verdict, reason = self.gate("hard", {oracle.ORACLE}, margin=0.49)
        self.assertEqual(verdict, "uncertain")
        self.assertIn("margin", reason)

    def test_an_oracle_may_decide_a_policy_requirement_without_a_margin(self) -> None:
        self.assertEqual(self.gate("policy", {oracle.ORACLE}, margin=0.1)[0], "met")

    def test_description_and_self_report_may_not_decide_a_policy_requirement(self) -> None:
        self.assertEqual(self.gate("policy", {oracle.DESCRIPTION})[0], "uncertain")
        self.assertEqual(self.gate("policy", {oracle.SELF_REPORT})[0], "uncertain")

    def test_a_soft_requirement_is_not_capped(self) -> None:
        self.assertEqual(self.gate("soft", {oracle.DESCRIPTION})[0], "met")

    def test_the_gate_never_softens_a_verdict(self) -> None:
        # It caps; it does not promote. An unmet or uncertain reading passes through.
        for proposed in ("unmet", "uncertain", "unverified"):
            with self.subTest(proposed=proposed):
                self.assertEqual(
                    oracle.apply_evidence_gate("hard", proposed, {oracle.DESCRIPTION}, 0.0, self.thresholds)[0],
                    proposed,
                )


class QuestionBuildingTest(unittest.TestCase):
    def test_only_oracle_decidable_requirements_become_questions(self) -> None:
        spec = spec_with(
            requirement("duration", "audio.dsp.duration", kind="mechanical"),
            requirement("theme", "jev.theme_adherence"),
            requirement("hook", "human.listening", severity="soft"),
        )
        questions = oracle.build_questions(spec)
        self.assertIn("theme", questions)
        self.assertNotIn("duration", questions)
        self.assertNotIn("hook", questions)

    def test_each_mood_axis_gets_its_own_question_and_bound(self) -> None:
        spec = spec_with(requirement("mood", "jev.mood_axis", target={"wistful": 3, "sadness_max": 1}))
        questions = {k: v for k, v in oracle.build_questions(spec).items() if not v.get("cross_check")}
        self.assertEqual(set(questions), {"mood.wistful", "mood.sadness"})
        self.assertEqual(questions["mood.wistful"]["bound"], "min")
        self.assertEqual(questions["mood.wistful"]["bound_value"], 3)
        self.assertEqual(questions["mood.sadness"]["bound"], "max")
        self.assertEqual(questions["mood.sadness"]["bound_value"], 1)

    def test_an_axis_name_reaches_the_question_text(self) -> None:
        spec = spec_with(requirement("mood", "jev.mood_axis", target={"wistful": 3}))
        questions = oracle.build_questions(spec)
        self.assertIn("wistful", questions["mood.wistful"]["instructions"])
        self.assertIn("wistful", questions["mood.wistful"]["levels"][0])

    def test_a_score_requirement_with_no_numeric_target_uses_the_banks_default_bound(self) -> None:
        spec = spec_with(requirement("genre", "jev.genre_fidelity", target="indie folk"))
        question = oracle.build_questions(spec)["genre"]
        self.assertEqual(question["bound"], "min")
        self.assertEqual(question["bound_value"], 3)

    def test_the_summary_violation_question_is_always_asked(self) -> None:
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        questions = oracle.build_questions(spec)
        self.assertIn("jev.any_serious_violation", questions)
        self.assertTrue(questions["jev.any_serious_violation"]["cross_check"])

    def test_a_requirement_with_no_bank_entry_gets_no_question(self) -> None:
        spec = spec_with(requirement("odd", "jev.something_unbanked"))
        self.assertNotIn("odd", oracle.build_questions(spec))

    def test_every_bank_entry_is_well_formed(self) -> None:
        bank = oracle.load_bank()
        for checker, entry in bank["questions"].items():
            with self.subTest(checker=checker):
                self.assertIn(entry["type"], ("noul", "score", "choice"))
                self.assertTrue(entry.get("instructions"))
                self.assertTrue(entry.get("reads"))
                if entry["type"] == "noul":
                    self.assertIn("criteria", entry)
                if entry["type"] == "score":
                    self.assertGreaterEqual(len(entry["levels"]), 2)
                    self.assertTrue(all(entry["levels"]))
                if "polarity" in entry:
                    self.assertIn(entry["polarity"], ("goal", "violation"))

    def test_every_always_ask_checker_exists_in_the_bank(self) -> None:
        bank = oracle.load_bank()
        for checker in bank.get("always_ask") or ():
            self.assertIn(checker, bank["questions"])


class ReportTest(unittest.TestCase):
    def build(self, **kwargs) -> dict:
        spec = kwargs.pop("spec")
        state = kwargs.pop("state", {})
        return oracle.evaluate(spec, state, **kwargs)

    def test_a_missing_answer_leaves_its_requirement_unverified(self) -> None:
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        report = self.build(spec=spec, oracle=oracle.ReplayOracle({}))
        verdict = report["verdicts"][0]
        self.assertEqual(verdict["verdict"], "unverified")
        self.assertIn("no answer", verdict["note"])
        self.assertEqual(report["overall"], "unverified")

    def test_an_unreachable_oracle_degrades_rather_than_failing(self) -> None:
        spec = spec_with(
            requirement("theme", "jev.theme_adherence"),
            requirement("duration", "audio.dsp.duration", kind="mechanical"),
        )
        mechanical = [{"requirement_id": "duration", "verdict": "met", "checker": "audio.dsp.duration"}]
        report = self.build(
            spec=spec,
            oracle=oracle.ReplayOracle({"theme": {"noul": 0.99}}, reachable=False),
            mechanical=mechanical,
        )
        self.assertFalse(report["oracle"]["reachable"])
        self.assertIn("unreachable", report["oracle"]["degraded_reason"])
        by_id = {v["requirement_id"]: v for v in report["verdicts"]}
        self.assertEqual(by_id["theme"]["verdict"], "unverified")
        self.assertEqual(by_id["duration"]["verdict"], "met")

    def test_an_oracle_that_raises_degrades_with_the_reason_recorded(self) -> None:
        class Broken:
            kind = "jev"
            model = "jev-1.13.0"
            reachable = True
            degraded_reason = None

            def evaluate(self, state, questions):
                raise TimeoutError("no response in 30s")

        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        report = self.build(spec=spec, oracle=Broken())
        self.assertIn("TimeoutError", report["oracle"]["degraded_reason"])
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")

    def test_the_none_mode_reports_semantic_requirements_unverified(self) -> None:
        spec = spec_with(requirement("theme", "jev.theme_adherence"), oracle_kind="none")
        report = oracle.evaluate(spec, {}, None)
        self.assertEqual(report["oracle"]["kind"], "none")
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")
        self.assertEqual(report["overall"], "unverified")

    def test_a_human_only_checker_is_unverified(self) -> None:
        spec = spec_with(requirement("hook", "human.listening", severity="soft"))
        report = self.build(spec=spec, oracle=oracle.ReplayOracle({}))
        self.assertEqual(report["verdicts"][0]["verdict"], "unverified")
        self.assertIn("human.listening", report["verdicts"][0]["note"])

    def test_a_requirement_with_several_questions_is_as_weak_as_its_weakest(self) -> None:
        spec = spec_with(requirement("mood", "jev.mood_axis", target={"wistful": 3, "sadness_max": 1}))
        answers = {
            "mood.wistful": {"distribution": [0, 0, 0.1, 0.6, 0.3]},
            "mood.sadness": {"distribution": [0, 0.1, 0.2, 0.5, 0.2]},
        }
        report = self.build(spec=spec, oracle=oracle.ReplayOracle(answers))
        self.assertEqual(report["verdicts"][0]["requirement_id"], "mood")
        self.assertEqual(report["verdicts"][0]["verdict"], "unmet")

    def test_the_evidence_class_and_the_source_are_recorded(self) -> None:
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        report = self.build(spec=spec, oracle=oracle.ReplayOracle({"theme": {"noul": 0.93}}, model="jev-1.13.0"))
        verdict = report["verdicts"][0]
        self.assertEqual(verdict["evidence_class"], oracle.ORACLE)
        self.assertEqual(verdict["supported_by"][0]["source"], "replay@jev-1.13.0")
        self.assertEqual(verdict["supported_by"][0]["threshold"], 0.70)

    def test_mechanical_verdicts_default_to_the_measurement_class(self) -> None:
        spec = spec_with(requirement("duration", "audio.dsp.duration", kind="mechanical"))
        report = self.build(spec=spec, mechanical=[{"requirement_id": "duration", "verdict": "met", "checker": "audio.dsp.duration"}])
        self.assertEqual(report["verdicts"][0]["evidence_class"], oracle.MEASUREMENT)

    def test_the_counts_separate_measurement_from_description(self) -> None:
        spec = spec_with(
            requirement("duration", "audio.dsp.duration", kind="mechanical"),
            requirement("theme", "jev.theme_adherence"),
        )
        report = self.build(
            spec=spec,
            oracle=oracle.ReplayOracle({"theme": {"noul": 0.93}}),
            mechanical=[{"requirement_id": "duration", "verdict": "met", "checker": "audio.dsp.duration"}],
        )
        self.assertEqual(report["counts"]["met"], 2)
        self.assertEqual(report["counts"]["decided_by_measurement"], 1)
        self.assertEqual(report["counts"]["decided_by_description"], 0)

    def test_the_same_inputs_produce_the_same_report(self) -> None:
        # Reproducibility is the point of the artifact: no clock, no ordering, no float drift.
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        first = oracle.evaluate(spec, {}, oracle.ReplayOracle({"theme": {"noul": 0.93}}), song_id="s")
        second = oracle.evaluate(spec, {}, oracle.ReplayOracle({"theme": {"noul": 0.93}}), song_id="s")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_unmet_is_never_empty_when_the_report_is_not_compliant(self) -> None:
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        report = self.build(spec=spec, oracle=oracle.ReplayOracle({"theme": {"noul": 0.1}}))
        self.assertNotEqual(report["overall"], "compliant")
        self.assertTrue(report["unmet"])

    def test_a_cross_check_disagreement_is_reported(self) -> None:
        # The lyric clearly fails the theme, yet the summary question does not call it a
        # serious violation. The disagreement is the finding, not either answer alone.
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        answers = {"theme": {"noul": 0.05}, "jev.any_serious_violation": {"noul": 0.02}}
        report = self.build(spec=spec, oracle=oracle.ReplayOracle(answers))
        self.assertIsNotNone(report["cross_check"])
        self.assertFalse(report["cross_check"]["fired"])
        self.assertFalse(report["cross_check"]["agrees_with_individual_verdicts"])
        self.assertIn("individual verdicts record a failure", report["cross_check"]["note"])

    def test_an_oracle_above_the_accept_threshold_can_still_be_capped_by_its_margin(self) -> None:
        # 0.72 clears the accept threshold but not the margin a hard requirement needs, which
        # is the companion signal the design requires of an oracle judgement.
        spec = spec_with(requirement("theme", "jev.theme_adherence"))
        report = self.build(spec=spec, oracle=oracle.ReplayOracle({"theme": {"noul": 0.72}}))
        verdict = report["verdicts"][0]
        self.assertEqual(verdict["verdict"], "uncertain")
        self.assertIn("margin", verdict["note"])


class OverallPrecedenceTest(unittest.TestCase):
    def verdict(self, verdict_value: str, severity: str = "hard") -> dict:
        return {"requirement_id": "r", "severity": severity, "verdict": verdict_value, "evidence_class": oracle.MEASUREMENT}

    def test_all_met_is_compliant(self) -> None:
        self.assertEqual(oracle.overall_verdict([self.verdict("met")]), "compliant")

    def test_an_unmet_hard_requirement_is_non_compliant(self) -> None:
        self.assertEqual(oracle.overall_verdict([self.verdict("met"), self.verdict("unmet")]), "non_compliant")

    def test_an_uncertain_hard_requirement_is_not_compliant(self) -> None:
        self.assertEqual(oracle.overall_verdict([self.verdict("uncertain")]), "non_compliant")

    def test_an_unverified_hard_requirement_leaves_the_report_unverified(self) -> None:
        self.assertEqual(oracle.overall_verdict([self.verdict("met"), self.verdict("unverified")]), "unverified")

    def test_a_known_failure_outranks_an_unknown(self) -> None:
        self.assertEqual(
            oracle.overall_verdict([self.verdict("unverified"), self.verdict("unmet")]), "non_compliant"
        )

    def test_an_unmet_soft_requirement_is_compliant_with_unmet_soft(self) -> None:
        self.assertEqual(
            oracle.overall_verdict([self.verdict("met"), self.verdict("unmet", "soft")]),
            "compliant_with_unmet_soft",
        )

    def test_no_verdicts_at_all_is_unverified(self) -> None:
        self.assertEqual(oracle.overall_verdict([]), "unverified")


class SchemaConformanceTest(unittest.TestCase):
    """The report must fit the schema, checked from the schema itself rather than by hand.

    The schema is the machine contract and it has `additionalProperties: false`, so an extra
    key here is a real break. Reading the allowed keys and enums out of the schema means the
    two cannot drift apart without a test failing.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((REPO / "schemas" / "compliance-report.schema.json").read_text())
        cls.verdict_schema = cls.schema["$defs"]["Verdict"]

    def report(self) -> dict:
        fixture = json.loads((EXAMPLES / "compliance-indie-folk.json").read_text())
        return oracle.evaluate(
            fixture["spec"],
            fixture["state"],
            oracle.ReplayOracle(fixture["answers"], fixture["oracle_model"]),
            mechanical=fixture["mechanical"],
            song_id=fixture["song_id"],
        )

    def test_required_top_level_keys_are_present(self) -> None:
        report = self.report()
        for key in self.schema["required"]:
            self.assertIn(key, report)

    def test_no_top_level_key_is_outside_the_schema(self) -> None:
        report = self.report()
        self.assertEqual(set(report) - set(self.schema["properties"]), set())

    def test_no_verdict_key_is_outside_the_schema(self) -> None:
        for verdict in self.report()["verdicts"]:
            with self.subTest(requirement=verdict["requirement_id"]):
                self.assertEqual(set(verdict) - set(self.verdict_schema["properties"]), set())
                for key in self.verdict_schema["required"]:
                    self.assertIn(key, verdict)

    def test_every_enum_value_is_one_the_schema_allows(self) -> None:
        report = self.report()
        self.assertIn(report["overall"], self.schema["properties"]["overall"]["enum"])
        self.assertIn(report["oracle"]["kind"], self.schema["properties"]["oracle"]["properties"]["kind"]["enum"])
        for verdict in report["verdicts"]:
            with self.subTest(requirement=verdict["requirement_id"]):
                self.assertIn(verdict["verdict"], self.verdict_schema["properties"]["verdict"]["enum"])
                self.assertIn(verdict["severity"], self.verdict_schema["properties"]["severity"]["enum"])
                if verdict["evidence_class"] is not None:
                    self.assertIn(
                        verdict["evidence_class"],
                        self.verdict_schema["properties"]["evidence_class"]["enum"],
                    )
                for item in verdict["supported_by"]:
                    self.assertIn(
                        item["class"],
                        self.verdict_schema["properties"]["supported_by"]["items"]["properties"]["class"]["enum"],
                    )

    def test_the_fixture_lands_one_requirement_in_each_verdict(self) -> None:
        report = self.report()
        by_id = {v["requirement_id"]: v for v in report["verdicts"]}
        self.assertEqual(by_id["theme"]["verdict"], "met")
        self.assertEqual(by_id["key"]["verdict"], "unmet")
        self.assertEqual(by_id["vocals"]["verdict"], "uncertain")
        self.assertEqual(by_id["hook"]["verdict"], "unverified")
        self.assertEqual(by_id["no_imitation"]["verdict"], "met")
        self.assertEqual(report["overall"], "non_compliant")

    def test_the_fixture_reports_the_two_counts_and_the_cross_check(self) -> None:
        report = self.report()
        self.assertEqual(report["counts"]["decided_by_measurement"], 2)
        self.assertEqual(report["counts"]["decided_by_description"], 0)
        self.assertIn("cross_check", report)


class CliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "vocabulary/check_compliance.py", *args], cwd=REPO, capture_output=True, text=True
        )

    def test_the_worked_fixture_prints_a_report(self) -> None:
        done = self.run_cli(str(EXAMPLES / "compliance-indie-folk.json"))
        self.assertIn("overall: non_compliant", done.stdout)
        self.assertIn("unverified", done.stdout)

    def test_the_cli_reports_by_default_and_gates_only_under_strict(self) -> None:
        # A reporter that fails the shell for an uncertain requirement is the wrong default;
        # `--strict` is how a CI job asks for the gate.
        path = str(EXAMPLES / "compliance-indie-folk.json")
        self.assertEqual(self.run_cli(path).returncode, 0)
        self.assertEqual(self.run_cli(path, "--strict").returncode, 1)

    def test_help_exits_zero_when_asked_for(self) -> None:
        done = self.run_cli("--help")
        self.assertEqual(done.returncode, 0)
        self.assertIn("compliance oracle seam", done.stdout)

    def test_the_json_mode_emits_a_parsable_report(self) -> None:
        done = self.run_cli(str(EXAMPLES / "compliance-indie-folk.json"), "--json")
        report = json.loads(done.stdout)
        self.assertEqual(report["report_version"], "1")
        self.assertIn("counts", report)

    def test_the_wrapper_exposes_the_implementation(self) -> None:
        sys.path.insert(0, str(REPO / "vocabulary"))
        import check_compliance  # noqa: PLC0415

        self.assertIs(check_compliance.evaluate, oracle.evaluate)


if __name__ == "__main__":
    unittest.main()
