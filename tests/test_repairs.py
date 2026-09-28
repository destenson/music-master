"""Tests for the repair layer: what to change, and where.

The suggestions are code, so they are tested like code. Two properties matter and are asserted here
rather than sampled: a met verdict never carries advice (there is nothing to say), and every string
names the thing that actually failed — the missing tag, the axis, the excluded element — because a
suggestion that does not name the failure is a second way of saying nothing.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from musicmaster import repairs  # noqa: E402


def requirement(requirement_id: str, checker: str, target=None, severity: str = "hard", text: str = "") -> dict:
    return {
        "id": requirement_id,
        "verify": checker,
        "target": target,
        "severity": severity,
        "text": text or requirement_id,
    }


def verdict(state: str, note: str = "a reason") -> dict:
    return {"requirement_id": "x", "verdict": state, "note": note, "severity": "hard"}


class MetAndUnverifiedTest(unittest.TestCase):
    def test_a_met_verdict_carries_no_advice(self) -> None:
        advice = repairs.advise(requirement("theme", "jev.theme_adherence", "autumn"), verdict("met"))
        self.assertIsNone(advice["suggestion"])
        self.assertIsNone(advice["repair_instruction"])

    def test_an_unverified_verdict_says_why_rather_than_what_to_change(self) -> None:
        advice = repairs.advise(requirement("theme", "jev.theme_adherence", "autumn"), verdict("unverified", "no oracle key"))
        self.assertIn("no oracle key", advice["suggestion"])
        self.assertIsNone(advice["repair_instruction"])


class CaptionAdviceTest(unittest.TestCase):
    def test_coverage_names_the_tag_that_is_missing(self) -> None:
        advice = repairs.advise(
            requirement("caption_instrumentation", "code.caption.coverage", ["Distorted Guitar"]),
            verdict("unmet"),
            detail={"missing": ["Distorted Guitar"]},
        )
        self.assertIn("Distorted Guitar", advice["suggestion"])
        # A rewrite cannot fix a string, so the generator is never told to try.
        self.assertIsNone(advice["repair_instruction"])

    def test_an_exclusion_names_what_appeared(self) -> None:
        advice = repairs.advise(
            requirement("caption_exclusions", "code.caption.exclusions", ["Bon Iver"]),
            verdict("unmet"),
            detail={"present": ["Bon Iver"]},
        )
        self.assertIn("Bon Iver", advice["suggestion"])

    def test_a_budget_failure_names_the_budget_and_the_dropped_tags(self) -> None:
        advice = repairs.advise(
            requirement("caption_budget", "code.caption.budget", 64, severity="soft"),
            verdict("unmet"),
            detail={"omitted": ["Banjo"], "budget": 64},
        )
        self.assertIn("Banjo", advice["suggestion"])
        self.assertIn("64", advice["suggestion"])

    def test_coherence_carries_the_conflict(self) -> None:
        advice = repairs.advise(
            requirement("caption_coherence", "code.caption.coherence"),
            verdict("unmet"),
            detail={"problems": ["bin 'drums': 'no_drums' and '808_kicks' exclude each other"]},
        )
        self.assertIn("exclude each other", advice["suggestion"])


class LyricAdviceTest(unittest.TestCase):
    def test_the_theme_is_named(self) -> None:
        advice = repairs.advise(
            requirement("theme", "jev.theme_adherence", "leaving a coastal town in autumn"),
            verdict("unmet"),
        )
        self.assertIn("leaving a coastal town in autumn", advice["suggestion"])
        self.assertIn("leaving a coastal town in autumn", advice["repair_instruction"])

    def test_a_lower_bound_axis_asks_for_more(self) -> None:
        advice = repairs.advise(
            requirement("mood_axis", "jev.mood_axis", {"wistful": 3}),
            verdict("uncertain"),
            question={"instructions": {"axis": "wistful"}, "bound": "min"},
        )
        self.assertIn("wistful", advice["suggestion"])
        self.assertIn("weaker", advice["suggestion"])
        self.assertIn("not certain", advice["suggestion"])

    def test_an_upper_bound_axis_asks_for_less(self) -> None:
        advice = repairs.advise(
            requirement("mood_axis", "jev.mood_axis", {"sadness_max": 1}),
            verdict("unmet"),
            question={"instructions": {"axis": "sadness"}, "bound": "max"},
        )
        self.assertIn("sadness", advice["suggestion"])
        self.assertIn("stronger", advice["suggestion"])

    def test_the_hook_kind_is_named(self) -> None:
        advice = repairs.advise(requirement("hook_payoff", "jev.hook_payoff", "Anthemic Chorus"), verdict("uncertain"))
        self.assertIn("Anthemic Chorus", advice["suggestion"])

    def test_the_explicitness_limit_is_named(self) -> None:
        advice = repairs.advise(requirement("explicitness", "jev.explicitness", "Clean"), verdict("uncertain"))
        self.assertIn("Clean", advice["suggestion"])

    def test_an_excluded_content_kind_is_named(self) -> None:
        advice = repairs.advise(requirement("content_no_profanity", "jev.content_policy", "Profanity"), verdict("unmet"))
        self.assertIn("Profanity", advice["suggestion"])
        self.assertIsNotNone(advice["repair_instruction"])

    def test_an_avoided_element_is_named(self) -> None:
        advice = repairs.advise(requirement("avoid_no_synths", "jev.absence_of", "Synthesizers"), verdict("unmet"))
        self.assertIn("Synthesizers", advice["suggestion"])

    def test_the_artist_is_named(self) -> None:
        advice = repairs.advise(requirement("no_imitation", "jev.artist_pastiche", "Bon Iver"), verdict("unmet"))
        self.assertIn("Bon Iver", advice["suggestion"])

    def test_an_unknown_lyric_checker_still_says_something_actionable(self) -> None:
        advice = repairs.advise(
            requirement("mystery", "jev.something_new", "a thing", text="the lyric does a thing"),
            verdict("unmet", "it did not hold"),
        )
        self.assertIn("the lyric does a thing", advice["suggestion"])
        self.assertIsNotNone(advice["repair_instruction"])


class SummaryTest(unittest.TestCase):
    def test_all_met_says_ready(self) -> None:
        line = repairs.summary([{"verdict": "met", "severity": "hard"}])
        self.assertIn("Ready to render", line)

    def test_a_soft_miss_is_a_preference_not_a_blocker(self) -> None:
        line = repairs.summary(
            [
                {"requirement_id": "theme", "verdict": "met", "severity": "hard"},
                {"requirement_id": "hook_payoff", "verdict": "unmet", "severity": "soft", "text": "Chanted Hook"},
            ]
        )
        self.assertIn("preference", line)
        self.assertIn("Chanted Hook", line)
        self.assertNotIn("Before rendering", line)

    def test_a_hard_failure_leads_with_what_already_holds_and_says_what_to_fix(self) -> None:
        line = repairs.summary(
            [
                {"requirement_id": "theme", "verdict": "met", "severity": "hard"},
                {"requirement_id": "hook_payoff", "verdict": "unmet", "severity": "hard", "text": "Chanted Hook"},
            ]
        )
        self.assertIn("1 of 2", line)
        self.assertIn("Before rendering", line)
        self.assertIn("Chanted Hook", line)

    def test_an_unreachable_oracle_is_reported_as_unchecked_not_failed(self) -> None:
        line = repairs.summary(
            [{"requirement_id": "theme", "verdict": "unverified", "severity": "hard"}],
            {"degraded_reason": "no oracle key"},
        )
        self.assertIn("no oracle key", line)
        self.assertNotIn("failed", line)

    def test_an_empty_report_says_so(self) -> None:
        self.assertIn("nothing to check", repairs.summary([]))


if __name__ == "__main__":
    unittest.main()
