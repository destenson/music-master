"""Tests for the deterministic spec: draft in, pre-render requirements and state out.

The point of this stage is that almost none of it is a judgement — every bin already declares the
checker its selection obliges — so most of these tests derive their expectations from the vocabulary
rather than recording them. That way the suite fails when the mapping is wrong and not when a label
is reworded.

The invariant that matters most is the one the first version of this stage broke: **a question may
only name fields the state actually carries**. A question that reads `targets.vocal_spec` while the
state has no `targets` is a construction bug that looks like a verdict, so it is asserted here for
every question the bank can build.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import jev, oracle, precheck, spec  # noqa: E402

VOCAB = spec.load_vocabulary()
BINS = {bin_["id"]: bin_ for bin_ in VOCAB["bins"]}
LABELS = {bin_["id"]: {o["id"]: o["label"] for o in bin_.get("options") or []} for bin_ in VOCAB["bins"]}


def label(bin_id: str, option_id: str) -> str:
    """The label the vocabulary gives, so an assertion cannot drift from the document."""
    return LABELS[bin_id][option_id]


def requirement(specification: dict, requirement_id: str) -> dict:
    for item in specification["requirements"]:
        if item["id"] == requirement_id:
            return item
    raise AssertionError(f"no requirement {requirement_id!r} in {[r['id'] for r in specification['requirements']]}")


def resolves(state: dict, path: str) -> bool:
    node = state
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def a_draft(**rest) -> dict:
    draft = {
        "selections": {
            "genre": {"options": ["trap"]},
            "drums": {"options": ["808_kicks"]},
            "bass": {"options": ["heavy_808_bass"]},
            "mood": {"options": ["wistful"]},
            "explicitness": {"options": ["clean"]},
            "content_exclusions": {"options": ["no_profanity"]},
            "avoid": {"options": ["no_synths"]},
        },
        "bpm": 92,
        "duration_s": 180,
        "theme": "leaving a coastal town in autumn",
        "caption": "Trap, 808 Kicks, Heavy 808 Bass, Wistful",
        "lyrics": "[Verse]\nSalt on the window",
        "artist_references": ["Bon Iver"],
    }
    draft.update(rest)
    return draft


class CaptionDerivationTest(unittest.TestCase):
    """Every sound property becomes a code coverage requirement on the caption string."""

    def setUp(self) -> None:
        self.built = spec.interpret(a_draft())
        self.spec = self.built["spec"]

    def test_a_genre_selection_becomes_a_caption_coverage_requirement(self) -> None:
        genre = requirement(self.spec, "caption_genre_fidelity")
        self.assertEqual(genre["verify"], "code.caption.coverage")
        self.assertEqual(genre["kind"], "mechanical")
        self.assertEqual(genre["severity"], "hard")
        self.assertEqual(genre["stage_enforced"], "plan")
        self.assertEqual(genre["target"], [label("genre", "trap")])

    def test_many_instrument_bins_become_one_requirement_carrying_every_label(self) -> None:
        instruments = requirement(self.spec, "caption_instrumentation")
        for option_id, bin_id in (("808_kicks", "drums"), ("heavy_808_bass", "bass")):
            self.assertIn(label(bin_id, option_id), instruments["target"])

    def test_a_sound_property_is_never_a_jev_requirement(self) -> None:
        # The audio cannot be judged from the input, so the pre-render spec must not ask about it.
        for item in self.spec["requirements"]:
            self.assertNotIn(item["verify"], ("jev.genre_fidelity", "jev.instrumentation", "jev.timbre"))

    def test_an_artist_reference_is_forbidden_in_the_caption(self) -> None:
        exclusions = requirement(self.spec, "caption_exclusions")
        self.assertEqual(exclusions["verify"], "code.caption.exclusions")
        self.assertEqual(exclusions["severity"], "policy")
        self.assertIn("Bon Iver", exclusions["target"])

    def test_a_negative_bin_contributes_its_element_not_its_label(self) -> None:
        # "No Synthesizers" is the choice; the requirement is that the song does not contain
        # synthesizers, so the label's negation is stripped before it becomes a target.
        exclusions = requirement(self.spec, "caption_exclusions")
        self.assertIn("Synthesizers", exclusions["target"])
        self.assertNotIn(label("avoid", "no_synths"), exclusions["target"])

    def test_coherence_and_budget_exist_whenever_anything_was_selected(self) -> None:
        self.assertEqual(requirement(self.spec, "caption_coherence")["verify"], "code.caption.coherence")
        budget = requirement(self.spec, "caption_budget")
        self.assertEqual(budget["severity"], "soft")
        self.assertEqual(budget["target"], VOCAB["tag_budget"])

    def test_nothing_selected_and_no_theme_is_no_requirement(self) -> None:
        bare = spec.interpret({"selections": {}})
        self.assertEqual(bare["spec"]["requirements"], [])

    def test_an_unknown_bin_or_option_is_ignored_rather_than_guessed(self) -> None:
        draft = a_draft(selections={"genre": {"options": ["trap"]}, "not_a_bin": {"options": ["x"]}})
        ids = [r["id"] for r in spec.interpret(draft)["spec"]["requirements"]]
        self.assertIn("caption_genre_fidelity", ids)


class LyricDerivationTest(unittest.TestCase):
    """Properties of the words become oracle requirements with their target in the state."""

    def setUp(self) -> None:
        self.built = spec.interpret(a_draft())
        self.spec = self.built["spec"]
        self.state = self.built["state"]

    def test_the_theme_comes_from_the_written_theme(self) -> None:
        theme = requirement(self.spec, "theme")
        self.assertEqual(theme["verify"], "jev.theme_adherence")
        self.assertEqual(theme["target"], "leaving a coastal town in autumn")
        self.assertEqual(theme["stage_enforced"], "lyrics")
        self.assertEqual(self.state["targets"]["theme"], theme["target"])

    def test_a_mood_selection_becomes_one_axis_question_bounded_below(self) -> None:
        mood = requirement(self.spec, "mood_axis")
        self.assertEqual(mood["verify"], "jev.mood_axis")
        self.assertEqual(mood["target"], {label("mood", "wistful").lower(): 3})

    def test_a_policy_bin_is_a_policy_requirement(self) -> None:
        explicitness = requirement(self.spec, "explicitness")
        self.assertEqual(explicitness["severity"], "policy")
        self.assertEqual(self.state["targets"]["explicitness"], label("explicitness", "clean"))

    def test_not_applicable_explicitness_is_no_requirement_at_all(self) -> None:
        built = spec.interpret(a_draft(selections={"explicitness": {"options": ["not_applicable"]}}))
        ids = [r["id"] for r in built["spec"]["requirements"]]
        self.assertNotIn("explicitness", ids)

    def test_each_excluded_thing_is_its_own_requirement(self) -> None:
        # One question over a list would let a satisfied exclusion hide an unmet one.
        content = requirement(self.spec, "content_no_profanity")
        self.assertEqual(content["verify"], "jev.content_policy")
        self.assertEqual(content["target"], "Profanity")
        self.assertEqual(self.state["targets"]["content_no_profanity"], "Profanity")

    def test_an_avoided_element_is_its_own_requirement(self) -> None:
        absence = requirement(self.spec, "avoid_no_synths")
        self.assertEqual(absence["verify"], "jev.absence_of")
        self.assertEqual(absence["target"], "Synthesizers")

    def test_artist_imitation_is_left_to_its_own_checker(self) -> None:
        # `no_artist_imitation` is a content exclusion in the vocabulary, but "does the lyric
        # contain artist imitation" is not a question; the named artist is the target instead.
        ids = [r["id"] for r in self.spec["requirements"]]
        self.assertNotIn("content_no_artist_imitation", ids)
        imitation = requirement(self.spec, "no_imitation")
        self.assertEqual(imitation["verify"], "jev.artist_pastiche")
        self.assertEqual(imitation["target"], "Bon Iver")


class SpecConformanceTest(unittest.TestCase):
    """The spec is a machine contract, so check it from the schema rather than by hand."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((REPO / "schemas" / "requirement-spec.schema.json").read_text())
        cls.item = cls.schema["$defs"]["Requirement"]
        cls.built = spec.interpret(a_draft())

    def test_required_top_level_keys_are_present(self) -> None:
        for key in self.schema["required"]:
            self.assertIn(key, self.built["spec"])

    def test_no_top_level_key_is_outside_the_schema(self) -> None:
        self.assertEqual(set(self.built["spec"]) - set(self.schema["properties"]), set())

    def test_every_requirement_fits_the_requirement_schema(self) -> None:
        for item in self.built["spec"]["requirements"]:
            with self.subTest(requirement=item["id"]):
                self.assertEqual(set(item) - set(self.item["properties"]), set())
                for key in self.item["required"]:
                    self.assertIn(key, item)
                self.assertIn(item["kind"], self.item["properties"]["kind"]["enum"])
                self.assertIn(item["severity"], self.item["properties"]["severity"]["enum"])
                self.assertIn(item["source"], self.item["properties"]["source"]["enum"])
                self.assertIn(item["stage_enforced"], self.item["properties"]["stage_enforced"]["enum"])

    def test_every_id_and_checker_matches_its_pattern(self) -> None:
        import re

        for item in self.built["spec"]["requirements"]:
            with self.subTest(requirement=item["id"]):
                self.assertRegex(item["id"], self.item["properties"]["id"]["pattern"])
                self.assertRegex(item["verify"], self.item["properties"]["verify"]["pattern"])


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.built = spec.interpret(a_draft())
        self.state = self.built["state"]

    def test_the_brief_carries_the_theme_and_the_excluded_artist(self) -> None:
        self.assertEqual(self.state["brief"]["theme"], "leaving a coastal town in autumn")
        self.assertEqual(self.state["brief"]["exclude_artist"], "Bon Iver")

    def test_every_requirement_target_travels_in_the_state(self) -> None:
        targets = self.state["targets"]
        for item in self.built["spec"]["requirements"]:
            if item.get("target") is not None:
                self.assertIn(item["id"], targets)

    def test_the_state_carries_the_requirement_list_for_the_cross_check(self) -> None:
        ids = {item["id"] for item in self.state["requirements"]}
        self.assertEqual(ids, {item["id"] for item in self.built["spec"]["requirements"]})

    def test_the_requested_tempo_is_planned_and_never_measured(self) -> None:
        self.assertEqual(self.state["planned"], {"tempo_bpm": 92, "duration_s": 180})
        self.assertNotIn("measured", self.state)

    def test_absent_parts_are_left_out_rather_than_emptied(self) -> None:
        bare = spec.interpret({"selections": {}, "bpm": 92})["state"]
        self.assertNotIn("caption", bare)
        self.assertNotIn("lyrics", bare)
        self.assertNotIn("targets", bare)


class QuestionWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.built = spec.interpret(a_draft())

    def test_every_lyric_requirement_gets_a_question_and_no_caption_one_does(self) -> None:
        questions = oracle.build_questions(self.built["spec"])
        asked = {q["requirement_id"] for q in questions.values() if q.get("requirement_id")}
        expected = {
            r["id"] for r in self.built["spec"]["requirements"] if r["verify"].startswith("jev.")
        }
        self.assertEqual(asked, expected)

    def test_every_question_reads_only_fields_the_state_carries(self) -> None:
        # The invariant this stage exists to keep: a question that names a path the state does not
        # carry is a construction bug, and a model will answer it anyway.
        questions = oracle.build_questions(self.built["spec"])
        projected = jev.project_state(self.built["state"], questions)
        for question_id, question in questions.items():
            for path in question.get("reads") or ():
                with self.subTest(question=question_id, path=path):
                    self.assertTrue(resolves(projected, path), f"{path} is not in the projected state")

    def test_a_spaced_axis_label_names_its_question_without_spaces(self) -> None:
        built = spec.interpret(a_draft(selections={"scene": {"options": ["late_night"]}}))
        questions = oracle.build_questions(built["spec"])
        axis_id = f"mood_axis.{spec._slug(label('scene', 'late_night'))}"
        self.assertIn(axis_id, questions)
        self.assertNotIn(" ", axis_id)
        instructions = questions[axis_id]["instructions"]
        self.assertEqual(instructions["axis"], label("scene", "late_night").lower())
        self.assertNotIn(label("scene", "late_night").lower(), instructions["question"])

    def test_the_whole_page_flow_produces_a_report_without_an_oracle(self) -> None:
        # Draft -> spec and state -> caption verdicts in code -> report. With no key the caption is
        # still decided and the lyric requirements are unverified, which is a report, not a failure.
        verdicts = precheck.caption_verdicts(
            self.built["spec"], self.built["state"], VOCAB, a_draft()["selections"]
        )
        report = oracle.evaluate(
            self.built["spec"],
            self.built["state"],
            oracle.NoOracle(),
            mechanical=verdicts,
            song_id="draft",
        )
        by_id = {v["requirement_id"]: v for v in report["verdicts"]}
        self.assertEqual(by_id["caption_genre_fidelity"]["verdict"], "met")
        self.assertEqual(by_id["caption_genre_fidelity"]["evidence_class"], "measurement")
        self.assertEqual(by_id["theme"]["verdict"], "unverified")
        self.assertEqual(report["overall"], "unverified")
        self.assertEqual(report["counts"]["decided_by_measurement"], 5)

    def test_the_whole_page_flow_produces_a_report_with_an_oracle(self) -> None:
        questions = oracle.build_questions(self.built["spec"])
        answers = {}
        for question_id, question in questions.items():
            if question["type"] == "noul":
                # The cross-check asks whether a violation exists, so a low answer is the good one.
                bad = question.get("polarity") == "violation" or question_id == "jev.any_serious_violation"
                answers[question_id] = {"noul": 0.05 if bad else 0.95}
            else:
                levels = len(question["levels"])
                answers[question_id] = {"distribution": [0.0] * (levels - 1) + [1.0]}
        verdicts = precheck.caption_verdicts(
            self.built["spec"], self.built["state"], VOCAB, a_draft()["selections"]
        )
        report = oracle.evaluate(
            self.built["spec"],
            self.built["state"],
            oracle.ReplayOracle(answers, "replay-authored"),
            mechanical=verdicts,
            song_id="draft",
        )
        by_id = {v["requirement_id"]: v for v in report["verdicts"]}
        self.assertEqual(by_id["theme"]["verdict"], "met")
        self.assertEqual(by_id["avoid_no_synths"]["verdict"], "met")
        self.assertEqual(report["overall"], "compliant")


if __name__ == "__main__":
    unittest.main()
