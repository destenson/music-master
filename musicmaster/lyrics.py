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
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTION_TAGS_PATH = ROOT / "vocabulary" / "section-tags.json"
VOCAB_PATH = ROOT / "vocabulary" / "tag-bins.json"
CLICHES_PATH = ROOT / "vocabulary" / "lyric-cliches.json"
TEMPLATES_PATH = ROOT / "vocabulary" / "structure-templates.json"
RHYME_PATH = ROOT / "vocabulary" / "rhyme-schemes.json"

try:
    from . import timeline as T
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
    """Findings, split by what can be done about them.

    ``errors`` and ``warnings`` are defects the checker decided itself. ``oracle_tasks`` are
    semantic comparisons the checker can pose but not answer. ``notes`` are observations about the
    lyric that are neither: a rhyme scheme written to a lenient pattern is allowed to land
    approximately, and reporting an approximate landing as work for the oracle would claim a
    judgement is pending when the pattern already permits it.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.oracle_tasks: list[str] = []

    def error(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)

    def note(self, m: str) -> None:
        self.notes.append(m)

    def oracle(self, m: str) -> None:
        self.oracle_tasks.append(m)


# --- Brief leakage ----------------------------------------------------------------------
# A writing brief is a contract, not a lyric, but a model that has just read one sometimes copies
# a line of it into the section it describes. "Energy 3/5" is the common case: print_brief prints
# `energy 3/5` among a section's details, and the model writes it as the verse's first line, where
# the meter check counts it as a phrase and the renderer sings it. Every directive is one of the
# brief's own line templates, so recognising one is exact and removing it is a repair rather than a
# judgement. It lives here so the page and the CLI repair a draft the same way.
DIRECTIVES: list[tuple[str, re.Pattern]] = [
    ("energy", re.compile(r"^\(?\s*energy(?:\s+level)?\s*[:=]?\s*\d+\s*/\s*\d+\s*\)?$", re.I)),
    ("section plan", re.compile(r"^\d+\s*bars?\s*,\s*[\d.]+\s*s\b", re.I)),
    ("syllable ceiling", re.compile(r"^at most\s+\d+\s+syllables?\b", re.I)),
    ("syllable budget", re.compile(r"^budget\s*[:=]?\s*\d+\s*[-–—]\s*\d+\s*syllables?\b", re.I)),
    # Two forms are directives: a labelled one ("Rhyme: aabb", "rhyme scheme = ABAB") and the
    # scheme written uppercase ("rhyme ABAB"), which is how the vocabulary writes a pattern. A bare
    # lowercase `rhyme <word>` is left alone, because a lyric line may begin that way ("Rhyme
    # interludes") and stripping it would be the worse mistake.
    ("rhyme scheme", re.compile(r"^rhyme(?:\s+scheme)?\s*[:=]\s*[A-Za-z() ]{2,14}$", re.I)),
    ("rhyme scheme", re.compile(r"^rhyme\s+[A-Z() ]{2,12}$")),
    ("instrumental note", re.compile(r"^instrumental\b.*\bno words here\b", re.I)),
    # A model often writes the bare note rather than the brief's full line. It is a direction, not
    # words, and the renderer -- which only reads brackets -- would sing it.
    ("instrumental note", re.compile(
        r"^\(\s*(?:instrumental(?:\s+(?:break|section|interlude))?|no vocals?|no words?|silence)"
        r"\s*\)$",
        re.I,
    )),
    ("tag instruction", re.compile(r"^place (?:this|these)\b.*\bunder the header\b", re.I)),
    ("transition instruction", re.compile(r"^leave this section with\s*:", re.I)),
    ("hook note", re.compile(r"^this is the hook$", re.I)),
    ("brief header", re.compile(r"^\d+:\d+\s+total\b", re.I)),
    ("brief rule", re.compile(
        r"^(?:- )?(?:\d+\s*-\s*\d+ syllables per line|count syllables per phrase|"
        r"at most one modifier per tag|up to four standalone performance tags|"
        # The brief's own line is "uppercase inside a line means ...", but a model paraphrases it
        # ("UPPERCASE line means louder"), so the rule is recognised by its shape rather than by
        # the exact wording. A lyric that merely contains "means" does not match.
        r"uppercase\b[^;]{0,40}\bmeans\b|keep one core metaphor)\b",
        re.I,
    )),
]


def directive_kind(line: str) -> str | None:
    """The kind of brief directive a line is, or None when it is (or may be) a lyric.

    Each pattern is anchored to the whole line and names a template the brief prints, so a lyric
    that merely mentions energy or rhyme is not mistaken for one, and a line that is only a tag is
    left to the tag checker.
    """
    stripped = line.strip()
    if not stripped:
        return None
    for kind, pattern in DIRECTIVES:
        if pattern.match(stripped):
            return kind
    return None


# --- Tags written without brackets -------------------------------------------------------
# A model that has read the brief, or the caption, sometimes writes a tag as a bare line --
# `Low energy`, `Deadpan delivery`, `Melodic hook` -- instead of bracketing it. The renderer only
# reads brackets, so it sings the line. Both vocabularies name every tag exactly, so a whole line
# equal to a label is a tag that lost its brackets rather than a guess about English.
_TAG_LABELS: set[str] | None = None
_STANDALONE_LABELS: set[str] | None = None
_SECTION_TAGS: dict | None = None

# The pools a tag may stand in on its own. `modifiers` is deliberately absent: a modifier belongs
# to a section header (`[Chorus - anthemic]`), so `[melodic]` alone is not a tag the grammar takes.
STANDALONE_POOLS = ("transition_tags", "vocal_tags", "energy_tags", "instrumental_section_tags")


def _section_tags() -> dict:
    """The lyric metatag vocabulary, loaded once. A missing file disables the tag test rather than
    failing the cleaner, which must still strip the brief's own lines."""
    global _SECTION_TAGS
    if _SECTION_TAGS is None:
        try:
            _SECTION_TAGS = json.loads(SECTION_TAGS_PATH.read_text())
        except OSError:
            _SECTION_TAGS = {}
    return _SECTION_TAGS


