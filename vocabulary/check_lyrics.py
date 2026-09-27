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

import difflib
import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"
CLICHES_PATH = ROOT / "vocabulary" / "lyric-cliches.json"
TEMPLATES_PATH = ROOT / "vocabulary" / "structure-templates.json"
RHYME_PATH = ROOT / "vocabulary" / "rhyme-schemes.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import timeline as T  # noqa: E402
except ImportError:  # the checker still works without the time budget
    T = None  # type: ignore[assignment]

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
    """A rough rhyme key: normalised final vowel group plus trailing consonants.

    A silent final 'e' carries no rhyme, so it is dropped first: without that, 'insane', 'image'
    and 'node' all key on a bare 'e' and match each other, which floods the internal-rhyme count
    with false pairs.
    """
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    if len(w) > 2 and w.endswith("e") and not w.endswith(("le", "ee", "ye", "oe")):
        w = w[:-1]
    for src, dst in VOWEL_DIGRAPHS:
        w = w.replace(src, dst)
    m = re.search(r"[aeiouyEAIYO]+[^aeiouyEAIYO]*$", w)
    key = m.group(0) if m else w[-2:]
    if len(key) < 2:
        # A one-character key matches almost anything; anchor it with the preceding consonant.
        i = w.rfind(key)
        key = (w[i - 1] if i > 0 else "") + key
    return key.lower()


# --- Phrasing and sound devices. --------------------------------------------------------
# A written line is not the unit that meets the music. Cadence splits lines in the middle, and
# a line with no internal punctuation is one long phrase however it is printed. So the phrase --
# not the line -- is what gets compared against the syllable band, and the devices that carry
# skilled lyric writing (internal rhyme, alliteration) are counted separately from the end-rhyme
# scheme rather than being invisible to it.
#
# Breaks are taken from an explicit caesura marker, which is never sung, or inferred from
# punctuation. `/` and `|` are the explicit forms; commas, semicolons, colons and dashes are
# inferred weak breaks.
PHRASE_BREAK_RE = re.compile(r"\s*(?:[,;:]|—|–|\s/\s|\s\|\s)\s*")

# Words that carry no stress of their own; excluded so "the ... the" is not read as alliteration.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for",
    "with", "from", "is", "are", "was", "were", "be", "been", "am", "it", "its", "this",
    "that", "these", "those", "i", "im", "you", "your", "we", "us", "my", "me", "he", "she",
    "they", "them", "his", "her", "as", "so", "do", "does", "did", "not", "no", "yeah", "oh",
    "up", "out", "down", "just", "still", "than", "then", "there", "here",
}


def bare_line(line: str) -> str:
    """A line with parenthesised backing vocals removed: they are a different voice."""
    return re.sub(r"\([^)]*\)", " ", line)


def segment_phrases(line: str) -> list[str]:
    parts = [p.strip() for p in PHRASE_BREAK_RE.split(bare_line(line))]
    return [p for p in parts if re.search(r"[A-Za-z]", p)]


def phrase_syllables(line: str) -> list[int]:
    return [line_syllables(p) for p in segment_phrases(line)]


def onset(word: str) -> str:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    m = re.match(r"^[^aeiouy]+", w)
    return m.group(0) if m else w[0]


def alliteration_groups(line: str) -> dict[str, list[str]]:
    """Repeated onsets among stressed (non-stopword) words in one line."""
    groups: dict[str, list[str]] = {}
    for w in split_tokens(bare_line(line)):
        if w.lower() in STOPWORDS:
            continue
        o = onset(w)
        if o:
            groups.setdefault(o, []).append(w)
    return {o: ws for o, ws in groups.items() if len(ws) >= 2}


def rhyme_pairs(words: list[str]) -> list[tuple[str, str]]:
    """Pairs of stressed words in the same line that rhyme.

    Identical words are repetition rather than rhyme, and function words are excluded because a
    rhyme between two of them is not a device anyone chose.
    """
    content = [w for w in words if w.lower() not in STOPWORDS]
    out: list[tuple[str, str]] = []
    for i in range(len(content)):
        for j in range(i + 1, len(content)):
            a, b = content[i].lower(), content[j].lower()
            if a != b and rhyme_key(content[i]) == rhyme_key(content[j]):
                out.append((content[i], content[j]))
    return out


