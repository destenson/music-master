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
RHYME_PATH = ROOT / "vocabulary" / "rhyme-schemes.json"
RHYME_SCHEMA_PATH = ROOT / "schemas" / "rhyme-schemes.schema.json"
TEMPLATES_PATH = ROOT / "vocabulary" / "structure-templates.json"
TEMPLATES_SCHEMA_PATH = ROOT / "schemas" / "structure-templates.schema.json"
RATES_PATH = ROOT / "vocabulary" / "delivery-rates.json"
RATES_SCHEMA_PATH = ROOT / "schemas" / "delivery-rates.schema.json"

POOLS = ("sections", "modifiers", "transition_tags", "vocal_tags", "energy_tags",
         "instrumental_section_tags")

# Plausible tempo envelope used to sanity-check a bar plan against a claimed duration.
MIN_TEMPO, MAX_TEMPO = 60.0, 200.0


def _schema_check(path: Path, schema_path: Path, label: str, p: Problems) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        p.warn(f"{path.name} not found; skipped {label} validation")
        return None
    except json.JSONDecodeError as exc:
        p.error(f"{path.name} is not valid JSON: {exc}")
        return None
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return data
    schema = json.loads(schema_path.read_text())
    for err in sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(x) for x in err.path) or "<root>"
        p.error(f"{label} schema: {location}: {err.message}")
    return data


def check_rhyme_schemes(p: Problems) -> set[str]:
    rs = _schema_check(RHYME_PATH, RHYME_SCHEMA_PATH, "rhyme-schemes", p)
    if rs is None:
        return set()
    ids = [s.get("id") for s in rs.get("schemes", [])]
    for dup in {i for i in ids if ids.count(i) > 1}:
        p.error(f"rhyme-schemes: id '{dup}' is duplicated")
    return set(ids)


