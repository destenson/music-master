# Tag bins: the vocabulary behind the prompt

The tag string a generator receives is not typed. It is **rendered from selections**, and the
selections come from dropdowns, checkboxes and sliders built from a controlled vocabulary of
*bins*. This document is the design of that vocabulary: what a bin is, how the UI is built
from it, how selections become a string, and why the file is the single point where the UI,
the prompt and the compliance battery are kept in step.

- The data: [`vocabulary/tag-bins.json`](../../vocabulary/tag-bins.json) — 29 bins, 711 options.
- The schema: [`schemas/tag-vocabulary.schema.json`](../../schemas/tag-vocabulary.schema.json)
- The lyric metatags: [`vocabulary/section-tags.json`](../../vocabulary/section-tags.json) — 59 tags across 5 pools, with the tag grammar and the caption/lyric consistency rules
- The validator: [`vocabulary/validate_vocabulary.py`](../../vocabulary/validate_vocabulary.py)
- The reference renderer: [`vocabulary/render_tags.py`](../../vocabulary/render_tags.py)
- The lyric checker: [`vocabulary/check_lyrics.py`](../../vocabulary/check_lyrics.py)
- The fixtures: [`vocabulary/examples/late-night-trap.json`](../../vocabulary/examples/late-night-trap.json), [`lyrics-late-night-trap.md`](../../vocabulary/examples/lyrics-late-night-trap.md)
- The prompting rules these implement: [`../research/prompting-rules.md`](../research/prompting-rules.md), read from ACE-Step's own tutorial

## 1. Why bins rather than a text box

A free-text tag box produces prompts that are unreviewable, unhashable and unrepeatable: two
people describing the same song write two different strings, and neither can be reloaded into
a UI six months later. Bins fix four things at once:

1. **The UI is generated from the data.** Adding an option to the file adds a checkbox; no UI
   code changes.
2. **The prompt is reproducible.** Selections are stored by option **id**, so the same
   selections always render the same string and hash the same bytes.
3. **The prompt is checkable.** A selected bin with a `maps_to` tells the check what it now owes
   the user, and which artifact can settle it: select a genre and the caption must carry it, which
   code can decide; select a mood and the lyric has to read that way, which is the oracle's
   question. See [`pre-render-check.md`](pre-render-check.md).
4. **The vocabulary is editable without breaking saved work.** A label can be reworded; the id
   it is stored under does not move.

Free text is still available, but as a deliberate escape hatch (`combo_free` bins), not as the
primary input.

## 2. What a bin declares

| Field | Purpose |
| --- | --- |
| `id` | Stable key. Stored in the prompt; never shown to the model |
| `label` | The UI's name for the bin, and the axis name in the compliance report |
| `group` | Layout only: Style, Rhythm, Instruments, Vocals, Sound, Words, Constraints |
| `control` | Which widget to build (below) |
| `priority` | 1 = defining, 3 = nice to have. Drives budget truncation |
| `maps_to` | The requirement this bin creates, in `RequirementSpec.verify` form |
| `emits_tag` | False for constraint bins, whose selections become checks and negative conditioning rather than tags |
| `options` | The selectable values, each with an `id`, a `label` (the exact tag text), optional `aliases`, and optional `excludes` |

The `label` **is** the tag text, verbatim. Options carry compound, natural-reading phrases —
`Heavy 808 Bass`, `Dark Bedroom Production`, `Breathy Whispers` — rather than atomic nouns with
separate adjective bins, because that is how music tag prompts are actually written and it is
what the motivating example contains.

One hard rule the validator enforces: **a label may not contain a comma**, because commas
separate tags in the rendered string. It may not have stray whitespace either.

## 3. Controls, and the UI they build

| `control` | Widget | Selection shape |
| --- | --- | --- |
| `single_select` | Dropdown or radio row | exactly one option |
| `multi_select` | Checkbox list, with a counter against `max_selections` | 0..N option ids |
| `numeric` | Slider plus number input | a number |
| `numeric_with_descriptor` | The same, plus an optional word tag (`Mid-Tempo`) | a number, plus 0..N ids |
| `key_mode` | Two dropdowns: tonic and mode | a key and a mode |
| `ranked_multi` | Ordered list, drag to reorder; order is meaningful | ordered option ids |
| `combo_free` | Datalist: pick a suggestion or type your own | 0..N ids plus free text |

