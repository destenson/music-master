"""Validate the tag vocabulary.

The vocabulary is a hand-extended data file that three consumers depend on: the UI
builds controls from it, the prompt renderer emits tags from it, and the compliance
battery reads `maps_to` to know what to check. A typo therefore does not fail loudly
at edit time -- it silently changes what gets generated or quietly drops a check. So
it is checked here.

Checks performed, cheapest first:

  1. the file parses and conforms to tag-vocabulary.schema.json (jsonschema, if installed)
  2. bin ids are unique; option ids are unique within a bin
  3. every render_order entry names a bin, and every bin appears in render_order
  4. every bin declares a control, a priority and a maps_to
  5. labels contain no comma, no leading or trailing whitespace, and no double space
  6. every `excludes` / `requires_any` reference resolves to an option in the same bin
  7. selection limits are satisfiable: a bin's default selections do not exceed its max

Exit status is non-zero if any check fails, so this can gate a commit or a CI step.

    python3 vocabulary/validate_vocabulary.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"
SCHEMA_PATH = ROOT / "schemas" / "tag-vocabulary.schema.json"
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
SECTION_SCHEMA_PATH = ROOT / "schemas" / "section-tags.schema.json"

POOLS = ("sections", "modifiers", "vocal_tags", "energy_tags", "instrumental_section_tags")

MULTI_CONTROLS = {"multi_select", "ranked_multi"}
SELECT_CONTROLS = {"single_select", "multi_select", "ranked_multi", "combo_free"}


class Problems:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def check_schema(vocab: dict, p: Problems) -> None:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        p.warn("jsonschema is not installed; skipped schema conformance check")
        return
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(vocab), key=lambda e: list(e.path)):
        location = "/".join(str(x) for x in err.path) or "<root>"
        p.error(f"schema: {location}: {err.message}")


def check_bins(vocab: dict, p: Problems) -> None:
    bins = vocab.get("bins", [])
    render_order = vocab.get("render_order", [])

    seen_bins: set[str] = set()
    bin_ids: list[str] = []
    for b in bins:
        bid = b.get("id", "<missing id>")
        if bid in seen_bins:
            p.error(f"bin id '{bid}' is duplicated")
        seen_bins.add(bid)
        bin_ids.append(bid)

        for field in ("id", "label", "group", "control", "priority", "maps_to"):
            if not b.get(field):
                p.error(f"bin '{bid}': missing required field '{field}'")
        if b.get("control") not in {
            "single_select", "multi_select", "numeric", "numeric_with_descriptor",
            "key_mode", "ranked_multi", "combo_free",
        }:
            p.error(f"bin '{bid}': unknown control '{b.get('control')}'")

        mx = b.get("max_selections")
        mn = b.get("min_selections", 0)
        if mx is not None and mn > mx:
            p.error(f"bin '{bid}': min_selections {mn} exceeds max_selections {mx}")

        if b.get("control") in SELECT_CONTROLS:
            options = b.get("options") or []
            if not options:
                p.error(f"bin '{bid}': control '{b['control']}' needs options")

        if (
            b.get("control") in {"numeric", "numeric_with_descriptor"}
            and b.get("value_emits_tag", True)
            and not b.get("emit")
        ):
            p.error(
                f"bin '{bid}': numeric control with value_emits_tag needs an 'emit' template"
            )

        if b.get("control") == "key_mode":
            if not b.get("key_options") or not b.get("mode_options"):
                p.error(f"bin '{bid}': key_mode needs key_options and mode_options")

    for bin_id in render_order:
        if bin_id not in seen_bins:
            p.error(f"render_order names unknown bin '{bin_id}'")
    for bin_id in bin_ids:
        if bin_id not in render_order:
            b = next(x for x in bins if x.get("id") == bin_id)
            if b.get("emits_tag", True):
                p.warn(f"bin '{bin_id}' emits tags but has no render position")

    dupes = {x for x in render_order if render_order.count(x) > 1}
    for d in dupes:
        p.error(f"render_order lists '{d}' more than once")


def check_bin_options(b: dict, p: Problems) -> None:
    bid = b.get("id", "<missing id>")
    options = b.get("options") or []
    ids = [o.get("id") for o in options]

    dupes = {x for x in ids if ids.count(x) > 1}
    for d in dupes:
        p.error(f"bin '{bid}': option id '{d}' is duplicated")

    id_set = set(ids)
    labels: dict[str, str] = {}
    for o in options:
        oid = o.get("id", "<missing id>")
        label = o.get("label", "")
        where = f"bin '{bid}' option '{oid}'"

        if "," in label:
            p.error(f"{where}: label contains a comma, which would split the tag string: {label!r}")
        if label != label.strip():
            p.error(f"{where}: label has leading or trailing whitespace: {label!r}")
        if "  " in label:
            p.warn(f"{where}: label has a double space: {label!r}")
        if label.endswith("."):
            p.warn(f"{where}: label ends with a period: {label!r}")

        key = label.casefold()
        if key in labels:
            p.error(f"{where}: label duplicates '{labels[key]}' within the same bin: {label!r}")
        labels[key] = oid

        for field in ("excludes", "requires_any"):
            for ref in o.get(field) or []:
                if ref not in id_set:
                    p.error(
                        f"{where}: {field} names '{ref}', which is not an option in bin '{bid}'"
                    )

    # Exclusions must be symmetric, or the UI can select one side and not block the other.
    by_id = {o.get("id"): o for o in options}
    for o in options:
        for ref in o.get("excludes") or []:
            other = by_id.get(ref)
            if other is not None and o.get("id") not in (other.get("excludes") or []):
                p.warn(
                    f"bin '{bid}': exclusion {o.get('id')} -> {ref} is declared one way only "
                    f"(the coherence linter treats exclusions as symmetric regardless)"
                )

    defaults = [o.get("id") for o in options if o.get("default")]
    mx = b.get("max_selections")
    if mx is not None and len(defaults) > mx:
        p.error(f"bin '{bid}': {len(defaults)} defaults exceed max_selections {mx}")


def check_section_tags(p: Problems) -> dict:
    """Validate the lyric metatag vocabulary and its grammar."""
    st = json.loads(SECTION_TAGS_PATH.read_text())

    try:
        import jsonschema  # type: ignore
    except ImportError:
        pass
    else:
        schema = json.loads(SECTION_SCHEMA_PATH.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(st), key=lambda e: list(e.path)):
            location = "/".join(str(x) for x in err.path) or "<root>"
            p.error(f"section-tags schema: {location}: {err.message}")

    if st.get("grammar", {}).get("max_modifiers") != 1:
        p.error("section-tags: max_modifiers should be 1; the model's guide warns against stacking")

    seen: dict[str, str] = {}
    for pool in POOLS:
        labels: dict[str, str] = {}
        for tag in st.get(pool, []):
            tid = tag.get("id", "<missing id>")
            if tid in seen:
                p.error(f"section-tags: id '{tid}' is duplicated (also in {seen[tid]})")
            seen[tid] = pool

            label = tag.get("label", "")
            where = f"section-tags {pool} '{tid}'"
            if label != label.strip():
                p.error(f"{where}: label has leading or trailing whitespace: {label!r}")
            if "," in label or "[" in label or "]" in label:
                p.error(f"{where}: label contains punctuation that is structural in a lyric: {label!r}")
            key = label.casefold()
            if key in labels:
                p.error(f"{where}: label duplicates '{labels[key]}' within {pool}: {label!r}")
            labels[key] = tid

    pool_names = set(POOLS)
    for rule in st.get("consistency", []):
        rid = rule.get("id", "<missing id>")
        if rule.get("section_pool") not in pool_names:
            p.error(f"section-tags consistency '{rid}': unknown section_pool '{rule.get('section_pool')}'")
        if not rule.get("caption_bins"):
            p.error(f"section-tags consistency '{rid}': names no caption bins")

    if not any(t.get("instrumental") for t in st.get("sections", [])):
        p.warn("section-tags: no section is marked instrumental; the instrumental consistency rule cannot fire")

    return st


def main() -> int:
    p = Problems()
    try:
        vocab = json.loads(VOCAB_PATH.read_text())
    except FileNotFoundError:
        print(f"FAIL: {VOCAB_PATH} not found")
        return 2
    except json.JSONDecodeError as exc:
        print(f"FAIL: {VOCAB_PATH} is not valid JSON: {exc}")
        return 2

    check_schema(vocab, p)
    check_bins(vocab, p)
    for b in vocab.get("bins", []):
        if b.get("options"):
            check_bin_options(b, p)

    try:
        section_tags = check_section_tags(p)
    except FileNotFoundError:
        section_tags = {}
        p.warn("section-tags.json not found; skipped lyric metatag validation")
    except json.JSONDecodeError as exc:
        section_tags = {}
        p.error(f"section-tags.json is not valid JSON: {exc}")

    bin_count = len(vocab.get("bins", []))
    option_count = sum(len(b.get("options") or []) for b in vocab.get("bins", []))
    tag_count = sum(len(section_tags.get(pool, [])) for pool in POOLS)

    for w in p.warnings:
        print(f"warn: {w}")
    for e in p.errors:
        print(f"ERROR: {e}")

    print(
        f"\n{bin_count} bins, {option_count} options, tag budget {vocab.get('tag_budget')}"
        f"\n{tag_count} section tags across {len(POOLS)} pools"
    )
    if p.errors:
        print(f"FAILED with {len(p.errors)} error(s) and {len(p.warnings)} warning(s)")
        return 1
    print(f"OK with {len(p.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
