"""Check a lyric artifact's metatags, and the mechanical half of caption/lyric consistency.

ACE-Step's tutorial says two things that this script exists to enforce:

  1. Structure tags are the most powerful control in the lyrics, and stacking them is a
     mistake -- the model may sing the tag, and too many instructions confuse it.
  2. Caption and lyrics must tell the same story. The model does not resolve conflicts;
     it degrades.

(1) is mechanical and is checked in full here. (2) is mostly a judgement, so only the part
that is exactly checkable is enforced, and the rest is reported as work for the oracle --
which is the same division the rest of the pipeline uses.

    python3 vocabulary/check_lyrics.py vocabulary/examples/lyrics-late-night-trap.md
    python3 vocabulary/check_lyrics.py --self-test
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"
CLICHES_PATH = ROOT / "vocabulary" / "lyric-cliches.json"

TAG_RE = re.compile(r"\[([^\[\]]+)\]")

# --- Approximate prosody. ---------------------------------------------------------------
# These are spelling-based heuristics, not phonology. They are good enough to catch a line
# that is wildly outside the band and to spot an obvious rhyme scheme, and they are
# systematically wrong in two places worth knowing: true vowel quality (through/queue rhyme
# but share no spelling) and any word whose pronunciation the spelling does not imply. The
# design's real answer is a pronunciation lexicon (cmudict-class); until that is a dependency,
# every number here is labelled approximate and should gate nothing hard.
VOWEL_DIGRAPHS = [
    ("ough", "O"), ("igh", "I"), ("ee", "E"), ("ea", "E"), ("ie", "E"), ("ei", "E"),
    ("ai", "A"), ("ay", "A"), ("ey", "A"), ("oo", "O"), ("ou", "O"), ("ow", "O"),
    ("oa", "O"), ("oy", "Y"), ("oi", "Y"), ("au", "A"), ("aw", "A"),
]

SYLLABLE_BAND = (6, 10)
POSITIONAL_TOLERANCE = 2


def split_tokens(line: str) -> list[str]:
    """Split a line into words, keeping CamelCase and acronyms together but countable.

    'KSampler' -> ['K', 'Sampler'], 'ComfyUI' -> ['Comfy', 'UI'], 'VAE' -> ['VAE'].
    Without this, every piece of technical jargon is undercounted.
    """
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z']*", line):
        parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z']*|[a-z']+", raw)
        tokens.extend(parts or [raw])
    return tokens


def syllables(word: str) -> int:
    if word.isupper() and 1 <= len(word) <= 4:
        return len(word)  # VAE, CFG, UI: said letter by letter
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(1, n)


def line_syllables(line: str) -> int:
    """Syllables in a lyric line. Parenthesised asides are backing vocals, not the lead line."""
    bare = re.sub(r"\([^)]*\)", " ", line)
    return sum(syllables(t) for t in split_tokens(bare))


def rhyme_key(word: str) -> str:
    """A rough rhyme key: normalised final vowel group plus trailing consonants."""
    w = word.lower()
    for src, dst in VOWEL_DIGRAPHS:
        w = w.replace(src, dst)
    m = re.search(r"[aeiouyEAIYO]+[^aeiouyEAIYO]*$", w)
    return (m.group(0) if m else w[-2:]).lower()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.oracle_tasks: list[str] = []

    def error(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)

    def oracle(self, m: str) -> None:
        self.oracle_tasks.append(m)


def build_index(st: dict) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    sections = {t["label"].casefold(): t for t in st["sections"]}
    modifiers = {t["label"].casefold(): t for t in st["modifiers"]}
    pools = {
        "vocal_tags": {t["label"].casefold(): t for t in st["vocal_tags"]},
        "energy_tags": {t["label"].casefold(): t for t in st["energy_tags"]},
        "instrumental_section_tags": {t["label"].casefold(): t for t in st["instrumental_section_tags"]},
    }
    return sections, modifiers, pools


def split_tag(body: str) -> tuple[str, str | None]:
    """Split '[Chorus - anthemic]' into ('chorus', 'anthemic')."""
    parts = [p.strip() for p in body.split(" - ")]
    head = parts[0]
    modifier = " - ".join(parts[1:]) if len(parts) > 1 else None
    return head, modifier


def strip_index(head: str) -> str:
    return re.sub(r"\s+\d+$", "", head).strip()


def analyse(lines: list[str], st: dict, rep: Report) -> list[dict]:
    sections, modifiers, pools = build_index(st)
    all_pool_labels = {k: set(v) for k, v in pools.items()}
    found: list[dict] = []

    for lineno, line in enumerate(lines, start=1):
        for match in TAG_RE.finditer(line):
            body = match.group(1)
            head, modifier = split_tag(body)
            base = strip_index(head).casefold()
            entry: dict = {"line": lineno, "raw": body, "section": None, "modifier": modifier}

            if any(sep in body for sep in (",", ";")):
                rep.error(f"line {lineno}: tag '[{body}]' contains punctuation; tags are hyphenated, not listed")

            parts_count = len([p for p in body.split(" - ")])
            if parts_count - 1 > st["grammar"]["max_modifiers"]:
                rep.error(
                    f"line {lineno}: tag '[{body}]' stacks {parts_count - 1} modifiers; "
                    f"the maximum is {st['grammar']['max_modifiers']}"
                )

            in_any_pool = False
            for pool_name, labels in all_pool_labels.items():
                if base in labels:
                    in_any_pool = True
                    entry["pool"] = pool_name
                    if pool_name == "instrumental_section_tags" and modifier:
                        rep.warn(
                            f"line {lineno}: instrumental tag '[{body}]' takes no modifier"
                        )

            if base in sections:
                entry["section"] = sections[base]["id"]
                if modifier is not None and modifier.casefold() not in modifiers:
                    rep.error(
                        f"line {lineno}: modifier '{modifier}' in '[{body}]' is not in the "
                        f"modifier vocabulary"
                    )
                if modifier is None and base == "solo":
                    rep.warn(
                        f"line {lineno}: '[Solo]' should name its instrument, e.g. '[Solo - guitar]'"
                    )
                if "numbered" not in sections[base] and re.search(r"\s+\d+$", head):
                    rep.warn(f"line {lineno}: '[{body}]' is indexed but this section takes no index")
            elif not in_any_pool:
                rep.error(
                    f"line {lineno}: unknown tag '[{body}]'. An unrecognised tag may be sung "
                    f"as a lyric; add it to section-tags.json or remove it"
                )
            found.append(entry)

    return found


def check_blank_lines(lines: list[str], rep: Report) -> None:
    """Every section tag should start a block, i.e. be preceded by a blank line."""
    for i, line in enumerate(lines):
        if TAG_RE.search(line) and i > 0 and lines[i - 1].strip() != "":
            rep.warn(f"line {i + 1}: section tag is not preceded by a blank line")


def check_consistency(found: list[dict], st: dict, vocab: dict, selections: dict, rep: Report) -> None:
    """Enforce the mechanical consistency rule; hand the rest to the oracle."""
    pools = {t["label"].casefold(): t for t in st["vocal_tags"]}

    for section in found:
        if section.get("section") is None:
            continue
        sid = section["section"]
        meta = next((s for s in st["sections"] if s["id"] == sid), None)
        if meta and meta.get("instrumental"):
            rep.oracle(
                f"line {section['line']}: caption instrumentation vs instrumental section "
                f"'[{section['raw']}]' -- semantic, needs the oracle"
            )

    # Rule 4 is exactly checkable: no vocal tag when the lead vocal is Instrumental/No Vocals.
    lead = (selections.get("lead_vocal") or {}).get("options") or []
    instrumental = bool({"instrumental", "no_vocals"} & set(lead))
    if instrumental:
        for entry in found:
            if entry.get("pool") == "vocal_tags":
                rep.error(
                    f"line {entry['line']}: '[{entry['raw']}]' is a vocal tag, but the caption's "
                    f"lead vocal is Instrumental/No Vocals"
                )

    for rule in st["consistency"]:
        bins_present = [b for b in rule["caption_bins"] if selections.get(b)]
        if bins_present:
            rep.oracle(
                f"consistency rule '{rule['id']}': compare caption bins {bins_present} against "
                f"{rule['section_pool']} tags in the lyrics"
            )

    if not selections:
        rep.warn("no caption selections supplied; consistency rules not evaluated")


def check_cliches(lines: list[str], rep: Report) -> None:
    """Soft lexical gate. Warnings only: cliche is a judgement, and the oracle scores it."""
    if not CLICHES_PATH.exists():
        return
    cl = load(CLICHES_PATH)
    lyric_lines = [(i, l) for i, l in enumerate(lines, start=1) if not TAG_RE.search(l)]

    for lineno, line in lyric_lines:
        low = line.casefold()
        for phrase in cl["phrases"]:
            if phrase in low:
                rep.warn(f"line {lineno}: stock phrase '{phrase}'")
        for noun in cl["overused_nouns"]:
            if re.search(rf"\b{re.escape(noun)}\b", low):
                rep.warn(f"line {lineno}: overused noun '{noun}'")
        for motif in cl["overused_motifs"]:
            if motif in low:
                rep.warn(f"line {lineno}: overused motif '{motif}'")

    # A rhyme pair is only a cliche when both words are actually used as line endings.
    endings: list[tuple[int, str]] = []
    for lineno, line in lyric_lines:
        words = re.findall(r"[a-z']+", line.casefold())
        if words:
            endings.append((lineno, words[-1]))
    for a, b in cl["overused_rhyme_pairs"]:
        where_a = [n for n, w in endings if w == a]
        where_b = [n for n, w in endings if w == b]
        if where_a and where_b:
            rep.warn(
                f"lines {where_a} and {where_b}: overused rhyme pair '{a}'/'{b}'"
            )


def check_meter_and_rhyme(lines: list[str], st: dict, rep: Report) -> dict:
    """Approximate syllable and rhyme check, per section.

    The model's own guidance: 6-10 syllables per line, and lines in the same position across
    sections should agree within +-1-2, because it aligns syllables to beats.
    """
    sections: list[dict] = []
    current: dict | None = None
    for lineno, line in enumerate(lines, start=1):
        if TAG_RE.search(line):
            body = TAG_RE.search(line).group(1)
            head = strip_index(split_tag(body)[0])
            current = {"tag": body, "name": head, "lines": []}
            sections.append(current)
            continue
        if current is None or not line.strip():
            continue
        words = split_tokens(re.sub(r"\([^)]*\)", " ", line))
        n = line_syllables(line)
        current["lines"].append((lineno, n, line, words))

    summary: dict = {"sections": [], "out_of_band": 0}

    for sec in sections:
        counts = [n for _, n, _, _ in sec["lines"]]
        if not counts:
            continue
        endings = [w[-1] for _, _, _, w in sec["lines"] if w]
        keys = [rhyme_key(w) for w in endings]
        symbols: list[str] = []
        for k in keys:
            if k in [rhyme_key(e) for e in endings[: len(symbols)]]:
                symbols.append(symbols[[rhyme_key(e) for e in endings[: len(symbols)]].index(k)])
            else:
                symbols.append(chr(ord("A") + len(set(symbols)) % 26))
        scheme = "".join(symbols)
        summary["sections"].append(
            {"tag": sec["tag"], "counts": counts, "scheme": scheme,
             "min": min(counts), "max": max(counts)}
        )

        for lineno, n, line, _ in sec["lines"]:
            lo, hi = SYLLABLE_BAND
            if n < lo or n > hi:
                summary["out_of_band"] += 1
                rep.warn(
                    f"line {lineno}: {n} syllables, outside the {lo}-{hi} band "
                    f"(approximate count) -- {line.strip()[:44]}"
                )

    # Positional variance: compare the Nth line across sections that share a name.
    by_name: dict[str, list[list[int]]] = {}
    for sec in sections:
        if sec["lines"]:
            by_name.setdefault(sec["name"], []).append([n for _, n, _, _ in sec["lines"]])
    for name, runs in by_name.items():
        if len(runs) < 2:
            continue
        positions = min(len(r) for r in runs)
        for i in range(positions):
            values = [r[i] for r in runs]
            if max(values) - min(values) > POSITIONAL_TOLERANCE:
                rep.warn(
                    f"position {i + 1} of [{name}]: lines differ by "
                    f"{max(values) - min(values)} syllables across sections {values}; "
                    f"the tolerance is {POSITIONAL_TOLERANCE}"
                )
    return summary


def run_self_test() -> int:
    st = load(SECTION_TAGS_PATH)
    vocab = load(VOCAB_PATH)
    broken = [
        "[Chorus - anthemic - stacked harmonies - high energy]",
        "",
        "[Guitar solo - electric - distorted]",
        "",
        "[Prechorus]",
        "",
        "[Instrumental]",
        "[whispered]",
    ]
    rep = Report()
    found = analyse(broken, st, rep)
    check_consistency(found, st, vocab, {"lead_vocal": {"options": ["instrumental"]}}, rep)

    expected_error_fragments = ["stacks 3 modifiers", "unknown tag", "not in the modifier vocabulary",
                                "vocal tag"]
    joined = " | ".join(rep.errors)
    missing = [f for f in expected_error_fragments if f not in joined]
    print("self-test on a deliberately broken lyric:")
    for e in rep.errors:
        print(f"  ERROR: {e}")
    for w in rep.warnings:
        print(f"  warn:  {w}")
    if missing:
        print(f"\nself-test FAILED: did not detect {missing}")
        return 1

    # Second fixture: a line far outside the syllable band must be caught.
    long_line = [
        "[Verse 1]",
        "I am singing an unnecessarily long and rambling line about a broken wire tonight",
    ]
    rep2 = Report()
    meter = check_meter_and_rhyme(long_line, st, rep2)
    band_warning = any("outside the" in w for w in rep2.warnings)
    print("\nself-test on an over-long line:")
    print(f"  counted {meter['sections'][0]['counts']} syllables; band warning raised: {band_warning}")
    if not band_warning:
        print("\nself-test FAILED: the syllable band check did not fire")
        return 1

    print("\nself-test passed: the checker catches stacking, unknown tags, bad modifiers, vocal tags in instrumentals, and over-long lines")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return run_self_test()
    if len(argv) < 2:
        print(__doc__)
        return 2

    st = load(SECTION_TAGS_PATH)
    vocab = load(VOCAB_PATH)
    path = Path(argv[1])
    lines = path.read_text().splitlines()

    selections: dict = {}
    for arg in argv[2:]:
        if arg.startswith("--selections="):
            selections = json.loads(Path(arg.split("=", 1)[1]).read_text()).get("selections", {})

    rep = Report()
    found = analyse(lines, st, rep)
    check_blank_lines(lines, rep)
    check_consistency(found, st, vocab, selections, rep)
    check_cliches(lines, rep)
    meter = check_meter_and_rhyme(lines, st, rep)

    section_count = sum(1 for f in found if f.get("section"))
    print(f"{path.name}: {len(lines)} lines, {len(found)} tags ({section_count} sections)")

    if meter["sections"]:
        print("\n  section                    syllables            rhyme")
        for s in meter["sections"]:
            counts = ",".join(str(c) for c in s["counts"])
            print(f"  {s['tag'][:24]:<26}{counts:<21}{s['scheme']}")
        print("  (syllable and rhyme figures are approximate: spelling-based, no lexicon)\n")
    for w in rep.warnings:
        print(f"warn:  {w}")
    for e in rep.errors:
        print(f"ERROR: {e}")
    for t in rep.oracle_tasks:
        print(f"oracle: {t}")

    if rep.errors:
        print(f"\nFAILED with {len(rep.errors)} error(s)")
        return 1
    print(f"\nOK; {len(rep.oracle_tasks)} consistency check(s) deferred to the oracle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