The UI is a single form, grouped into collapsible sections by `group`, with three things always
visible:

```
┌─ Style ────────────────────────┬─ Live prompt ──────────────────────────────┐
│ Genre            [Trap      ▾] │ Trap, West-Coast Feel, Late Night, 95 BPM, │
│ Fusion           ☐ Cinematic   │ Heavy 808 Bass, Slap Bass, Deep Sub Bass,  │
│                    ☐ Soundtrack│ Wet Synths, Male Rap Vocals, Breathy       │
│ Regional feel    ☑ West-Coast │ Whispers, Female Background Vocals,        │
│ Scene            ☑ Late Night  │ Seductive Female Vocals, Dark Bedroom      │
├─ Rhythm ───────────────────────┤ Production, Cinematic R&B Soundtrack       │
│ Tempo      95 ──●────────  BPM │                                            │
│ Time sig.        [4/4       ▾] │ tags 14 / budget 14        [ Copy ]        │
│ Key and mode     [F# ▾][minor▾]│ ───────────────────────────────────────────│
├─ Instruments ──────────────────┤ ⚠ 0 conflicts    ⓘ 3 bins unset            │
│ Drums            ☐ 808 Kicks…  │                                            │
│ Bass             ☑ Heavy 808…  │                                            │
└────────────────────────────────┴────────────────────────────────────────────┘
```

Three UI obligations that follow from the model:

- **Live rendering.** The right-hand pane re-renders on every change, so the user always sees
  the exact string the model will receive, including the budget count. A prompt that silently
  dropped a tag at render time would be a nasty surprise.
- **Conflicts surface immediately.** Selecting `Instrumental` clears and disables the vocal
  bins. Exclusions are treated as **symmetric** by the linter even where the data declares them
  one way, so the UI cannot be walked into an impossible state from either direction.

  Not every conflict is an exclusion, though. The model's guide warns that conflicting style
  combinations degrade output and offers two remedies rather than a prohibition: **repetition
  reinforcement** (repeat the element that should dominate) and **conflict to evolution** (make
  it temporal — "start with soft strings, middle becomes metal, end turns to hip-hop"). Both are
  worth exposing as affordances. Evolution in particular is a structure-level answer, so it lands
  in the lyric section tags, not the caption.
- **Selections explain themselves.** Each bin can contribute a note, which lands in the prompt's
  `notes` array and its `requirement_id`. That is where "why is the tempo 95" gets recorded —
  in the artifact, not in someone's memory.

## 4. Rendering: selections to a tag string

The rules, in order, as implemented in `render_tags.py`:

1. **Walk `render_order`, not the UI order.** Bins are grouped for humans and ordered for the
   model. `render_order` is what makes two prompts meaning the same thing produce the same
   bytes.
2. **Skip `emits_tag: false` bins.** Explicitness and content exclusions never appear in the
   positive string; they become negative conditioning and compliance questions.
3. **Emit labels verbatim**, options first, then the numeric template (`{value} BPM`), then the
   key and mode, then any free text for that bin.
4. **Collapse duplicate labels**, keeping the first in render order.
5. **Enforce the tag budget by priority.** If the string exceeds `tag_budget` (64), tags are
   ranked by bin priority and then by render order, and the lowest-priority surplus is dropped.
6. **Record every omission.** Dropped tags go into the prompt's `omitted` list. A tag that never
   reaches the model must still be visible in the artifact, or reproducibility is a lie.
7. **Join with `", "`.**

