"""Render bin selections into a comma-separated tag string.

This is the reference implementation of the render rules in
docs/design/tag-vocabulary.md. It exists to prove the design against the motivating
example and to pin the rules that make rendering reproducible:

  * canonical order, taken from render_order, never from selection order
  * labels emitted verbatim; selections stored by id
  * numeric bins rendered through their `emit` template
  * bins with emits_tag = false contribute nothing to the positive string
  * a tag budget, enforced by priority, with everything dropped recorded rather than
    silently discarded
  * duplicate labels collapsed

It also runs a small coherence pass -- unknown option ids, exceeded selection limits,
and exclusions -- because those are the failures a UI should have prevented and a
non-UI caller can still produce.

    python3 vocabulary/render_tags.py vocabulary/examples/late-night-trap.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"


def load_vocabulary(path: Path = VOCAB_PATH) -> dict:
    return json.loads(path.read_text())


def coherence_check(vocab: dict, selections: dict) -> list[str]:
    """Return human-readable problems with a selection set. Empty means coherent."""
    problems: list[str] = []
    bins = {b["id"]: b for b in vocab["bins"]}

    for bin_id, sel in selections.items():
        b = bins.get(bin_id)
        if b is None:
            problems.append(f"unknown bin '{bin_id}'")
            continue
        chosen = sel.get("options") or []
        known = {o["id"] for o in (b.get("options") or [])}
        for oid in chosen:
            if oid not in known:
                problems.append(f"bin '{bin_id}': unknown option '{oid}'")
        mx = b.get("max_selections")
        if mx is not None and len(chosen) > mx:
            problems.append(
                f"bin '{bin_id}': {len(chosen)} selections exceed the maximum of {mx}"
            )

    # Exclusions are treated as symmetric even when declared one way only.
    selected = {
        (bin_id, oid)
        for bin_id, sel in selections.items()
        for oid in (sel.get("options") or [])
    }
    for bin_id, oid in selected:
        b = bins.get(bin_id, {})
        opt = next((o for o in (b.get("options") or []) if o["id"] == oid), None)
        if opt is None:
            continue
        for excluded in opt.get("excludes") or []:
            if (bin_id, excluded) in selected:
                problems.append(
                    f"bin '{bin_id}': '{oid}' excludes '{excluded}', but both are selected"
                )
        for other_bin, other_id in selected:
            if other_bin != bin_id:
                continue
            other = next(
                (o for o in (b.get("options") or []) if o["id"] == other_id), None
            )
            if other and oid in (other.get("excludes") or []):
                problems.append(
                    f"bin '{bin_id}': '{oid}' and '{other_id}' exclude each other, but both are selected"
                )
    return problems


def collect_tags(vocab: dict, selections: dict) -> list[tuple[int, int, str]]:
    """Return (priority, render_index, label) for every selected tag, in render order."""
    bins = {b["id"]: b for b in vocab["bins"]}
    out: list[tuple[int, int, str]] = []

    for index, bin_id in enumerate(vocab["render_order"]):
        b = bins.get(bin_id)
        if b is None or not b.get("emits_tag", True):
            continue
        sel = selections.get(bin_id)
        if not sel:
            continue
        priority = b.get("priority", 2)

        for oid in sel.get("options") or []:
            opt = next((o for o in (b.get("options") or []) if o["id"] == oid), None)
            if opt is not None:
                out.append((priority, index, opt["label"]))

        value = sel.get("value")
        if value is not None and b.get("value_emits_tag", True) and b.get("emit"):
            out.append((priority, index, b["emit"].format(value=value)))

        if b.get("control") == "key_mode":
            key, mode = sel.get("key"), sel.get("mode")
            if key and mode:
                out.append((priority, index, f"{key} {mode}"))

        text = sel.get("text")
        if text:
            out.append((priority, index, text))

    return out


def collect_negatives(vocab: dict, selections: dict) -> list[str]:
    """Labels from negative-polarity bins: exclusions, never tags."""
    out: list[str] = []
    for b in vocab["bins"]:
        if b.get("polarity", "positive") != "negative":
            continue
        sel = selections.get(b["id"])
        if not sel:
            continue
        for oid in sel.get("options") or []:
            opt = next((o for o in (b.get("options") or []) if o["id"] == oid), None)
            if opt:
                out.append(opt["label"])
    return out


def render(vocab: dict, selections: dict) -> dict:
    tags = collect_tags(vocab, selections)

    # Collapse duplicate labels, keeping the first occurrence in render order.
    seen: set[str] = set()
    unique: list[tuple[int, int, str]] = []
    for priority, index, label in tags:
        if label not in seen:
            seen.add(label)
            unique.append((priority, index, label))

    budget = vocab.get("tag_budget", 10**9)
    if len(unique) > budget:
        # Keep the most defining tags first; ties broken by render order. Rank by position, not by
        # the (priority, index) pair: several options in one bin share that pair, so using it as a
        # key kept whole bins and overran the budget.
        ranked = sorted(range(len(unique)), key=lambda k: (unique[k][0], unique[k][1]))
        keep = set(ranked[:budget])
        kept = [tag for k, tag in enumerate(unique) if k in keep]
        omitted = [label for k, (_, _, label) in enumerate(unique) if k not in keep]
    else:
        kept, omitted = unique, []

    kept.sort(key=lambda t: t[1])
    rendered = [label for _, _, label in kept]
    return {
        "tags": rendered,
        "string": ", ".join(rendered),
        "omitted": omitted,
        "negatives": collect_negatives(vocab, selections),
    }


def main(argv: list[str]) -> int:
    vocab = load_vocabulary()
    if len(argv) > 1:
        payload = json.loads(Path(argv[1]).read_text())
        selections = payload.get("selections", {})
        expected_tags = payload.get("rendered_tags")
        expected_str = payload.get("rendered_string")
    else:
        selections, expected_tags, expected_str = {}, None, None

    problems = coherence_check(vocab, selections)
    for p in problems:
        print(f"coherence: {p}")

    result = render(vocab, selections)
    print(f"\ntags ({len(result['tags'])}):")
    for t in result["tags"]:
        print(f"  {t}")
    print(f"\nstring:\n  {result['string']}")
    if result["omitted"]:
        print(f"\nomitted over budget: {result['omitted']}")

    if expected_tags is not None:
        if result["tags"] == expected_tags and result["string"] == expected_str:
            print("\nmatches the fixture")
            return 0 if not problems else 1
        print("\nDOES NOT MATCH the fixture")
        print(f"  expected {len(expected_tags)} tags: {expected_tags}")
        print(f"  got      {len(result['tags'])} tags: {result['tags']}")
        return 1
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
