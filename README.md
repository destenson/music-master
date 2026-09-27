# music-master

A design for a lyrics-and-composition generator that proves its output meets the brief.

The brief can ask for anything: a theme, a mood, a genre, a tempo, a key, a structure, a
language, an explicitness limit, "don't sound like Bon Iver". Music Master generates the
song, then returns it with a **compliance report** that says, per requirement, what was
checked, on what evidence, and whether it passed — and lists the requirements it could not
satisfy rather than quietly ignoring them.

Status: **design only.** No code yet.

## The idea in one paragraph

Requirements split into mechanical ones that code computes exactly (duration, BPM, key,
syllables, rhyme, banned words, loudness) and semantic ones that are irreducibly judgments
(theme, mood, genre, hook, cliché, imitation, explicitness). The mechanical half never
touches a model. The semantic half goes to a **Jev-like System One model** — typed
questions over a state, returning calibrated probabilities rather than prose — because code
can consume the answers directly. The catch is that such a model takes *text only*, so it
cannot hear the track; the design therefore renders every audio artifact into text
surrogates (measured MIR facts, chord transcription, vocal transcript, music caption) and
judges those. And because a requirement that can only be checked after synthesis is
expensive to fail, the generation path is chosen so most requirements become observable as
early as possible.

## What it produces

A song is a **directory of artifacts**, not an audio file. The audio is the expensive,
opaque, hard-to-diff output of a stochastic process; the prompt, the lyrics and the
composition are cheap, textual and diffable. So they are the artifacts of record and the
audio is a build product derived from them — which is what makes the whole thing
reproducible.

```
songs/<song_id>/
  brief.md  spec.json  composition.json  lyrics.md  prompt.json
  rendered/ace_step_1_5.json   audio.wav   report.json   manifest.json
```

Each of the four generated artifacts is built by its own independently runnable stage, so the
lyrics can be rewritten and the audio re-rendered without re-planning the composition. The
**prompt is the first artifact to get right**, because it is the input to the generator and
therefore the thing that determines the output: it is a canonical, model-agnostic object
rather than a string, it is rendered per target by the generator adapter, and it is fully
checkable *before* any GPU work.

That split also makes an important distinction explicit. **Intent fidelity** — does the prompt
faithfully encode the brief? — is cheap and exact, because the prompt is text. **Realization
fidelity** — does the audio realize the prompt? — is expensive and partly unverifiable. Prompt
verification does not imply audio compliance, so the compliance battery runs twice and reports
both.

## Documents

| Document | What it covers |
| --- | --- |
| [`docs/design/compliance-architecture.md`](docs/design/compliance-architecture.md) | The design: the artifact bundle, the prompt artifact, stages, requirement taxonomy, the compliance battery, gating policy, repair loop, risks, validation plan |
| [`docs/design/tag-vocabulary.md`](docs/design/tag-vocabulary.md) | The tag bins: what a bin declares, the UI controls built from them, how selections render into the comma-separated prompt, and how the vocabulary keeps the UI, the prompt and the compliance battery in step |
| [`docs/design/lyric-templates.md`](docs/design/lyric-templates.md) | Song structures and rhyme schemes as a contract: the writing brief handed to the lyric generator, the bar plan handed to the composer, and the conformance check on the result |
| [`docs/design/ui-plan.md`](docs/design/ui-plan.md) | The front-end plan: readiness, design principles, information architecture, the core/UI seam, the four surfaces that matter, phasing from core extraction to live verification |
| [`docs/design/captioner.md`](docs/design/captioner.md) | The captioner: what audio description entails, the two outputs it must produce, model choices, the gauge that decides what it may decide, and what it must not be used for |
| [`docs/design/evidence-classes.md`](docs/design/evidence-classes.md) | Measurement, description, self-report and oracle: what each may decide alone, why description is never sole evidence for a hard requirement, and the two counts the report must carry |
| [`docs/research/jev-and-decision-models.md`](docs/research/jev-and-decision-models.md) | What Jev is, what it measures, what the sibling projects already learned, and the open alternatives (including self-hosted) |
| [`docs/research/music-generation-landscape.md`](docs/research/music-generation-landscape.md) | Open lyrics-to-song and text-to-music models, controllability, and the MIR tools that make audio judgeable as text |
| [`docs/research/prompting-rules.md`](docs/research/prompting-rules.md) | What the generator's own tutorial says about prompting: the caption/metadata split, structure tags, caption↔lyric consistency, control boundaries, and the three sources of randomness |
| [`docs/research/suno-prompting-principles.md`](docs/research/suno-prompting-principles.md) | The "universal" prompting ideas the ACE-Step guide points at |