def reduced_vowel_note() -> str:
    """Why cross-line embedded rhyme is deliberately not reported."""
    return (
        "cross-line embedded rhyme is not reported: whether two syllables rhyme depends on "
        "stress and vowel length, which spelling does not encode. 'open'/'screen' and "
        "'hit'/'right' both look like rhymes to this detector and are not. A pronunciation "
        "lexicon is required before that number would mean anything."
    )


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
        "transition_tags": {t["label"].casefold(): t for t in st.get("transition_tags", [])},
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


def section_lookup(st: dict) -> dict[str, dict]:
    return {s["label"].casefold(): s for s in st["sections"]}


def is_section_header(st: dict, body: str) -> bool:
    """A bracket is a section header, not a standalone performance tag."""
    head, _ = split_tag(body)
    return strip_index(head).casefold() in section_lookup(st)


def analyse(lines: list[str], st: dict, rep: Report) -> list[dict]:
    """Walk the lyric and collect sections, their hyphenated modifier, and their standalone tags.

    The guide presents three kinds of inline tag, and they behave differently: a section header
    starts a section, a hyphenated modifier belongs to that header, and a standalone performance
    tag -- [rap], [powerful belting], [building energy] -- applies from where it sits until the
    next header. Treating the third as a section header would both invent sections that the
    template never declared and detach the lyric lines that follow from the section they belong to.
    """
    sections, modifiers, pools = build_index(st)
    all_pool_labels = {k: set(v) for k, v in pools.items()}
    max_standalone = st["grammar"].get("max_tags_per_section", 3)
    found: list[dict] = []
    current: dict | None = None

    for lineno, line in enumerate(lines, start=1):
        for match in TAG_RE.finditer(line):
            body = match.group(1)
            head, modifier = split_tag(body)
            base = strip_index(head).casefold()

            if any(sep in body for sep in (",", ";")):
                rep.error(f"line {lineno}: tag '[{body}]' contains punctuation; tags are hyphenated, not listed")

            parts_count = len([p for p in body.split(" - ")])
            if parts_count - 1 > st["grammar"]["max_modifiers"]:
                rep.error(
                    f"line {lineno}: tag '[{body}]' stacks {parts_count - 1} modifiers; "
                    f"the maximum is {st['grammar']['max_modifiers']}"
                )

            if base in sections:
                entry = {"line": lineno, "raw": body, "section": sections[base]["id"],
                         "modifier": modifier, "standalone": [], "transitions": []}
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
                current = entry
                found.append(entry)
                continue

            # Not a section header: it must be a standalone performance tag.
            pool = next((p for p, labels in all_pool_labels.items() if base in labels), None)
            if pool is None:
                rep.error(
                    f"line {lineno}: unknown tag '[{body}]'. An unrecognised tag may be sung "
                    f"as a lyric; add it to section-tags.json or remove it"
                )
                continue
            if pool == "instrumental_section_tags" and modifier:
                rep.warn(f"line {lineno}: instrumental tag '[{body}]' takes no modifier")
            if current is None:
                rep.warn(f"line {lineno}: '[{body}]' appears before any section header, so it "
                         f"governs nothing")
                continue
            if pool == "transition_tags":
                current.setdefault("transitions", []).append(
                    {"line": lineno, "raw": body, "pool": pool}
                )
                limit = st["grammar"].get("max_transitions_per_section", 1)
                if len(current["transitions"]) > limit:
                    rep.error(
                        f"line {lineno}: [{current['raw']}] declares "
                        f"{len(current['transitions'])} transitions; a section leaves one way, "
                        f"and the maximum is {limit}"
                    )
                continue
            current["standalone"].append({"line": lineno, "raw": body, "pool": pool})
            if len(current["standalone"]) > max_standalone:
                rep.error(
                    f"line {lineno}: [{current['raw']}] carries "
                    f"{len(current['standalone'])} performance tags; the maximum is {max_standalone}"
                )

    return found