def standalone_tag_labels() -> set[str]:
    """The labels the lyric grammar accepts as a bracketed tag on its own line."""
    global _STANDALONE_LABELS
    if _STANDALONE_LABELS is None:
        st = _section_tags()
        labels: set[str] = set()
        for key in STANDALONE_POOLS:
            labels.update(tag["label"].casefold() for tag in st.get(key, []))
        _STANDALONE_LABELS = labels
    return _STANDALONE_LABELS


def tag_labels() -> set[str]:
    """Every tag label the vocabularies define, casefolded, loaded once.

    The lyric pools and the caption bins both name directions; a model that has seen either can
    copy one into a section. A missing vocabulary file yields an empty set, which disables the test
    rather than failing it.
    """
    global _TAG_LABELS
    if _TAG_LABELS is None:
        labels = set(standalone_tag_labels())
        st = _section_tags()
        for tag in st.get("modifiers", []):
            labels.add(tag["label"].casefold())
        try:
            vocab = json.loads(VOCAB_PATH.read_text())
        except OSError:
            vocab = {}
        for bin_ in vocab.get("bins", []):
            labels.update(option["label"].casefold() for option in bin_.get("options", []))
        _TAG_LABELS = labels
    return _TAG_LABELS


def bare_tag(line: str) -> str | None:
    """The tag label a whole line is when it carries no brackets, or None.

    A bracketed line is the checker's business, not this one's, so anything with a bracket is left
    alone here.
    """
    stripped = line.strip()
    if not stripped or TAG_RE.search(stripped):
        return None
    return stripped if stripped.casefold() in tag_labels() else None


def _content_line(line: str) -> bool:
    """Whether a line is words a section is meant to sing.

    A blank, a bracketed tag and a recognised directive are not words, so they do not bound the
    edge zones a bare tag has to sit in.
    """
    stripped = line.strip()
    if not stripped or TAG_RE.search(stripped):
        return False
    return directive_kind(stripped) is None and bare_tag(stripped) is None


