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
| [`docs/research/jev-and-decision-models.md`](docs/research/jev-and-decision-models.md) | What Jev is, what it measures, what the sibling projects already learned, and the open alternatives (including self-hosted) |
| [`docs/research/music-generation-landscape.md`](docs/research/music-generation-landscape.md) | Open lyrics-to-song and text-to-music models, controllability, and the MIR tools that make audio judgeable as text |

## Schemas

- [`schemas/prompt.schema.json`](schemas/prompt.schema.json) — the canonical generation
  request: style, metadata, form, lyric reference, negative conditioning, target identity and
  seed. The input artifact.
- [`schemas/song-bundle.schema.json`](schemas/song-bundle.schema.json) — the manifest: content
  hashes, per-stage seeds, dependency edges and environment, so any artifact can be re-derived
  and any output traced to its inputs.
- [`schemas/requirement-spec.schema.json`](schemas/requirement-spec.schema.json) — the typed
  interpretation of a brief, where every requirement names its checker and its provenance.
- [`schemas/compliance-report.schema.json`](schemas/compliance-report.schema.json) — the
  per-requirement verdict with evidence; `unverified` is distinct from `met`.

The prompt, manifest, spec and report schemas are written. `composition.json` and `lyrics.md`
are described in the design but do not yet have schemas of their own — by intent, since the
prompt is the input to the generator and is being specified first.

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