def check_structure_templates(p: Problems, section_roles: set[str], scheme_ids: set[str],
                              section_tags: dict | None = None) -> dict:
    st = _schema_check(TEMPLATES_PATH, TEMPLATES_SCHEMA_PATH, "structure-templates", p)
    if st is None:
        return {}

    band = st.get("default_syllable_band", [6, 10])
    if len(band) == 2 and band[0] > band[1]:
        p.error(f"structure-templates: syllable band {band} is inverted")

    ids = [t.get("id") for t in st.get("templates", [])]
    for dup in {i for i in ids if ids.count(i) > 1}:
        p.error(f"structure-templates: template id '{dup}' is duplicated")

    for t in st.get("templates", []):
        tid = t.get("id", "<missing id>")
        sections = t.get("sections", [])
        if not sections:
            p.error(f"structure-templates '{tid}': has no sections")
            continue

        for sec in sections:
            role = sec.get("role")
            if role not in section_roles:
                p.error(
                    f"structure-templates '{tid}': role '{role}' is not a section in "
                    f"section-tags.json (expected one of {sorted(section_roles)})"
                )
            scheme = sec.get("rhyme_scheme")
            if scheme is not None and scheme not in scheme_ids:
                p.error(
                    f"structure-templates '{tid}': rhyme_scheme '{scheme}' is not in "
                    f"rhyme-schemes.json"
                )
            if sec.get("lines") and scheme is None:
                p.warn(
                    f"structure-templates '{tid}': section '{role}' has lyrics but no rhyme scheme"
                )
            if scheme is not None and not sec.get("lines"):
                p.warn(
                    f"structure-templates '{tid}': section '{role}' names a rhyme scheme but no lines"
                )

            if section_tags:
                known_transitions = {t["id"] for t in section_tags.get("transition_tags", [])}
                if sec.get("transition_out") and sec["transition_out"] not in known_transitions:
                    p.error(
                        f"structure-templates '{tid}' section '{role}': transition_out names "
                        f"'{sec['transition_out']}', which is not in the transition_tags pool"
                    )
                for field, pool in (("vocals", "vocal_tags"), ("energy_tags", "energy_tags")):
                    known = {t["id"] for t in section_tags.get(pool, [])}
                    for ref in sec.get(field) or []:
                        if ref not in known:
                            p.error(
                                f"structure-templates '{tid}' section '{role}': {field} names "
                                f"'{ref}', which is not in the {pool} pool"
                            )
                budget = section_tags.get("grammar", {}).get("max_tags_per_section", 4)
                total = len(sec.get("vocals") or []) + len(sec.get("energy_tags") or [])
                if total > budget:
                    p.error(
                        f"structure-templates '{tid}' section '{role}': {total} standalone tags "
                        f"exceeds max_tags_per_section {budget}"
                    )
                if sec.get("vocals") and not sec.get("lines"):
                    p.warn(
                        f"structure-templates '{tid}' section '{role}': asks for vocal tags on a "
                        f"section with no lyric lines"
                    )

        if any(s.get("role") == "chorus" for s in sections) and not any(s.get("hook") for s in sections):
            p.warn(f"structure-templates '{tid}': has a chorus but no section marked as the hook")

        energies = [s["energy"] for s in sections if s.get("energy")]
        rng = t.get("duration_range_s") or []
        # A sketch is too short for a dynamic arc to be meaningful, so a flat one is fine there.
        short_form = bool(rng) and rng[-1] < 70
        if energies and max(energies) == min(energies) and not short_form:
            p.warn(f"structure-templates '{tid}': the energy arc is flat")

        total_bars = sum(s.get("bars", 0) for s in sections)
        if len(rng) == 2:
            low = total_bars * 4 * 60 / MAX_TEMPO
            high = total_bars * 4 * 60 / MIN_TEMPO
            if rng[1] < low or rng[0] > high:
                p.error(
                    f"structure-templates '{tid}': {total_bars} bars implies {low:.0f}-{high:.0f}s "
                    f"at {MIN_TEMPO:.0f}-{MAX_TEMPO:.0f} BPM, which does not overlap the claimed "
                    f"duration {rng}"
                )

    return st

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
    for b in bins:
        if b.get("polarity", "positive") == "negative" and b.get("emits_tag", True):
            p.error(
                f"bin '{b.get('id')}': polarity is negative but emits_tag is true; a bin that "
                f"subtracts cannot also add"
            )

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

    # A label that appears in the sections pool and in a tag pool is unparseable: the checker
    # decides section header versus standalone tag by label, so the same string in both places
    # silently turns a transition into a section. Two tag pools sharing a label are merely
    # ambiguous about which pool a standalone tag came from.
    section_labels = {t["label"].casefold() for t in st.get("sections", [])}
    standalone_owner: dict[str, str] = {}
    for pool in POOLS:
        if pool == "sections":
            continue
        for tag in st.get(pool, []):
            lab = tag["label"].casefold()
            if lab in section_labels and pool != "modifiers":
                p.error(
                    f"section-tags: label '{tag['label']}' is in the '{pool}' pool and also in "
                    f"'sections'; the parser cannot tell a section header from a standalone tag"
                )
            if pool != "modifiers" and lab in standalone_owner:
                p.warn(
                    f"section-tags: label '{tag['label']}' appears in both "
                    f"'{standalone_owner[lab]}' and '{pool}'; a standalone tag of that label "
                    f"cannot be attributed to one pool"
                )
            if pool != "modifiers":
                standalone_owner[lab] = pool

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


def check_delivery_rates(p: Problems) -> dict:
    """Validate the delivery profiles that the time budget depends on."""
    rates = _schema_check(RATES_PATH, RATES_SCHEMA_PATH, "delivery-rates", p)
    if rates is None:
        return {}

    ids = [r.get("id") for r in rates.get("profiles", [])]
    for dup in {i for i in ids if ids.count(i) > 1}:
        p.error(f"delivery-rates: profile id '{dup}' is duplicated")
    if rates.get("default") not in ids:
        p.error(f"delivery-rates: default '{rates.get('default')}' is not one of the profiles")

    for r in rates.get("profiles", []):
        rid = r.get("id", "<missing id>")
        band = r.get("band", [])
        if len(band) == 2 and band[0] > band[1]:
            p.error(f"delivery-rates '{rid}': band {band} is inverted")
        comfy, hard = r.get("comfortable_max"), r.get("hard_max")
        if comfy is not None and hard is not None and comfy > hard:
            p.error(
                f"delivery-rates '{rid}': comfortable_max {comfy} exceeds hard_max {hard}, "
                f"so nothing would ever be reported as merely rushed"
            )
        if rid != "instrumental" and not band:
            p.error(f"delivery-rates '{rid}': has no band, so no writing budget could be stated")
        if rid == "instrumental" and (hard or comfy):
            p.warn(f"delivery-rates '{rid}': an instrumental profile with a non-zero rate ceiling")
    return rates