## The tag vocabulary

The tag string is **rendered from selections**, not typed. 30 bins of properties — genre,
scene, tempo, drums, bass, harmonies, synths, vocals, delivery, production, timbre, mood,
exclusions and more — with **743 options** between them, each labelled with the exact tag text it
emits. The lyrics have their own vocabulary too: **59 section tags** across 5 pools, with a
grammar and the caption/lyric consistency rules.

```bash
python3 vocabulary/validate_vocabulary.py     # bins, ids, labels, references, limits, tags
python3 vocabulary/render_tags.py vocabulary/examples/late-night-trap.json
python3 vocabulary/check_lyrics.py vocabulary/examples/lyrics-late-night-trap.md \
    --selections=vocabulary/examples/late-night-trap.json
python3 vocabulary/check_lyrics.py --self-test
```

Rendering the motivating example yields 13 tags, and the renderer reproduces the fixture
exactly. It is 13 rather than 14 because the example's `95 BPM` was **moved out of the caption
into `metadata.bpm`** — the generator's own guide says tempo, key and time signature belong in
the metadata parameters and should not be written into the caption, so those bins are
metadata-only.

The lyrics fixtures are the real paired example — the caption and lyrics that ship together with
the packaged ComfyUI template. Running the checker on them found: no blank line between sections
(four warnings, against explicit guidance), no modifiers or performance tags anywhere, almost no
internal rhyme or alliteration (it reads as a technical jingle rather than a crafted lyric), and
heavy technical jargon the model is likely to slur.

It also caught a modelling error in the checker itself. Counting syllables per printed line flagged
ten verse lines as over-long; counting per **phrase** — `Open up the canvas` / `blank slate on my
screen` is 6/5, not 11 — flags the two lines that genuinely have no internal break. Cadence splits
lines, so the line is the wrong unit. Cross-line embedded rhyme is now deliberately not reported at
all: stress and vowel length decide whether two syllables rhyme and spelling encodes neither, so
that number would have been an artifact.

## Templates

Writing is easier and checkable when the shape is chosen first. **15 song structures**, **13
rhyme schemes** and **6 delivery profiles** are held as data, and each template is used four ways —
as a brief, as a bar plan, as a time budget, and as a conformance check:

```bash
python3 vocabulary/structure_templates.py --list
python3 vocabulary/structure_templates.py --template=pop_standard --brief --bpm=95 --duration=180
python3 vocabulary/structure_templates.py --template=pop_standard --timeline --bpm=95 --duration=180
python3 vocabulary/check_lyrics.py lyrics.md --template=pop_standard --bpm=95
```

A template is a contract rather than a label: it carries the section order, bar counts, lines per
section, the rhyme scheme each section is written to, an energy arc, and where the hook is. The
`structure` bin in the vocabulary points at one via `template_ref`, so choosing a form in the UI is
what selects the contract. Section sequence and line counts are checked exactly; rhyme conformance
is advisory, because the detector is spelling-based and demonstrably misses real rhymes.

### The time budget

A three-minute song is not three minutes of words, so the plan separates them and each section gets
a **budget** (`lines x band`, what the writer is asked for) and a **ceiling** (`singable seconds x
syllables per second`, what the clock allows). The budget is clipped by the ceiling, because stating
a band the section cannot physically hold is advice that is wrong on its face — a 4-bar pre-chorus
with 4 lines cannot carry 10 syllables a line at 95 BPM, so the brief says "at most 8 here".

The band is delivery-dependent and lives in `delivery-rates.json`: a caption containing "Male Rap
Vocals" gets 8–16 syllables per line and a 6.5/s ceiling, where a ballad gets 5–9 and 2.6. Intros,
outros, interludes and solos are instrumental by construction, and writing words into one is an
**error** — which is exactly what running the real fixture against `pop_standard` produced:

```
ERROR: [Outro]: 36 syllables written into an instrumental section (10.1s); there is no vocal there
```

The timeline also reports **density**, which catches what scaling does: filling an exact duration
stretches every section, so `pop_standard` stretched to three minutes at 95 BPM comes out with five
sparse sections at 1.58 syllables/s against a comfortable 2.3. Hitting a duration and keeping a
density are different goals.

Adding a bin is a four-part change — options, a control, a render position, and a checker —
because a bin is simultaneously a UI element, a prompt field and a compliance obligation.
`maps_to` is the field that keeps the three in step, and it is orthogonal to `emits_tag`, so a
bin like `tempo` can create a requirement without contributing a tag.

## Schemas