Step 5 deserves a note. A long tag list is not automatically a better prompt, which is why the cap
is enforced by priority rather than by hoping — but the number itself is model-specific. An early
figure of 14 came from Suno community advice (4–8 descriptors, ~20 ceiling), which was the wrong
model to borrow from: ACE-Step's own guide says it accepts comma-separated tags, plain style words
and long natural-language descriptions alike, and that the text format does not significantly change
performance. A full selection across the caption dimensions lands around 30, and a song that states a
fusion, a whole kit, a vocal split and its exclusions passes that comfortably, so the budget is
**64**. It is a dilution guard rather than a model limit, and it should still be tuned against
compliance outcomes rather than by taste. What matters either way is that a truncation the user
cannot see is worse than no truncation, so the budget is displayed live and `omitted` is stored.

### 4.1 What never becomes a tag

ACE-Step's own tutorial is explicit on this point:

> Don't write tempo, BPM, key, and other metadata information in Caption. These should be set
> through dedicated metadata parameters (`bpm`, `keyscale`, `timesignature`, etc.), not described
> in Caption.

So three bins carry `emits_tag: false` or `value_emits_tag: false`, and their selections go to
`prompt.metadata` instead:

| Bin | Behaviour |
| --- | --- |
| `tempo` | The number goes to `metadata.bpm`. Only a descriptor word (`Mid-Tempo`, `Laid-Back`) can reach the tag string, and only if the user picks one |
| `time_signature` | Metadata only |
| `key_mode` | Metadata only |
| `explicitness`, `content_exclusions` | Never tags. They become negative conditioning and compliance checks |

The motivating example is affected: it puts `95 BPM` in the tag string, and per the model's own
guidance it should not. A number in both places is at worst a conflict when the two disagree. The
fixture records the change and the reason.

Two bins also carry a `caution` string where the model's documentation admits instability. The
`time_signature` bin's `5/4` and `7/8` options do, because the tutorial says complex signatures
are "advanced, effects vary by style" and that `4/4` is the most reliable. The caution surfaces
in the UI and is carried into the pre-prompt check rather than being buried in a doc.

### 4.2 Rendering is target-specific

The canonical prompt records intent; the adapter decides how to express it. Reading a second
model's guidance against ACE-Step's turns up two places where "the right way" differs by target:

| Intent | ACE-Step 1.5 | A Suno-like target |
| --- | --- | --- |
| `metadata.bpm = 95` | the `bpm` metadata field, and **never** the caption | rendered into the style prompt as `95 BPM`, because there is no metadata field to put it in |
| chorus, one modifier `anthemic` | `[Chorus - anthemic]`, at most one modifier | `[Chorus \| Anthemic]`, stacking several is common practice |

So `render_order`, `value_emits_tag` and `emits_tag` as written describe the **ACE-Step 1.5
rendering**; a second target carries its own. What does not change is the stored intent:
selections by option id, and a section plus an ordered modifier list. This is the generator
adapter's swap-safety principle applied to the prompt itself, and it is the reason the canonical
artifact is an object rather than a string.

## 5. One vocabulary, three consumers

The reason this file matters more than a constants list is that a bin is simultaneously a UI
control, a prompt field, and a compliance obligation. The three are kept in step by `maps_to`:

| Bin | `maps_to` | What the battery must therefore do |
| --- | --- | --- |
| `genre`, `fusion`, `regional_feel` | `jev.genre_fidelity` | one Jev score, plus the tags themselves as evidence |
| `tempo` | `code.audio.tempo` | measure BPM and compare in code |
| `time_signature` | `code.audio.meter` | measure, compare in code |
| `key_mode` | `code.audio.key` | measure with chroma; treat as low confidence |
| `drums`, `bass`, `harmony`, `synth`, `extra_instrument` | `jev.instrumentation` | Jev on the surrogate, plus stem presence from demucs |
| `lead_vocal`, `vocal_delivery`, `backing_vocal`, `vocal_fx` | `jev.vocal_spec` | Jev, plus measured F0 range from the vocal stem |
| `production`, `space` | `jev.era_production` | Jev on the surrogate; spectral facts as corroboration |
| `timbre` | `jev.timbre` | Jev on the surrogate; the guide notes texture words influence mixing and timbre |
| `mood`, `scene` | `jev.mood_axis` | one score per selected axis |
| `energy` | `jev.energy` | one score |
| `lyric_theme` | `jev.theme_adherence` | Jev on lyrics and plan |
| `hook` | `jev.hook_payoff` | Jev on lyrics |
| `structure` | `code.audio.sections` | segment the render and compare the section map; its option carries a `template_ref`, so choosing a form selects the contract the lyrics are written to and checked against ([lyric templates](lyric-templates.md)) |
| `explicitness`, `content_exclusions` | `jev.explicitness`, `jev.content_policy` | lexical gates plus Jev policy nouls |