def _edge_zones(lines: list[str]) -> set[int]:
    """The zero-based lines at a section's edges: before its first words and after its last.

    Tags belong at a section's edge -- the brief puts the performance tags under the header and the
    transition on the last line -- so a bare label there is a tag that lost its brackets. A bare
    label *between* words is left to the lyric, where a lyric is the likelier reading.
    """
    st = _section_tags()
    zones: set[int] = set()

    def close(segment: list[int]) -> None:
        content = [index for index in segment if _content_line(lines[index])]
        if not content:
            zones.update(segment)
            return
        first, last = content[0], content[-1]
        zones.update(index for index in segment if index < first or index > last)

    segment: list[int] = []
    for index, line in enumerate(lines):
        match = TAG_RE.search(line)
        if match and is_section_header(st, match.group(1)):
            close(segment)
            segment = []
            continue
        segment.append(index)
    close(segment)
    return zones


def _tag_positions(lines: list[str]) -> set[int]:
    """The zero-based lines a tag could stand on: a section's edges, or directly after a line that
    already carries a bracketed tag.

    The second half is what continues a run: once a header or a tag is bracketed, a bare label
    beneath it is a tag that lost its brackets too, even mid-section.
    """
    positions = set(_edge_zones(lines))
    previous = ""
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if TAG_RE.search(previous):
            positions.add(index)
        previous = line
    return positions


def _bare_tag_action(lines: list[str], index: int, positions: set[int]) -> str | None:
    """What a bare tag line is: `bracket` a tag the grammar takes, `remove` a name it does not, or
    None when the line is (or may be) a lyric.

    A one-word caption name is left alone: `Raw` or `Piano` at the top of a section is as likely to
    be a lyric line as a direction, and dropping a lyric is the worse mistake. A multi-word name
    (`Deadpan delivery`, `Melodic hook`) is a direction and the caption already carries the sound.
    """
    label = bare_tag(lines[index])
    if label is None or index not in positions:
        return None
    if label.casefold() in standalone_tag_labels():
        return "bracket"
    return "remove" if " " in label.strip() else None


_TRAILING_TAG_RE = re.compile(r"^(?P<head>.*?)\s*(?P<tag>\[[^\[\]]+\])$")


def _split_trailing_tag(line: str) -> tuple[str | None, str | None]:
    """Split `last words [hard cut]` into `('last words', '[hard cut]')`.

    A tag sits on its own line; a model sometimes glues the section's transition, or a performance
    tag, to the end of the last lyric line, where the renderer can sing it with the words. Only a
    tag that follows words is split -- a line of tags alone is already where it belongs.
    """
    match = _TRAILING_TAG_RE.match(line.strip())
    if not match:
        return None, None
    head = match.group("head")
    if not re.sub(r"\[[^\[\]]*\]", "", head).strip():
        return None, None
    return head, match.group("tag")