def check_template_budget(p: Problems, templates: dict, rates: dict) -> None:
    """Check that a template's own minimum ask fits the clock.

    A template and a delivery profile can each be internally fine and still disagree: four lines in
    a four-bar section is a normal shape, and so is a 6-syllable minimum per line, but at 200 BPM
    the two together are unsingable. Checked at a nominal 100 BPM because a template declares bars
    rather than a tempo; a warning here means the pairing is tight, not that either file is wrong.
    """
    try:
        from . import timeline as T  # type: ignore
    except ImportError:
        p.warn("timeline.py not importable; skipped the template/time-budget cross-check")
        return

    section_tags = json.loads(SECTION_TAGS_PATH.read_text())
    profile = T.rate_profile(rates, None)
    for t in templates.get("templates", []):
        plan = T.build_timeline(t, 100.0, section_tags, profile, templates)
        for row in plan["rows"]:
            if row["instrumental"] or not row["lines"]:
                continue
            if not row["budget_fits"]:
                p.warn(
                    f"structure-templates '{t['id']}' section '{row['role']}': {row['lines']} lines "
                    f"in {row['bars']} bars needs at least {row['budget_min']} syllables in "
                    f"{row['singable_s']:.1f}s, above the {profile['label']} ceiling of "
                    f"{row['ceiling']}; at 100 BPM this shape and this delivery disagree"
                )


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

    scheme_ids = check_rhyme_schemes(p)
    roles = {s["id"].removeprefix("sec_") for s in section_tags.get("sections", [])}
    templates = check_structure_templates(p, roles, scheme_ids, section_tags)

    # Structural options point at templates; check both directions of that link.
    known_templates = {t["id"] for t in templates.get("templates", [])}
    referenced: set[str] = set()
    for b in vocab.get("bins", []):
        for opt in b.get("options") or []:
            ref = opt.get("template_ref")
            if ref is None:
                continue
            if ref not in known_templates:
                p.error(
                    f"bin '{b['id']}' option '{opt['id']}': template_ref '{ref}' is not a known "
                    f"structure template"
                )
            else:
                referenced.add(ref)
    for missing in sorted(known_templates - referenced):
        p.warn(
            f"structure template '{missing}' is not reachable from any bin option, so no UI "
            f"control selects it"
        )

    bin_count = len(vocab.get("bins", []))
    option_count = sum(len(b.get("options") or []) for b in vocab.get("bins", []))
    tag_count = sum(len(section_tags.get(pool, [])) for pool in POOLS)
    scheme_count = len(scheme_ids)
    template_count = len(templates.get("templates", []))
    rates = check_delivery_rates(p)
    profile_count = len(rates.get("profiles", []))
    if rates:
        check_template_budget(p, templates, rates)

    for w in p.warnings:
        print(f"warn: {w}")
    for e in p.errors:
        print(f"ERROR: {e}")

    print(
        f"\n{bin_count} bins, {option_count} options, tag budget {vocab.get('tag_budget')}"
        f"\n{tag_count} section tags across {len(POOLS)} pools"
        f"\n{scheme_count} rhyme schemes, {template_count} structure templates"
        f"\n{profile_count} delivery profiles"
    )
    if p.errors:
        print(f"FAILED with {len(p.errors)} error(s) and {len(p.warnings)} warning(s)")
        return 1
    print(f"OK with {len(p.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