def check_blank_lines(lines: list[str], st: dict, rep: Report) -> None:
    """Every section header should start a block, i.e. be preceded by a blank line.

    Only section headers: a standalone performance tag is *meant* to sit directly under its header.
    """
    for i, line in enumerate(lines):
        match = TAG_RE.search(line)
        if not match or not is_section_header(st, match.group(1)):
            continue
        if i > 0 and lines[i - 1].strip() != "":
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
        for sec in found:
            for tag in sec.get("standalone", []):
                if tag["pool"] == "vocal_tags":
                    rep.error(
                        f"line {tag['line']}: '[{tag['raw']}]' is a vocal tag, but the caption's "
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


def check_meter_and_rhyme(lines: list[str], st: dict, rep: Report,
                          band: tuple[int, int] | None = None) -> dict:
    """Approximate syllable and rhyme check, per section.

    The band is 6-10 syllables per line for a mid-tempo sung delivery, but it moves with the
    delivery: a rapped line carries far more, so the band is passed in from the delivery profile
    when one is known rather than assumed. Using the sung band on a rap verse reports every line as
    too long, which is a false alarm rather than a finding.
    """
    lo, hi = band or SYLLABLE_BAND
    sections: list[dict] = []
    current: dict | None = None
    index = build_index(st)[0]
    transition_labels = {t["label"].casefold() for t in st.get("transition_tags", [])}
    for lineno, line in enumerate(lines, start=1):
        match = TAG_RE.search(line)
        if match:
            body = match.group(1)
            if not is_section_header(st, body):
                # A standalone tag: a transition belongs to the section it leaves, the rest are
                # performance tags on the section itself.
                if current is not None:
                    key = "transitions" if body.casefold() in transition_labels else "standalone"
                    current.setdefault(key, []).append({"line": lineno, "raw": body})
                continue
            head = strip_index(split_tag(body)[0])
            current = {"tag": body, "name": head, "lines": [], "standalone": [], "transitions": [],
                       "modifier": split_tag(body)[1],
                       "role": index.get(head.casefold(), {}).get("id", "").removeprefix("sec_")}
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
            # A tagged section with no lines is an instrumental one. It must still be reported, or
            # the alignment cannot match it and the template's instrumental rows look missing.
            summary["sections"].append(
                {"tag": sec["tag"], "role": sec.get("role", ""), "counts": [], "scheme": "",
                 "phrases": [], "internal": 0, "allit": 0, "min": None, "max": None,
                 "standalone": sec.get("standalone", []),
                 "transitions": sec.get("transitions", []),
                 "modifier": sec.get("modifier")}
            )
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

        phrases = [phrase_syllables(line) for _, _, line, _ in sec["lines"]]
        internal = 0
        allit = 0
        for _, _, line, _ in sec["lines"]:
            internal += len(rhyme_pairs(split_tokens(bare_line(line))))
            allit += len(alliteration_groups(line))
        summary["sections"].append(
            {"tag": sec["tag"], "role": sec.get("role", ""), "counts": counts,
             "scheme": scheme, "min": min(counts), "max": max(counts),
             "phrases": phrases, "internal": internal, "allit": allit,
             "standalone": sec.get("standalone", []),
             "transitions": sec.get("transitions", []),
             "modifier": sec.get("modifier")}
        )

        # The band applies to the phrase, not the printed line: cadence is what meets the beat.
        for (lineno, n, line, _), line_phrases in zip(sec["lines"], phrases):
            for p in line_phrases:
                if p > hi:
                    summary["out_of_band"] += 1
                    rep.warn(
                        f"line {lineno}: a phrase of {p} syllables exceeds the {hi} comfortable "
                        f"maximum (approximate) -- {line.strip()[:44]}"
                    )
            if n > 2 * hi:
                summary["out_of_band"] += 1
                rep.warn(
                    f"line {lineno}: {n} syllables with no internal break; that is a long way to "
                    f"sing in one breath (approximate)"
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
    summary["enjambed"] = 0
    return summary


def check_template(meter: dict, st: dict, template: dict, rep: Report,
                   plan: dict | None = None) -> dict:
    """Verify a lyric against a structure template, and against the clock.

    The template is a contract: section sequence, lines per section, and the rhyme scheme each
    section was written to. Sequence and line count are exact. Rhyme conformance is reported as a
    ratio and weighted by the scheme's own strictness, because the detector is spelling-based.

    When a ``plan`` from timeline.build_timeline is supplied, each matched section is also checked
    against its time budget: how many syllables fit, and whether any were written into a section
    that carries no vocal at all. Alignment is by position in the template, so three identical
    choruses are checked individually rather than collapsed by label.
    """
    schemes = {s["id"]: s for s in load(RHYME_PATH)["schemes"]}
    actual = meter["sections"]
    expected = template["sections"]
    result: dict = {"matched": [], "missing": [], "extra": [], "findings": []}

    # Align expected against actual with an LCS, so repeated sections line up and a skipped
    # optional section does not cascade into a false mismatch for everything after it.
    exp_roles = [s["role"] for s in expected]
    act_roles = [s.get("role") or "" for s in actual]
    matcher = difflib.SequenceMatcher(a=exp_roles, b=act_roles, autojunk=False)
    covered_exp: set[int] = set()
    covered_act: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            pairs.append((block.a + k, block.b + k))
            covered_exp.add(block.a + k)
            covered_act.add(block.b + k)
    pairs.sort()

    for i, exp in enumerate(expected):
        if i in covered_exp:
            continue
        if exp.get("optional"):
            result["findings"].append(f"optional section '{exp['role']}' is absent")
        else:
            result["missing"].append(exp["role"])
    result["extra"] = [act_roles[i] for i in range(len(actual)) if i not in covered_act]

    for role in result["missing"]:
        rep.error(f"template '{template['id']}': expected section '{role}' is missing")
    for role in result["extra"]:
        rep.warn(f"template '{template['id']}': unexpected section '{role}'")

    for ei, ai in pairs:
        exp, act = expected[ei], actual[ai]
        result["matched"].append((exp, act))
        if exp.get("lines") and len(act["counts"]) != exp["lines"]:
            rep.warn(
                f"[{act['tag']}]: {len(act['counts'])} lines, template expects {exp['lines']}"
            )

        # Performance tags the template asks for: present or not.
        if plan is not None and ei < len(plan["rows"]):
            row = plan["rows"][ei]
            wanted_ids = list(row.get("vocals") or []) + list(row.get("energy_tags") or [])
            if wanted_ids:
                labels = T.tag_label_map(st) if T is not None else {}
                present = [t["raw"].casefold() for t in act.get("standalone", [])]
                # A hyphenated modifier and a standalone tag of the same label are the same
                # instruction, so either satisfies the template's ask.
                if act.get("modifier"):
                    present.append(act["modifier"].casefold())
                wanted = [labels.get(i, i) for i in wanted_ids]
                missing = [w for w in wanted if w.casefold() not in present]
                act["vocals_expected"] = wanted
                act["vocals_present"] = [t["raw"] for t in act.get("standalone", [])]
                if missing:
                    rep.warn(
                        f"[{act['tag']}]: template asks for performance tags {missing} and they "
                        f"are not in the lyric"
                    )

            t_out = row.get("transition_out")
            if t_out:
                labels = T.tag_label_map(st) if T is not None else {}
                want = labels.get(t_out, t_out)
                have = [x["raw"].casefold() for x in act.get("transitions", [])]
                act["transition_expected"] = want
                act["transition_present"] = [x["raw"] for x in act.get("transitions", [])]
                if want.casefold() not in have:
                    rep.warn(
                        f"[{act['tag']}]: template asks for a '{want}' transition out of this "
                        f"section and it is not in the lyric"
                    )

        written = sum(act["counts"])

        # --- fit against the clock -----------------------------------------------------------------
        if plan is not None and ei < len(plan["rows"]):
            row = plan["rows"][ei]
            act["budget"] = [row["budget_min"], row["budget_max"]]
            act["singable_s"] = row["singable_s"]
            act["ceiling"] = row["ceiling"]
            act["written"] = written

            if row["instrumental"] and written:
                rep.error(
                    f"[{act['tag']}]: {written} syllables written into an instrumental section "
                    f"({row['dur_s']:.1f}s); there is no vocal there"
                )
            elif not row["instrumental"]:
                if written > row["ceiling"]:
                    rep.error(
                        f"[{act['tag']}]: {written} syllables but only ~{row['ceiling']} fit in "
                        f"{row['singable_s']:.1f}s at {plan['bpm']:g} BPM; it cannot be sung in "
                        f"the time available"
                    )
                elif written > row["comfortable_max"]:
                    rep.warn(
                        f"[{act['tag']}]: {written} syllables against a comfortable "
                        f"~{row['comfortable_max']} in {row['singable_s']:.1f}s; it will be rushed"
                    )
                elif written > row["budget_max"]:
                    rep.warn(
                        f"[{act['tag']}]: {written} syllables over the "
                        f"{row['budget_min']}-{row['budget_max']} budget for "
                        f"{row['singable_s']:.1f}s"
                    )
                elif written < row["budget_min"]:
                    rep.oracle(
                        f"[{act['tag']}]: {written} syllables under the "
                        f"{row['budget_min']}-{row['budget_max']} budget; the section will feel "
                        f"empty unless the arrangement carries it"
                    )
                if row["singable_s"]:
                    act["rate"] = round(written / row["singable_s"], 2)

        # --- density against the plan ----------------------------------------------------------------
        if exp.get("bars") and exp.get("lines"):
            bar_band = (plan or {}).get("band") or list(SYLLABLE_BAND)
            act["syl_per_bar"] = round(written / exp["bars"], 2)
            if act["syl_per_bar"] > bar_band[1]:
                rep.warn(
                    f"[{act['tag']}]: {act['syl_per_bar']} syllables per bar over "
                    f"{exp['bars']} bars; more than the {bar_band[1]} comfortable maximum "
                    f"for a one-bar line (approximate)"
                )

        scheme_id = exp.get("rhyme_scheme")
        if not scheme_id or scheme_id not in schemes:
            continue
        scheme = schemes[scheme_id]
        kind = scheme.get("kind", "end")
        act["scheme_expected"] = scheme_id

        if kind == "none":
            continue

        if kind == "internal":
            # End-rhyme conformance is the wrong test for a verse carried by embedded rhyme, so
            # check for the presence of interior rhyme instead of matching a pattern.
            act["scheme_match"] = None
            if act["internal"] == 0:
                rep.warn(
                    f"[{act['tag']}]: declared internal rhyme but no interior rhyme pairs were "
                    f"found (approximate, and the detector is weakest exactly here)"
                )
            continue

        pattern = scheme["pattern"].replace(" ", "").replace("(", "").replace(")", "")
        detected = act["scheme"]
        if len(pattern) != len(detected):
            continue  # a scheme for a different line count; not comparable
        hits = sum(1 for p, d in zip(pattern, detected) if p == d)
        ratio = hits / len(pattern)
        act["scheme_match"] = round(ratio, 2)
        if ratio < 1.0:
            weight = "warn" if scheme["strictness"] == "strict" else "note"
            message = (
                f"[{act['tag']}]: rhyme scheme {detected} vs template '{scheme_id}' "
                f"({pattern}), {hits}/{len(pattern)} positions match (approximate)"
            )
            (rep.warn if weight == "warn" else rep.oracle)(message)

    hooks = [s for s in expected if s.get("hook")]
    if hooks:
        hook_roles = {h["role"] for h in hooks}
        if not any(s.get("role") in hook_roles for s in actual):
            rep.warn(f"template '{template['id']}': the hook section is absent")
    return result


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
    band_warning = any(
        "exceeds the" in w or "long way to sing" in w for w in rep2.warnings
    )
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
    template_id: str | None = None
    bpm: float | None = None
    duration: float | None = None
    profile_id: str | None = None
    for arg in argv[2:]:
        if arg.startswith("--selections="):
            selections = json.loads(Path(arg.split("=", 1)[1]).read_text()).get("selections", {})
        elif arg.startswith("--template="):
            template_id = arg.split("=", 1)[1]
        elif arg.startswith("--bpm="):
            bpm = float(arg.split("=", 1)[1])
        elif arg.startswith("--duration="):
            duration = float(arg.split("=", 1)[1])
        elif arg.startswith("--profile="):
            profile_id = arg.split("=", 1)[1]

    # Resolve the delivery band before the meter check, so the band the phrase check uses and the
    # band the time budget states are the same one. Otherwise a rap verse is judged by the sung
    # band and every line reports as too long.
    rates = T.load_delivery_rates() if T is not None else None
    prof = None
    if rates is not None and (template_id or selections or profile_id):
        if profile_id:
            prof = T.rate_profile(rates, profile_id)
        elif selections:
            prof = T.profile_for_vocals(selections, rates)
        else:
            prof = T.rate_profile(rates, None)
    band = tuple(prof["band"]) if prof and prof.get("band") and prof["band"][1] > 0 else None

    rep = Report()
    found = analyse(lines, st, rep)
    check_blank_lines(lines, st, rep)
    check_consistency(found, st, vocab, selections, rep)
    check_cliches(lines, rep)
    meter = check_meter_and_rhyme(lines, st, rep, band=band)

    section_count = sum(1 for f in found if f.get("section"))
    print(f"{path.name}: {len(lines)} lines, {len(found)} tags ({section_count} sections)")

    if meter["sections"]:
        print("\n  section                  syllables/line       phrases/line         end-rhyme")
        for s in meter["sections"]:
            counts = ",".join(str(c) for c in s["counts"])
            phr = " ".join("/".join(str(p) for p in line) for line in s["phrases"])
            scheme = s["scheme"]
            if s.get("scheme_expected"):
                scheme = (
                    f"{scheme} vs {s['scheme_expected']} ({s['scheme_match']})"
                    if s.get("scheme_match") is not None
                    else f"({s['scheme_expected']})"
                )
            if s.get("syl_per_bar") is not None:
                scheme += f"  {s['syl_per_bar']} syl/bar"
            print(f"  {s['tag'][:22]:<24}{counts:<21}{phr:<21}{scheme}")

        print("\n  sound structure (approximate; the devices a line-based model cannot see)")
        print(f"  {'section':<24}{'internal rhyme':>15}{'alliteration':>14}")
        for s in meter["sections"]:
            print(f"  {s['tag'][:22]:<24}{s['internal']:>15}{s['allit']:>14}")
        print("  (syllables are counted per phrase, not per printed line: cadence splits lines)")
        print("  (end-rhyme, internal rhyme and alliteration are spelling-based)")
        for chunk in textwrap.wrap(reduced_vowel_note(), 92):
            print(f"  note: {chunk}" if chunk.startswith("cross-line") else f"        {chunk}")
        print()

    if template_id:
        templates = {t["id"]: t for t in load(TEMPLATES_PATH)["templates"]}
        template = templates.get(template_id)
        if template is None:
            print(f"ERROR: unknown template '{template_id}'")
            rep.error(f"unknown template '{template_id}'")
        else:
            plan = None
            if T is not None:
                if prof is None:
                    prof = T.rate_profile(T.load_delivery_rates(), None)
                speed = bpm or 120.0
                sections = template["sections"]
                if duration:
                    total_bars = sum(s["bars"] for s in sections)
                    factor = (duration * speed / (T.BEATS_PER_BAR * 60.0)) / total_bars
                    sections = [
                        {**s, "bars": max(2, int(round(s["bars"] * factor / 2.0)) * 2)}
                        for s in sections
                    ]
                plan = T.build_timeline(
                    {**template, "sections": sections}, speed, st, prof, load(TEMPLATES_PATH)
                )
                tot = plan["totals"]
                print(
                    f"  timeline: {T.mmss(tot['total_s'])} total at {speed:g} BPM"
                    f"  |  {T.mmss(tot['vocal_s'])} sung, {T.mmss(tot['instrumental_s'])} instrumental"
                    f"  |  delivery '{prof['label']}'"
                )

            conf = check_template(meter, st, template, rep, plan=plan)
            print(f"  template '{template_id}': {template['name']}")
            print(f"    sections matched : {len(conf['matched'])} of {len(template['sections'])}")
            if conf["missing"]:
                print(f"    missing          : {conf['missing']}")
            if conf["extra"]:
                print(f"    unexpected       : {conf['extra']}")
            for f in conf["findings"]:
                print(f"    note             : {f}")

            fitted = [(e, a) for e, a in conf["matched"] if a.get("written") is not None]
            if fitted:
                print(f"\n    {'section':<22}{'written':>8}{'budget':>10}{'ceiling':>9}{'rate':>9}")
                for _exp, act in fitted:
                    b = act.get("budget")
                    rate = act.get("rate")
                    print(
                        f"    {act['tag'][:20]:<22}{act['written']:>8}"
                        f"{(f'{b[0]}-{b[1]}' if b else '-'):>10}"
                        f"{act.get('ceiling', '-'):>9}"
                        f"{(f'{rate:.2f}/s' if rate else '-'):>9}"
                    )
            print()
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