def strip_directives(text: str) -> dict:
    """Repair the directions a model copied into a draft, and say what was removed and what changed.

    Three repairs, each exact: a line of the brief itself is removed; a tag written bare is
    bracketed when the lyric grammar takes it there and removed when it does not (a multi-word name
    such as `Melodic hook` is not a lyric tag, and the caption already carries the sound); and a tag
    glued to the end of a lyric line is moved onto its own line. Removing a line can leave a run of
    blanks where it sat between two of them, so a run is collapsed to the single blank the lyric
    grammar expects.

    Nothing is silent: ``removed`` names every line that was dropped and ``changed`` every line that
    was rewritten, both with the line number from the input, so a caller can show what happened.
    ``{"text": ..., "removed": [{"line", "kind", "text"}],
    "changed": [{"line", "kind", "text", "replacement"}]}``
    """
    lines = text.splitlines()
    positions = _tag_positions(lines)
    kept: list[str] = []
    removed: list[dict] = []
    changed: list[dict] = []
    for index, line in enumerate(lines):
        lineno = index + 1
        kind = directive_kind(line)
        if kind is not None:
            removed.append({"line": lineno, "kind": kind, "text": line.strip()})
            continue
        action = _bare_tag_action(lines, index, positions)
        if action == "remove":
            removed.append({"line": lineno, "kind": "unbracketed name", "text": line.strip()})
            continue
        if action == "bracket":
            replacement = f"[{line.strip()}]"
            changed.append({"line": lineno, "kind": "unbracketed tag", "text": line.strip(),
                            "replacement": replacement})
            kept.append(replacement)
            continue
        head, tag = _split_trailing_tag(line)
        if tag is not None:
            changed.append({"line": lineno, "kind": "tag on the wrong line", "text": line.strip(),
                            "replacement": f"{head}\n{tag}"})
            kept.append(head)
            kept.append(tag)
            continue
        kept.append(line)
    return {
        "text": re.sub(r"\n{3,}", "\n\n", "\n".join(kept)),
        "removed": removed,
        "changed": changed,
    }


def check_directives(lines: list[str], rep: Report) -> list[dict]:
    """Report a direction left in the lyric: it is not words, but the model would sing it.

    Only a tag in a tag position is reported, and only a bare label the vocabularies name; a bare
    label between words may be a lyric and is left to the reader.
    """
    positions = _tag_positions(lines)
    found: list[dict] = []
    for index, line in enumerate(lines):
        lineno = index + 1
        kind = directive_kind(line)
        if kind is not None:
            found.append({"line": lineno, "kind": kind, "text": line.strip()})
            rep.error(
                f"line {lineno}: '{line.strip()}' is a directive from the writing brief ({kind}), "
                f"not a lyric; a generated draft has it stripped automatically, so this one was "
                f"written or pasted by hand"
            )
            continue
        action = _bare_tag_action(lines, index, positions)
        if action == "bracket":
            found.append({"line": lineno, "kind": "tag without brackets", "text": line.strip()})
            rep.error(
                f"line {lineno}: '{line.strip()}' is a tag written without brackets, so the "
                f"renderer would sing it; write it as '[{line.strip()}]' — a generated draft has it "
                f"bracketed automatically"
            )
            continue
        if action == "remove":
            found.append({"line": lineno, "kind": "tag without brackets", "text": line.strip()})
            rep.error(
                f"line {lineno}: '{line.strip()}' is a direction the lyric grammar has no tag for, "
                f"so the renderer would sing it; remove it — a generated draft has it stripped "
                f"automatically"
            )
            continue
        _, tag = _split_trailing_tag(line)
        if tag is not None:
            found.append({"line": lineno, "kind": "tag not on its own line", "text": line.strip()})
            rep.error(
                f"line {lineno}: the tag '{tag}' shares a line with lyric words; a tag sits on its "
                f"own line so the renderer does not sing it with the words"
            )
    return found


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


def _instrumental_surfaces(found: list[dict], st: dict) -> list[str]:
    """Where the lyric names an instrument, as "'[tag]' line N".

    Two surfaces do it, and the caption comparison covers both: a section the vocabulary flags as
    instrumental -- ``[Instrumental]``, ``[Solo - guitar]`` -- and a standalone
    ``instrumental_section_tags`` tag such as ``[Guitar Solo]``.
    """
    sections = {s["id"]: s for s in st["sections"]}
    surfaces: list[str] = []
    for sec in found:
        meta = sections.get(sec.get("section") or "")
        if meta and meta.get("instrumental"):
            surfaces.append(f"'[{sec['raw']}]' line {sec['line']}")
        for tag in sec.get("standalone", []):
            if tag["pool"] == "instrumental_section_tags":
                surfaces.append(f"'[{tag['raw']}]' line {tag['line']}")
    return surfaces