- [`schemas/prompt.schema.json`](schemas/prompt.schema.json) — the canonical generation
  request: style, metadata, form, lyric reference, negative conditioning, target identity and
  seed. The input artifact.
- [`schemas/song-bundle.schema.json`](schemas/song-bundle.schema.json) — the manifest: content
  hashes, per-stage seeds, dependency edges and environment, so any artifact can be re-derived
  and any output traced to its inputs.
- [`schemas/tag-vocabulary.schema.json`](schemas/tag-vocabulary.schema.json) — the shape of the
  bin vocabulary: bins, controls, priorities, render positions, options and cautions.
- [`schemas/section-tags.schema.json`](schemas/section-tags.schema.json) — the lyric metatag
  vocabulary and its grammar, including the caption/lyric consistency rules.
- [`schemas/structure-templates.schema.json`](schemas/structure-templates.schema.json) — the shape
  of a song-structure template: sections, bars, lines, rhyme scheme, energy and hooks.
- [`schemas/rhyme-schemes.schema.json`](schemas/rhyme-schemes.schema.json) — the rhyme-pattern
  library and each scheme's strictness.
- [`schemas/delivery-rates.schema.json`](schemas/delivery-rates.schema.json) — the delivery
  profiles: syllables per line, and the rate ceilings the time budget is built from.
- [`schemas/requirement-spec.schema.json`](schemas/requirement-spec.schema.json) — the typed
  interpretation of a brief, where every requirement names its checker and its provenance.
- [`schemas/compliance-report.schema.json`](schemas/compliance-report.schema.json) — the
  per-requirement verdict with evidence; `unverified` is distinct from `met`.

The prompt, manifest, vocabulary, spec and report schemas are written. `composition.json` and
`lyrics.md` are described in the design but do not yet have schemas of their own — by intent,
since the prompt is the input to the generator and is being specified first.

## Spikes

- [`spikes/measurement_probe.py`](spikes/measurement_probe.py) — synthesises a known 92 BPM
  F# minor signal and measures it back with the libraries already installed, to check that
  the design's deterministic layer is real. Measured 92.29 BPM and an exact key. The run
  also documents two failure modes worth knowing: librosa needs a writable
  `NUMBA_CACHE_DIR`, and a naive beat tracker returned a confident `0.0 BPM`.

  ```bash
  NUMBA_CACHE_DIR=spikes/.numba \
    /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/measurement_probe.py
  ```

- [`spikes/pyodide_text_core/`](spikes/pyodide_text_core/README.md) — runs the text core under a
  WebAssembly CPython, to check that a static SPA can use the same implementation the CLI does
  instead of a rewrite that drifts. Seven CLI invocations came back **byte-identical** between native
  CPython 3.12.3 and Pyodide 3.14.2, and the full per-caret lyric check measured ~12 ms median / ~17 ms
  p95 — about twice native, and inside a frame. It also pins the invariant that makes it possible:
  the text tier imports nothing outside the standard library.

  ```bash
  cd spikes/pyodide_text_core && npm install
  node parity.mjs      # correctness, byte-for-byte
  node latency.mjs     # is the per-caret check inside a frame budget?
  ```

## Target model

**ACE-Step 1.5** (XL turbo) is the reference generator, driven through its ComfyUI graph. All
four of its weights are on disk and this machine has already produced output from it. It
accepts `bpm`, `duration`, `timesignature`, `keyscale`, `language` and `seed` as conditioning
parameters, which is what lets several mechanical requirements be *requested* rather than
only measured — but that conditioning is injected as a text prompt, not a hard constraint, so
every conditioned requirement is still verified afterwards.

The composer sits behind a `MusicGenerator` adapter whose capabilities are declared, and a
model swap that would weaken any requirement's enforcement mode is a hard error rather than a
silent downgrade. See `docs/design/compliance-architecture.md` §5.8.

## The three rules that matter most

1. **Never ask the model something code can compute exactly.** Counting, arithmetic, dates
   and numeric comparison are documented weak spots.
2. **Never consume a `choice` without a companion `noul`.** A choice settles *which* of
   your options; a noul settles *whether* — and can be low for all of them.
3. **Uncertainty is an outcome, not a pass.** A probability in the uncertain band is
   reported as uncertain and routed to repair or review.

## Related work on this machine

Prior Jev integrations live in `~/src/llamas` (PRP-206),
`~/src/lance` (PRP-J01 and `spikes/jev`), `~/src/ai-experiments/opencaw`, and
`~/src/TheoLeeCJ--SemIf-OpenJev` (an open, self-hostable reproduction of the same interface
pattern). The research document summarises what each measured and what is worth copying.