Note that `tempo`, `time_signature` and `key_mode` appear here as obligations even though they
emit no tags. That is the point of keeping `maps_to` orthogonal to `emits_tag`: a bin can create
a requirement without contributing to the prompt.

So **adding a bin is a four-part change**: options, a control, a position in `render_order`, and
a checker. The validator warns if the third is missing; the fourth is a review obligation with
no automated check, which is why `maps_to` is required rather than optional.

## 6. Importing a hand-typed prompt

Existing prompts — including the motivating example — predate the UI. Options therefore carry
`aliases`, and the intended import path is: split on commas, match each tag against labels and
aliases case-insensitively, then report what did not match for the user to assign by hand. This
is a convenience, not a source of truth: the imported result is shown as selections for review
before it becomes a prompt artifact.

`vocabulary/examples/late-night-trap.json` is that example resolved. Rendering it produces 13
tags, well inside the budget of 64:

```
Trap, West-Coast Feel, Late Night, 95 BPM, Heavy 808 Bass, Slap Bass, Deep Sub Bass,
Wet Synths, Male Rap Vocals, Breathy Whispers, Female Background Vocals,
Seductive Female Vocals, Dark Bedroom Production, Cinematic R&B Soundtrack
```

The differences from the hand-typed original are recorded in the fixture and are all
canonicalisation rather than meaning: order is fixed by `render_order`, `Late Night Trap` became
the genre `Trap` plus the scene `Late Night` so either can be changed independently, and
`Cinematic R&B Soundtrack` is one `vibe_reference` option rather than a composed genre fusion.

## 7. Section tags: the other vocabulary

The tag string is the caption. The **section tags in the lyrics are a separate control surface**,
and ACE-Step's tutorial calls them "the most powerful tool in Lyrics" — the temporal script to the
caption's overall portrait. The *shape* those sections form is itself data, in
[`lyric-templates.md`](lyric-templates.md): 15 structures and 13 rhyme schemes, used as a writing
brief, a bar plan, and a conformance check. They live in `vocabulary/section-tags.json` and get
their own grammar, because the guide names two specific failure modes:

> Stacking too many tags has two risks: the model might mistake tag content as lyrics to sing;
> too many instructions confuse the model, making effects worse.

So `max_modifiers` is `1`, the accepted shape is `[Section]` or `[Section - modifier]`, and every
bracket in a lyric is validated against the file before the prompt is rendered. **An unrecognised
tag is treated as a defect, not a style choice**, because the model may sing it.

The file holds five pools — `sections`, `modifiers`, `vocal_tags`, `energy_tags`,
`instrumental_section_tags` — and `check_lyrics.py` enforces the grammar and reports the
caption/lyric consistency rules. That is where the tutorial's checklist becomes machinery:

| Rule | Checkable how |
| --- | --- |
| No vocal tag when the caption's lead vocal is Instrumental | **In code.** Exactly decidable |
| Instrument in the caption ↔ instrumental section tag in the lyrics | Oracle. Semantic |
| Caption emotion ↔ lyric energy tag | Oracle. Semantic |
| Caption vocal description ↔ lyric vocal control tag | Oracle. Semantic |

Keeping the mechanical one in code and the rest with the oracle is the same division the whole
design uses, and it is why `check_lyrics.py` exits with a distinct "deferred to the oracle" list
rather than pretending to have verified them. Its findings are split three ways for that reason:
what the checker can decide is an error or a warning, what it can only pose is deferred to the
oracle, and what a lenient rule already permits — a rhyme scheme landing approximately — is a note
rather than a pending verdict.