def consistency_tasks(found: list[dict], st: dict, selections: dict) -> list[dict]:
    """The semantic consistency rules the checker can pose but not answer.

    One dict per rule in scope: its id and text, the caption bins that make it applicable, the lyric
    tag pool it compares against, and the tags actually found in the lyric. ``display`` is the line
    the Lyrics tab shows; the Check tab turns the same dict into a requirement, so the findings list
    and the check cannot disagree about what was deferred.

    The one exactly-decidable rule is deliberately absent: ``no_vocals_no_vocal_tags`` is an error in
    code, and posing it here would ask a model to re-decide something the checker already settled.
    """
    tasks: list[dict] = []
    surfaces = _instrumental_surfaces(found, st)
    for rule in st["consistency"]:
        if rule["id"] == "no_vocals_no_vocal_tags":
            continue
        bins_present = [bin_id for bin_id in rule["caption_bins"] if selections.get(bin_id)]
        if not bins_present:
            continue
        lyric_tags: list[str] = []
        for sec in found:
            for tag in sec.get("standalone", []):
                if tag["pool"] == rule["section_pool"] and tag["raw"] not in lyric_tags:
                    lyric_tags.append(tag["raw"])
        if rule["id"] == "instruments_match_instrumental_tags":
            # A section names its instrument in the modifier -- `[Solo - guitar]` -- and that name is
            # the evidence the rule is about, so it joins the pool tags. Without it the rule would be
            # asked against an empty list and answered on nothing.
            sections = {s["id"]: s for s in st["sections"]}
            for sec in found:
                meta = sections.get(sec.get("section") or "")
                if meta and meta.get("instrumental") and sec.get("modifier") and sec["modifier"] not in lyric_tags:
                    lyric_tags.append(sec["modifier"])
        # Nothing in the lyric of the pool the rule covers means nothing the rule can contradict: the
        # rules say the tags must not contradict the caption, and silence does not contradict. The
        # instrumentation rule is the exception, because a section can name the instrument without a
        # tag, which is what `surfaces` records.
        if not lyric_tags and not (rule["id"] == "instruments_match_instrumental_tags" and surfaces):
            continue
        where = ""
        if rule["id"] == "instruments_match_instrumental_tags" and surfaces:
            where = f" ({', '.join(surfaces)})"
        tasks.append(
            {
                "rule": rule["id"],
                "rule_text": rule.get("judge") or rule.get("rule", ""),
                "caption_bins": bins_present,
                "pool": rule["section_pool"],
                "lyric_tags": lyric_tags,
                # An instrument a *section* names -- `[Solo - guitar]`, `[Instrumental]` -- is the
                # evidence the instrumentation rule is actually about, and it is not a pool tag. The
                # question is told about it, or it would be asked against an empty list.
                "surfaces": surfaces if rule["id"] == "instruments_match_instrumental_tags" else [],
                "display": (
                    f"consistency rule '{rule['id']}': compare caption bins {bins_present} against "
                    f"{rule['section_pool']} tags in the lyrics{where}"
                ),
            }
        )
    return tasks


def check_consistency(found: list[dict], st: dict, vocab: dict, selections: dict, rep: Report) -> None:
    """Enforce the exactly-checkable consistency rule; give each semantic rule one oracle task.

    Rule 4 is decidable and never deferred: when the caption's lead vocal is Instrumental or No
    Vocals, a vocal control tag in the lyric is an error, not a question. The other rules compare a
    caption bin against a lyric tag pool, which is a judgement, so they are deferred -- once each.
    The instrumentation rule is compared against two lyric surfaces, so naming both in its single
    task keeps one rule from producing two deferrals.
    """
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

    for task in consistency_tasks(found, st, selections):
        rep.oracle(task["display"])

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


# A shared phrase is not a repeated song, so a run shorter than the floor is left alone; a run at or
# past the ceiling is a lift however much of the rest of the lyric is new. Between them the penalty
# ramps, which is what makes the measure a judgement rather than a cliff.
RUN_FLOOR = 5
RUN_CEILING = 20


