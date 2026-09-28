"""Tests for the caption half of the pre-render check: exact facts about the string.

These are the checks that make "the caption carries what was chosen" decidable without a model, so
they are also the ones that must hold when there is no key and no service. The failure cases matter
more than the pass: a coverage check that cannot notice a dropped tag measures nothing.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import precheck, spec  # noqa: E402

VOCAB = spec.load_vocabulary()


def a_draft(**rest) -> dict:
    draft = {
        "selections": {
            "genre": {"options": ["trap"]},
            "drums": {"options": ["808_kicks"]},
            "avoid": {"options": ["no_synths"]},
        },
        "caption": "Trap, 808 Kicks",
        "lyrics": "[Verse]\nSalt on the window",
        "artist_references": [],
    }
    draft.update(rest)
    return draft


def verdicts(draft: dict, vocab: dict | None = None) -> dict[str, dict]:
    built = spec.interpret(draft, vocab=vocab or VOCAB)
    return {
        verdict["requirement_id"]: verdict
        for verdict in precheck.caption_verdicts(
            built["spec"], built["state"], vocab or VOCAB, draft.get("selections") or {}
        )
    }


class CoverageTest(unittest.TestCase):
    def test_a_caption_that_carries_every_tag_is_met(self) -> None:
        result = verdicts(a_draft())
        self.assertEqual(result["caption_genre_fidelity"]["verdict"], "met")
        self.assertEqual(result["caption_instrumentation"]["verdict"], "met")

    def test_a_missing_tag_is_unmet_and_the_note_names_it(self) -> None:
        result = verdicts(a_draft(caption="Trap"))
        instruments = result["caption_instrumentation"]
        self.assertEqual(instruments["verdict"], "unmet")
        self.assertIn("808 Kicks", instruments["note"])

    def test_a_tag_is_matched_as_a_whole_tag_not_a_substring(self) -> None:
        # "Trap" must not be satisfied by a longer, different tag that merely contains it.
        result = verdicts(a_draft(caption="Trap House, 808 Kicks"))
        self.assertEqual(result["caption_genre_fidelity"]["verdict"], "unmet")

    def test_the_verdict_is_measurement_not_an_oracle_account(self) -> None:
        result = verdicts(a_draft())
        self.assertEqual(result["caption_genre_fidelity"]["evidence_class"], "measurement")

    def test_there_are_no_caption_requirements_without_a_selection(self) -> None:
        built = spec.interpret({"selections": {}})
        self.assertEqual(precheck.caption_verdicts(built["spec"], built["state"], VOCAB, {}), [])


class ExclusionTest(unittest.TestCase):
    def test_an_excluded_artist_in_the_caption_is_unmet(self) -> None:
        result = verdicts(a_draft(caption="Trap, 808 Kicks, in the style of Bon Iver", artist_references=["Bon Iver"]))
        exclusions = result["caption_exclusions"]
        self.assertEqual(exclusions["verdict"], "unmet")
        self.assertIn("Bon Iver", exclusions["note"])

    def test_a_clean_caption_passes_the_exclusion_check(self) -> None:
        result = verdicts(a_draft(artist_references=["Bon Iver"]))
        self.assertEqual(result["caption_exclusions"]["verdict"], "met")


class CoherenceTest(unittest.TestCase):
    def test_mutually_exclusive_selections_are_unmet(self) -> None:
        # The vocabulary says `no_drums` excludes `808_kicks`, so both together is a contradiction
        # the UI should have prevented and a non-UI caller can still produce.
        draft = a_draft(selections={"drums": {"options": ["no_drums", "808_kicks"]}})
        result = verdicts(draft)
        self.assertEqual(result["caption_coherence"]["verdict"], "unmet")
        self.assertIn("exclude each other", result["caption_coherence"]["note"])

    def test_a_coherent_selection_is_met(self) -> None:
        self.assertEqual(verdicts(a_draft())["caption_coherence"]["verdict"], "met")


class BudgetTest(unittest.TestCase):
    def test_a_dropped_tag_is_reported_even_though_the_budget_is_doing_its_job(self) -> None:
        # Soft severity: dropping is intended when a selection overruns the budget, and the property
        # that the render will not be conditioned on the dropped tag is still worth stating.
        tiny = {**VOCAB, "tag_budget": 0}
        result = verdicts(a_draft(), vocab=tiny)
        budget = result["caption_budget"]
        self.assertEqual(budget["verdict"], "unmet")
        self.assertEqual(budget["severity"], "soft")
        self.assertIn("808 Kicks", budget["note"])

    def test_nothing_dropped_is_met(self) -> None:
        self.assertEqual(verdicts(a_draft())["caption_budget"]["verdict"], "met")


if __name__ == "__main__":
    unittest.main()
