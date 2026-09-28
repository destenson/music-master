"""Tests for the deterministic Interpret stage: draft in, RequirementSpec and state out.

The point of this stage is that almost none of it is a judgement — every bin already declares the
checker its selection obliges — so most of these tests derive their expectations from the
vocabulary rather than recording them. That way the suite fails when the mapping is wrong and not
when a label is reworded.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import oracle, spec  # noqa: E402

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


def a_draft(**rest) -> dict:
    draft = {
        "selections": {
            "genre": {"options": ["trap"]},
            "drums": {"options": ["808_kicks"]},
            "bass": {"options": ["heavy_808_bass"]},
            "mood": {"options": ["wistful"]},
            "explicitness": {"options": ["clean"]},
            "avoid": {"options": ["no_synths"]},
        },
        "bpm": 92,
        "duration_s": 180,
        "theme": "leaving a coastal town in autumn",
        "caption": "Sparse fingerpicked guitar, close female alto",
        "lyrics": "[Verse]\nSalt on the window",
        "artist_references": ["Bon Iver"],
    }
    draft.update(rest)
    return draft


class DerivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.built = spec.interpret(a_draft())
        self.spec = self.built["spec"]

    def test_one_requirement_per_checker_not_per_bin(self) -> None:
        # Three instrument bins are three ways of describing one obligation, so they must not
        # become three requirements that would ask the same question under different ids.
        draft = a_draft(selections={
            "drums": {"options": ["808_kicks", "punchy_kick"]},
            "bass": {"options": ["heavy_808_bass"]},
            "synth": {"options": ["wet_synths"]},
        })
        built = spec.interpret(draft)
        instruments = [r for r in built["spec"]["requirements"] if r["verify"] == "jev.instrumentation"]
        self.assertEqual(len(instruments), 1)
        for option_id in ("808_kicks", "punchy_kick", "heavy_808_bass", "wet_synths"):
            bin_id = "drums" if option_id in LABELS["drums"] else ("bass" if option_id in LABELS["bass"] else "synth")
            self.assertIn(label(bin_id, option_id), instruments[0]["target"])

    def test_a_genre_selection_becomes_a_genre_obligation_carrying_its_label(self) -> None:
        genre = requirement(self.spec, "genre_fidelity")
        self.assertEqual(genre["verify"], "jev.genre_fidelity")
        self.assertEqual(genre["target"], label("genre", "trap"))
        self.assertEqual(genre["kind"], "semantic")
        self.assertEqual(genre["source"], "explicit")

    def test_a_mood_selection_becomes_one_axis_question_bounded_below(self) -> None:
        mood = requirement(self.spec, "mood_axis")
        self.assertEqual(mood["verify"], "jev.mood_axis")
        self.assertEqual(mood["target"], {label("mood", "wistful").lower(): 3})

    def test_a_policy_bin_is_a_policy_requirement(self) -> None:
        explicitness = requirement(self.spec, "explicitness")
        self.assertEqual(explicitness["severity"], "policy")
        self.assertEqual(explicitness["kind"], "policy")

    def test_the_avoid_bin_becomes_an_absence_obligation(self) -> None:
        absence = requirement(self.spec, "absence_of")
        self.assertEqual(absence["verify"], "jev.absence_of")
        self.assertEqual(absence["target"], label("avoid", "no_synths"))

    def test_the_artist_exclusion_becomes_a_policy_requirement(self) -> None:
        imitation = requirement(self.spec, "no_imitation")
        self.assertEqual(imitation["verify"], "jev.artist_pastiche")
        self.assertEqual(imitation["severity"], "policy")
        self.assertEqual(imitation["target"], "Bon Iver")

    def test_a_value_the_page_holds_and_a_bin_that_maps_to_the_same_checker_agree(self) -> None:
        # `bpm` is a draft field and the tempo bin maps to the same checker; the requirement must
        # appear once, or the report would carry the same obligation twice.
        draft = a_draft(selections={"genre": {"options": ["trap"]}, "tempo": {"options": []}}, bpm=92)
        ids = [r["id"] for r in spec.interpret(draft)["spec"]["requirements"]]
        self.assertEqual(ids.count("tempo"), 1)

    def test_the_theme_comes_from_the_written_theme(self) -> None:
        self.assertEqual(requirement(self.spec, "theme")["target"], "leaving a coastal town in autumn")

    def test_nothing_selected_and_no_theme_is_no_requirement(self) -> None:
        # An empty draft must not invent an obligation to check. Without a brief there is nothing
        # the user asked for, and a spec that says otherwise would manufacture failures.
        bare = spec.interpret({"selections": {}})
        self.assertEqual(bare["spec"]["requirements"], [])

    def test_an_unknown_bin_or_option_is_ignored_rather_than_guessed(self) -> None:
        draft = a_draft(selections={"genre": {"options": ["trap"]}, "not_a_bin": {"options": ["x"]}})
        ids = [r["id"] for r in spec.interpret(draft)["spec"]["requirements"]]
        self.assertIn("genre_fidelity", ids)


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

    def test_every_id_and_checker_matches_its_pattern(self) -> None:
        for item in self.built["spec"]["requirements"]:
            with self.subTest(requirement=item["id"]):
                self.assertRegex(item["id"], self.item["properties"]["id"]["pattern"])
                self.assertRegex(item["verify"], self.item["properties"]["verify"]["pattern"])


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = spec.interpret(a_draft())["state"]

    def test_the_brief_carries_what_the_bins_describe(self) -> None:
        self.assertEqual(self.state["brief"]["genre"], label("genre", "trap"))
        self.assertEqual(self.state["brief"]["theme"], "leaving a coastal town in autumn")
        self.assertEqual(self.state["brief"]["exclude_artist"], "Bon Iver")
        self.assertEqual(self.state["brief"]["avoid"], label("avoid", "no_synths"))

    def test_the_requested_tempo_is_planned_and_never_measured(self) -> None:
        # The page knows what it asked for and has not measured the audio. Calling that
        # `measured` would let a question read an intention as a fact.
        self.assertEqual(self.state["planned"], {"tempo_bpm": 92, "duration_s": 180})
        self.assertNotIn("measured", self.state)

    def test_absent_parts_are_left_out_rather_than_emptied(self) -> None:
        bare = spec.interpret({"selections": {}, "bpm": 92})["state"]
        self.assertNotIn("caption", bare)
        self.assertNotIn("lyrics", bare)
        self.assertNotIn("chords", bare)


class QuestionWiringTest(unittest.TestCase):
    def test_every_derived_requirement_gets_a_battery_question(self) -> None:
        built = spec.interpret(a_draft())
        questions = oracle.build_questions(built["spec"])
        requirement_ids = {r["id"] for r in built["spec"]["requirements"]}
        asked = {q["requirement_id"] for q in questions.values() if q.get("requirement_id")}
        # The mechanical requirements are decided by code and are not the oracle's to ask.
        self.assertEqual(asked, {r for r in requirement_ids if r not in ("tempo", "duration")})

    def test_a_spaced_axis_label_names_its_question_without_spaces(self) -> None:
        draft = a_draft(selections={"scene": {"options": ["late_night"]}})
        built = spec.interpret(draft)
        questions = oracle.build_questions(built["spec"])
        axis_id = f"mood_axis.{spec._slug(label('scene', 'late_night'))}"
        self.assertIn(axis_id, questions)
        self.assertNotIn(" ", axis_id)
        # The label is data, not a word spliced into the sentence: that is what lets one question
        # template serve a mood and a setting alike, and only the id has to be slugged.
        instructions = questions[axis_id]["instructions"]
        self.assertEqual(instructions["axis"], label("scene", "late_night").lower())
        self.assertNotIn(label("scene", "late_night").lower(), instructions["question"])
        self.assertTrue(instructions["question"].startswith("How far"))

    def test_the_whole_page_flow_produces_a_report(self) -> None:
        # Draft -> spec and state -> questions -> answers -> report, with a replay oracle standing
        # in for the network. This is the path the browser takes, minus the fetch.
        built = spec.interpret(a_draft())
        questions = oracle.build_questions(built["spec"])
        answers = {}
        for question_id, question in questions.items():
            if question["type"] == "noul":
                answers[question_id] = {"noul": 0.95}
            else:
                levels = len(question["levels"])
                answers[question_id] = {"distribution": [0.0] * (levels - 1) + [1.0]}
        report = oracle.evaluate(
            built["spec"],
            built["state"],
            oracle.ReplayOracle(answers, "replay-authored"),
            song_id="draft",
        )
        self.assertEqual(report["oracle"]["kind"], "replay")
        verdicts = {v["requirement_id"]: v["verdict"] for v in report["verdicts"]}
        self.assertEqual(verdicts["genre_fidelity"], "met")
        self.assertEqual(verdicts["theme"], "met")
        # The artist-pastiche question is asked as a violation, so 0.95 means it *was* imitated.
        self.assertEqual(verdicts["no_imitation"], "unmet")
        self.assertEqual(report["overall"], "non_compliant")


if __name__ == "__main__":
    unittest.main()