def lyric_words(text: str) -> list[str]:
    """The words a listener hears, with the staging taken out.

    Section headers, performance tags and ``(instrumental)`` notes are directions to the model, not
    words anyone sings, so they are dropped before two lyrics are compared. Case is folded: the
    measure is about what was said, and a model that capitalises a line differently has not written a
    different song.
    """
    without_tags = TAG_RE.sub(" ", text)
    without_notes = re.sub(r"\([^)]*\)", " ", without_tags)
    return [word.casefold() for word in re.findall(r"[A-Za-z0-9']+", without_notes)]


def longest_shared_run(left: list[str], right: list[str]) -> int:
    """The longest run of consecutive words two lyrics have in common."""
    if not left or not right:
        return 0
    best = 0
    previous = [0] * (len(right) + 1)
    for word in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, start=1):
            if word == other:
                current[index] = previous[index - 1] + 1
                if current[index] > best:
                    best = current[index]
        previous = current
    return best


def novelty(candidate: str, prior: Sequence[str]) -> dict:
    """How new a draft's words are against words the song's station has already sung.

    Two signals, because either alone is easy to fool. A whole lyric repeated has a word-set overlap
    of one; a draft that keeps a prior hook but rewrites everything around it has a low overlap and a
    long shared run. They are folded into one number:

    * ``max_overlap`` — the largest Jaccard overlap of word sets with any single prior lyric;
    * ``longest_run`` — the longest run of consecutive words shared with any prior lyric, scored as a
      ramp from ``RUN_FLOOR`` (a phrase anyone might write) to ``RUN_CEILING`` (a lift);
    * ``novelty`` — one minus the larger of the two, so 1.0 shares nothing and 0.0 repeats a take.

    With no prior lyric there is nothing to repeat, and every draft is new.
    """
    words = lyric_words(candidate)
    kept = [
        (index, other)
        for index, text in enumerate(prior)
        for other in [lyric_words(text)]
        if other
    ]
    if not words or not kept:
        return {
            "novelty": 1.0,
            "max_overlap": 0.0,
            "longest_run": 0,
            "nearest": None,
            "words": len(words),
        }

    candidate_set = set(words)
    nearest: int | None = None
    overlap = 0.0
    run = 0
    score = 0.0
    for index, other in kept:
        union = candidate_set | set(other)
        here_overlap = len(candidate_set & set(other)) / len(union) if union else 0.0
        here_run = longest_shared_run(words, other)
        here_score = max(here_overlap, _run_penalty(here_run))
        if here_score > score:
            nearest, overlap, run, score = index, here_overlap, here_run, here_score

    return {
        "novelty": round(max(0.0, 1.0 - score), 4),
        "max_overlap": round(overlap, 4),
        "longest_run": run,
        "nearest": nearest,
        "words": len(words),
    }


def _run_penalty(run: int) -> float:
    """A shared run's share of the ramp, zero at the floor and one at the ceiling."""
    if run <= RUN_FLOOR:
        return 0.0
    return min(1.0, (run - RUN_FLOOR) / (RUN_CEILING - RUN_FLOOR))


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
            # A strict scheme is a commitment, so a miss is a warning. A lenient one is written to
            # bend, so an approximate landing is a note -- not a pending oracle verdict.
            message = (
                f"[{act['tag']}]: rhyme scheme {detected} vs template '{scheme_id}' "
                f"({pattern}), {hits}/{len(pattern)} positions match (approximate)"
            )
            (rep.warn if scheme["strictness"] == "strict" else rep.note)(message)

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
    check_directives(lines, rep)
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
    for n in rep.notes:
        print(f"note:  {n}")
    for w in rep.warnings:
        print(f"warn:  {w}")
    for e in rep.errors:
        print(f"ERROR: {e}")
    for t in rep.oracle_tasks:
        print(f"oracle: {t}")

    if rep.errors:
        print(f"\nFAILED with {len(rep.errors)} error(s)")
        return 1
    print(f"\nOK; {len(rep.oracle_tasks)} item(s) deferred to the oracle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