```bash
python3 vocabulary/check_lyrics.py vocabulary/examples/lyrics-late-night-trap.md \
    --selections=vocabulary/examples/late-night-trap.json
python3 vocabulary/check_lyrics.py --self-test
```

The self-test runs a deliberately broken lyric through the checker and asserts it catches all
four classes of defect: a stacked modifier, an unknown tag, an invalid modifier, and a vocal tag
inside an instrumental.

### 7.1 What the checker found on the real paired example

The fixture pair — the caption and the lyrics that ship together with the packaged ComfyUI
ACE-Step 1.5 template — is a genuinely useful regression case, because the two describe
different things: the caption asks for late-night trap with seductive backing vocals, and the
lyrics are a technical walkthrough of node graphs. That is the template's own joke, and it is
also exactly the failure mode the consistency rules exist to catch.

Running the checker on it produced five findings worth keeping:

| Finding | Why it matters |
| --- | --- |
| No blank line between sections; four warnings | The guide asks for blank-line separation so boundaries are unambiguous. Cheap to fix, easy to miss |
| Verse lines at 11–13 syllables per *printed line* — but that is the wrong unit | Every verse line except two breaks at its internal comma into phrases of 4–7 syllables, inside the band. The two with no internal punctuation are the only genuinely long ones. A line-based count flagged ten; a phrase-aware count flags two, and those two are real. See [lyric-templates.md](lyric-templates.md) §5 |
| No modifier and no performance, vocal or energy tags anywhere | Legitimate — all direction is in the caption — but it leaves the consistency check nothing to compare against, so three caption selections have no lyric counterpart |
| Rhymes missed and false pairs found | The detector is spelling-based. A silent-final-*e* bug was making `insane`, `image` and `node` share the key `e`; fixing it recovered `insane`/`chain`, `node`/`code` and `slate`/`late`. Cross-line embedded rhyme is now not reported at all, because stress and vowel length decide it and spelling does not encode either |
| Technical jargon — KSampler, VAE, CFG, ControlNet, ComfyUI | Hard phoneme sequences, and the guide warns the model drops or slurs consonant clusters. This is the content that most needs the independent ASR currently marked unverified |

The first and fourth are the useful ones for the design: the blank-line rule was a doc sentence
that is now an enforced check, and the rhyme miss converts "use a pronunciation lexicon" from a
preference into a demonstrated dependency.

## 8. Extending the vocabulary

The loop is: edit `tag-bins.json`, run the validator, re-run the fixture.

```bash
python3 vocabulary/validate_vocabulary.py
python3 vocabulary/render_tags.py vocabulary/examples/late-night-trap.json
```

The validator checks schema conformance, duplicate ids, `render_order` coverage, comma-free
labels, resolvable `excludes` references, satisfiable selection limits, and defaults that fit
within a bin's maximum. It exits non-zero on error, so it can gate a commit.

Two things are deliberately *not* in the vocabulary:

- **Numeric values that are not tags.** BPM and duration are slider values that *render into*
  a tag; they are not options. Duration lives in the prompt's `metadata`, not in a bin.
- **Anything the user must be able to say freely.** Artist exclusions, reference tracks and
  unusual production descriptions belong in `combo_free` bins or the prompt's `notes`. A
  controlled vocabulary that cannot express the request is worse than a text box.

## 9. Open questions

- **How large should the budget be?** It sits at 64, clear of a full selection, so it now truncates
  only genuinely excessive lists. The number should still be tuned by measuring tag-count against
  compliance outcomes on a gauge rather than by taste, and that gauge is not built.
- **Does tag order matter to the model?** The design assumes only weakly, and fixes the order
  for hash stability. Worth testing: shuffle the same tags and compare compliance rates.
- **Should bins be conditionally shown?** Several are meaningless together (a `drum_machine`
  bin for an orchestral brief). Hiding by genre would shorten the form but risks hiding an
  option the user wants; the current design shows everything and uses conflicts instead.
- **How should option labels be localised?** Labels are the tag text sent to an English-first
  model, so translating the UI must not translate the labels — that needs a separate
  display-label field if it is ever wanted.
