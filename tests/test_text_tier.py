"""Tests for the text tier: the standard-library invariant, and the values it computes.

The invariant comes first. The text tier has two adapters — CPython and Pyodide — and a Pyodide
caller cannot install anything, so a *required* import outside the standard library would make the
browser quietly differ from the CLI.

Then the values. These are ordinary assertions with their expectations inline. Anything derivable
from a definition is derived rather than recorded — a section's duration *is* its bars times its
beat length, a song satisfies its template when every template section matched — so the suite fails
when the arithmetic or the mapping is wrong, and not when a message is reworded or the vocabulary
grows.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "musicmaster"
sys.path.insert(0, str(REPO))

from musicmaster import TEXT_TIER, lyrics, prompt, render, templates, timeline  # noqa: E402

ALLOWED_LOCAL = {"musicmaster"}

# `except*` arrives in 3.11; build the tuple defensively so the guard runs on older interpreters.
TRY_NODES = (ast.Try, ast.TryStar) if hasattr(ast, "TryStar") else (ast.Try,)

# Song, template id and tempo, as recorded in each song's song.json.
SONGS = (
    ("rap-metal-groove", "rap_metal_groove", 92.0),
    ("nu-metal-rap-rock", "nu_metal_rap_rock", 120.0),
)


def by_id(document: dict) -> dict:
    return {t["id"]: t for t in document["templates"]}


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True)


# --- The invariant -----------------------------------------------------------------------

def catches_import_error(node: ast.Try) -> bool:
    def names_import_error(handler: ast.ExceptHandler) -> bool:
        exc = handler.type
        if exc is None:  # bare `except:`
            return True
        candidates = exc.elts if isinstance(exc, ast.Tuple) else [exc]
        return any(
            (isinstance(c, ast.Name) and c.id == "ImportError")
            or (isinstance(c, ast.Attribute) and c.attr == "ImportError")
            for c in candidates
        )

    return any(names_import_error(handler) for handler in node.handlers)


def imports_in(tree: ast.Module) -> list[tuple[int, str, bool, bool]]:
    """(line, top-level module, is_relative, guarded_by_import_error) for every import."""
    found: list[tuple[int, str, bool, bool]] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, TRY_NODES):
            inner = guarded or catches_import_error(node)
            for statement in node.body:
                visit(statement, inner)
            for statement in [*node.orelse, *node.finalbody]:
                visit(statement, guarded)
            for handler in node.handlers:
                for statement in handler.body:
                    visit(statement, guarded)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name.split(".")[0], False, guarded))
            return
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            found.append((node.lineno, module, node.level > 0, guarded))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree, False)
    return found


class TextTierImportsTest(unittest.TestCase):
    def test_declared_modules_exist(self) -> None:
        for name in TEXT_TIER:
            with self.subTest(module=name):
                self.assertTrue(
                    (PACKAGE / f"{name}.py").is_file(),
                    f"musicmaster.TEXT_TIER names '{name}', which has no module",
                )

    def test_text_tier_imports_only_the_standard_library(self) -> None:
        violations: list[str] = []
        for name in TEXT_TIER:
            path = PACKAGE / f"{name}.py"
            tree = ast.parse(path.read_text(), filename=str(path))
            for line, module, is_relative, guarded in imports_in(tree):
                if is_relative or not module or module in ALLOWED_LOCAL:
                    continue
                if module in sys.stdlib_module_names:
                    continue
                if not guarded:
                    violations.append(
                        f"musicmaster/{name}.py:{line}: requires non-standard-library "
                        f"'{module}'. Guard it with `except ImportError`, or move the module "
                        f"to the execute tier."
                    )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_guard_recognises_the_known_optional_import(self) -> None:
        # The guard is only useful if it can see a real optional import; jsonschema is one, and if
        # it ever stops being guarded the test above must be the thing that says so.
        tree = ast.parse((PACKAGE / "vocabulary.py").read_text())
        optional = {
            module
            for _, module, is_relative, guarded in imports_in(tree)
            if guarded and not is_relative
        }
        self.assertIn("jsonschema", optional)


# --- Tag rendering -----------------------------------------------------------------------

class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vocab = render.load_vocabulary()
        cls.fixture = json.loads(
            (REPO / "vocabulary/examples/late-night-trap.json").read_text()
        )

    def test_render_reproduces_the_example_expectation(self) -> None:
        # The example carries its own expected tags, so this compares against the fixture's
        # declared result rather than against a copy of the rendered string.
        result = render.render(self.vocab, self.fixture["selections"])
        self.assertEqual(result["tags"], self.fixture["rendered_tags"])
        self.assertEqual(result["string"], self.fixture["rendered_string"])

    def test_render_never_exceeds_the_tag_budget(self) -> None:
        result = render.render(self.vocab, self.fixture["selections"])
        self.assertLessEqual(len(result["tags"]), self.vocab["tag_budget"])

    def test_a_positive_bin_never_contributes_negatives(self) -> None:
        # Only a negative-polarity bin may subtract; a positive selection leaking into the
        # exclusion list would silently remove tags from the caption.
        bin_ = next(
            b for b in self.vocab["bins"]
            if b.get("polarity", "positive") == "positive" and b.get("options")
        )
        result = render.render(self.vocab, {bin_["id"]: {"options": [bin_["options"][0]["id"]]}})
        self.assertEqual(result["negatives"], [])

    def test_coherence_reports_mutually_exclusive_selections(self) -> None:
        for bin_ in self.vocab["bins"]:
            for option in bin_.get("options") or []:
                for excluded in option.get("excludes") or []:
                    problems = render.coherence_check(
                        self.vocab, {bin_["id"]: {"options": [option["id"], excluded]}}
                    )
                    self.assertTrue(
                        problems,
                        f"bin '{bin_['id']}': '{option['id']}' excludes '{excluded}', "
                        f"but selecting both was reported as coherent",
                    )
                    return
        self.skipTest("the vocabulary declares no exclusions to check")


# --- The time budget ---------------------------------------------------------------------

class TimelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = timeline.load(timeline.TEMPLATES_PATH)
        cls.st = timeline.load(timeline.SECTION_TAGS_PATH)
        cls.profile = timeline.rate_profile(timeline.load_delivery_rates(), "sung_slow")
        cls.template = by_id(cls.doc)["rap_metal_groove"]
        cls.bpm = 92.0
        cls.plan = timeline.build_timeline(cls.template, cls.bpm, cls.st, cls.profile, cls.doc)

    def bar_seconds(self, bpm: float) -> float:
        return timeline.BEATS_PER_BAR * 60.0 / bpm

    def test_each_section_lasts_its_bars_at_the_tempo(self) -> None:
        for row in self.plan["rows"]:
            with self.subTest(section=row["label"]):
                self.assertAlmostEqual(row["dur_s"], row["bars"] * self.bar_seconds(self.bpm))

    def test_totals_are_the_sum_of_the_sections(self) -> None:
        totals = self.plan["totals"]
        self.assertEqual(totals["sections"], len(self.plan["rows"]))
        self.assertAlmostEqual(totals["total_s"], sum(r["dur_s"] for r in self.plan["rows"]))
        self.assertAlmostEqual(
            totals["total_s"], totals["vocal_s"] + totals["instrumental_s"]
        )

    def test_instrumental_sections_carry_no_syllables(self) -> None:
        # Writing words into an instrumental is an error the lyric checker reports, so the plan
        # must not offer it a budget in the first place.
        for row in self.plan["rows"]:
            if not row["instrumental"]:
                continue
            with self.subTest(section=row["label"]):
                self.assertEqual(row["singable_s"], 0.0)
                self.assertEqual(row["ceiling"], 0)
                self.assertEqual(row["budget_min"], 0)
                self.assertEqual(row["budget_max"], 0)

    def test_the_budget_is_clipped_by_what_the_clock_allows(self) -> None:
        band = self.profile["band"]
        for row in self.plan["rows"]:
            if row["instrumental"]:
                continue
            with self.subTest(section=row["label"]):
                self.assertEqual(row["ceiling"], round(row["singable_s"] * self.profile["hard_max"]))
                self.assertEqual(row["budget_min"], row["lines"] * band[0])
                self.assertEqual(row["budget_max"], min(row["lines"] * band[1], row["ceiling"]))

    def test_scaling_to_a_duration_keeps_the_bar_grid(self) -> None:
        # Duration is reached by scaling bars, so every section keeps an even count of at least two
        # and a longer target never yields fewer bars than a shorter one.
        previous = 0
        for target in (60.0, 120.0, 180.0, 240.0, 400.0):
            sections, achieved = templates.scale_to_duration(self.template["sections"], target, self.bpm)
            bars = [s["bars"] for s in sections]
            with self.subTest(target=target):
                self.assertTrue(all(b % 2 == 0 and b >= 2 for b in bars), bars)
                self.assertAlmostEqual(achieved, sum(bars) * self.bar_seconds(self.bpm))
                self.assertGreaterEqual(sum(bars), previous)
            previous = sum(bars)


# --- Lyric checking ----------------------------------------------------------------------

class LyricsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = lyrics.load(lyrics.SECTION_TAGS_PATH)
        cls.doc = lyrics.load(lyrics.TEMPLATES_PATH)

    def test_syllables_counts_by_spelling(self) -> None:
        # The counter is documented as approximate, so only unambiguous words are pinned here:
        # vowel quality and words whose spelling implies the wrong pronunciation are its known
        # blind spots, and asserting those would enshrine the error rather than catch it.
        for word, expected in [("future", 2), ("canvas", 2), ("screen", 1), ("tonight", 2), ("wire", 1)]:
            with self.subTest(word=word):
                self.assertEqual(lyrics.syllables(word), expected)

    def test_analyse_returns_one_entry_per_section_header(self) -> None:
        sample = ["[Verse 1]", "[rap]", "a line of words", "", "[Chorus]", "another line"]
        found = lyrics.analyse(sample, self.st, lyrics.Report())
        self.assertEqual(len(found), 2)
        self.assertTrue(all(f.get("section") for f in found))

    def test_each_song_satisfies_its_own_template(self) -> None:
        for song, template_id, _bpm in SONGS:
            with self.subTest(song=song):
                lines = (REPO / "songs" / song / "lyrics.md").read_text().splitlines()
                report = lyrics.Report()
                meter = lyrics.check_meter_and_rhyme(lines, self.st, report)
                template = by_id(self.doc)[template_id]
                conformance = lyrics.check_template(meter, self.st, template, report)
                self.assertEqual(report.errors, [])
                self.assertEqual(conformance["missing"], [])
                self.assertEqual(len(conformance["matched"]), len(template["sections"]))


# --- The render path: the prompt and the graph it renders to ------------------------------

class PromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        song = REPO / "songs/rap-metal-groove"
        config = json.loads((song / "song.json").read_text())
        cls.doc = {
            "song_id": config["song_id"],
            "template_id": config["template_id"],
            "bpm": config["bpm"],
            "seed": config["seed"],
            "selections": json.loads((song / "selections.json").read_text())["selections"],
            "lyrics": (song / "lyrics.md").read_text(),
            "brief": (song / "brief.md").read_text(),
            "artist_references": config.get("artist_references", []),
            "vocabulary_path": REPO / "vocabulary" / "tag-bins.json",
            "vocabulary": render.load_vocabulary(),
            "section_tags": timeline.load(timeline.SECTION_TAGS_PATH),
            "templates_doc": timeline.load(timeline.TEMPLATES_PATH),
        }
        cls.artifacts = prompt.build(cls.doc)

    def test_the_prompt_pins_the_composition_it_references(self) -> None:
        # Derived, not recorded: the hash is the hash of the bytes the composition is written as.
        self.assertEqual(
            self.artifacts["prompt"]["form"]["composition_sha256"],
            prompt.sha256_bytes(prompt.serialise(self.artifacts["composition"]).encode()),
        )

    def test_the_graph_is_a_rendering_of_the_prompt(self) -> None:
        # Every input the graph carries must come from the prompt; a second source of truth here is
        # how a render stops matching the artifact of record.
        graph = self.artifacts["workflow"]
        recorded = self.artifacts["prompt"]
        self.assertEqual(graph["4"]["inputs"]["tags"], recorded["style"]["rendered_string"])
        self.assertEqual(graph["4"]["inputs"]["lyrics"], self.doc["lyrics"])
        self.assertEqual(graph["4"]["inputs"]["bpm"], recorded["metadata"]["bpm"])
        self.assertEqual(graph["4"]["inputs"]["duration"], recorded["metadata"]["duration_s"])
        self.assertEqual(graph["6"]["inputs"]["seconds"], recorded["metadata"]["duration_s"])
        self.assertEqual(graph["8"]["inputs"]["seed"], recorded["target"]["seed"])
        self.assertEqual(graph["10"]["inputs"]["filename_prefix"], f"audio/{recorded['song_id']}")

    def test_the_prompt_is_deterministic(self) -> None:
        self.assertEqual(
            prompt.build(self.doc)["prompt_sha256"], self.artifacts["prompt_sha256"]
        )

    def test_the_tempo_note_states_the_tempo_it_was_given(self) -> None:
        # The note is documentation and used to be copied between songs, so a 92 BPM song claimed
        # 120. Deriving it from the tempo is what stops that drifting again.
        notes = {note["field"]: note["why"] for note in self.artifacts["prompt"]["notes"]}
        self.assertIn(f"{self.doc['bpm']:g} BPM", notes["metadata.bpm"])


# --- The entry points, and the wrappers --------------------------------------------------

class EntryPointTest(unittest.TestCase):
    def test_wrappers_delegate_rather_than_duplicate(self) -> None:
        # `vocabulary/` is a compatibility shim. An importer such as build_and_submit.py must reach
        # the package's objects, not a second copy of the logic that would drift from it.
        sys.path.insert(0, str(REPO / "vocabulary"))
        for wrapper_name, module, attribute in [
            ("render_tags", render, "render"),
            ("timeline", timeline, "build_timeline"),
            ("check_lyrics", lyrics, "analyse"),
        ]:
            with self.subTest(wrapper=wrapper_name):
                wrapper = importlib.import_module(wrapper_name)
                self.assertIs(getattr(wrapper, attribute), getattr(module, attribute))

    def test_help_prints_the_modules_own_docstring(self) -> None:
        # The invariant is not the wording — that is the maintainer's to change — but that the help
        # a user sees is the implementation module's docstring, i.e. it moved with the code.
        for script, module, args in [
            ("vocabulary/check_lyrics.py", lyrics, []),
            ("vocabulary/structure_templates.py", templates, ["--brief"]),
        ]:
            self.assertTrue(module.__doc__ and module.__doc__.strip())
            for argv in ([script, *args], ["-m", module.__name__, *args]):
                with self.subTest(argv=argv):
                    proc = run_cli(*argv)
                    self.assertEqual(proc.returncode, 2, proc.stderr.decode())
                    self.assertEqual(proc.stdout.decode(), module.__doc__ + "\n")

    def test_self_test_passes(self) -> None:
        # run_self_test() asserts its own error fragments internally and returns 1 when one is
        # missing, so the exit status is the whole signal.
        for argv in (
            ["vocabulary/check_lyrics.py", "--self-test"],
            ["-m", "musicmaster.lyrics", "--self-test"],
        ):
            with self.subTest(argv=argv):
                proc = run_cli(*argv)
                self.assertEqual(proc.returncode, 0, proc.stdout.decode()[:400])

    def test_every_entry_point_runs(self) -> None:
        invocations = [
            ("vocabulary/render_tags.py", ["vocabulary/examples/late-night-trap.json"]),
            ("vocabulary/structure_templates.py", ["--list"]),
            ("vocabulary/validate_vocabulary.py", []),
            ("vocabulary/check_lyrics.py", ["songs/rap-metal-groove/lyrics.md",
                                            "--template=rap_metal_groove", "--bpm=92"]),
            ("vocabulary/check_lyrics.py", ["songs/nu-metal-rap-rock/lyrics.md",
                                            "--template=nu_metal_rap_rock", "--bpm=120"]),
        ]
        for script, args in invocations:
            with self.subTest(script=script, args=args):
                proc = run_cli(script, *args)
                self.assertEqual(proc.returncode, 0, proc.stdout.decode()[-500:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
