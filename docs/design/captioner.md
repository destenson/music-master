# The captioner: what audio description entails

Status: plan, not built. Companion to [`compliance-architecture.md`](compliance-architecture.md),
[`evidence-classes.md`](evidence-classes.md) and [`ui-plan.md`](ui-plan.md).

## 1. What it unblocks

A Jev-like model takes text only, so every audio requirement has to become text before it can be
judged. Measurement covers the mechanical half. **Description covers the semantic half, and it is
the largest single block of verdicts currently reported as `unverified`.**

| Requirement | Today | With a captioner |
| --- | --- | --- |
| Genre fidelity | `unverified` | score over the genre bin, against the selection |
| Production character, era | `unverified` | caption + score over production/space/timbre bins |
| Instrumentation audible | `unverified` (stems only) | score over the instrument bins |
| Vocal character | partial (harmonicity only) | score over lead_vocal / vocal_delivery |
| Mood, energy | `unverified` | score over the mood bin |
| Caption ↔ lyric consistency | deferred to the oracle | oracle question over the caption and the lyrics |
| No-imitation policy | `unverified` | oracle question over the caption (see §9) |

That is roughly ten requirement classes, which is what makes this worth doing before the UI: it is
the difference between a report with four rows and a report with fourteen.

## 2. Why not just use the generator's own audio understanding

ACE-Step 1.5 advertises audio understanding — extract BPM, key, time signature and a caption — and
automatic quality scoring. It is already on disk and free. It is also the generator grading its own
homework, which is why the design admits it only as `generator_self_report`: a model that is
conditioned on metadata and then asked to read metadata back can agree with itself about audio that
does not match the brief.

A third-party captioner is worth building because it is **independent**: different model family,
different training data, no shared conditioning pathway with ACE-Step. Independence, not accuracy, is
the reason to add one. It is still a model, and §6 and
[`evidence-classes.md`](evidence-classes.md) say what that costs us.

## 3. What it must produce: two outputs, not one

The tempting design is "ask a model for a paragraph and give the paragraph to Jev". That produces an
unauditable artifact: a verdict resting on one sentence nobody can check, about audio nobody kept.
It also throws away the one thing we already have — **the captioner's label set is our tag
vocabulary.** 792 options, each an auditable claim.

So the captioner produces two things:

**A. A structured score matrix against the vocabulary.** For each bin in scope, a score per candidate
option, so the audio's own answer is directly comparable to what the spec asked for:

```jsonc
"structured": {
  "genre":       { "rap_metal": 0.41, "nu_metal": 0.29, "rap_rock": 0.18, "metal": 0.12 },
  "lead_vocal":  { "male_rap_vocals": 0.52, "spoken_word_vocals": 0.27, "male_tenor_vocals": 0.11 },
  "harmony":     { "distorted_guitar": 0.38, "clean_electric_guitar": 0.33, "piano": 0.16 },
  "mood":        { "aggressive": 0.44, "defiant": 0.31, "urgent": 0.19 }
}
```

**B. A short free caption**, for the holistic judgments that do not decompose — genre, mood,
production era, vibe — and as the text Jev reads for consistency and policy questions:

```
"Relentless rap metal at a driving tempo: distorted downtuned guitar riffing over a busy
live drum kit and fingerstyle bass, shouted male vocals answered by gang backing, dry
close production with little reverb."
```

The point of A is that it is **contrastive**: it answers "did we get the distorted guitar we asked
for, rather than the clean one?" instead of "is this good?". The point of B is that some judgments
are not a score over options, and pretending otherwise would be worse than a sentence.

**Scoring is against candidates, not all 792 options.** Per bin, score only the selected options plus
that bin's most plausible alternatives — a shortlist built in code, for the same reason the generator
picks from a shortlist: fine-grained discrimination degrades as the candidate set grows, and the
question we actually care about is whether the *asked-for* option beat its nearest competitors.

## 4. Granularity: per section, in windows

Music captioners are trained on short clips — MusicCaps, the standard captioning corpus behind
LP-MusicCaps, is built from 10-second excerpts. So windowed, per-section description is not a
workaround; it is what the models are actually good at.

- **Per section**, using the section boundaries already in `composition.json`, with a 10–20 second
  window placed inside each section (skipping the first and last bar, which are transition, not
  content).
- **Whole-song** as well, from 2–3 windows, for the caption that goes to the oracle.
- This also gives something a whole-song caption cannot: the **verse/chorus contrast in words**. The
  nu-metal brief asked for a sung chorus over a rapped verse; a caption per section can say whether
  that happened, and a single whole-song caption cannot.

Cost: 8–12 windows per song instead of 1, which is the whole cost argument for keeping the models
small.

## 5. Models, and what each is actually good at

| Option | Size | What it gives | Honest assessment |
| --- | --- | --- | --- |
| **CLAP** (audio-text embedding) | ~600 MB–1.5 GB | scores any text against audio, so it scores *our options* | the right engine for output A. Trained on coarse captions, so reliable on genre, mood, vocal presence and instrument families; poor on fine-grained production phrases |
| **LP-MusicCaps** (BART captioner) | ~0.5–1 GB | a music caption trained on MusicCaps | the right engine for output B. Purpose-built, small, fast, and trained on exactly this input shape |
| **MERT / MERT2** + a probe head | 95M–330M + head | tag probabilities on a *fixed* label set | strong on coarse genre (our research notes 91.72% GTZAN genre on MERT2-30s) but the label set is not ours, so it cannot answer about our options without fine-tuning |
| **Qwen2-Audio / Qwen2.5-Omni** (7B) | ~15 GB fp16 | open-ended description and question answering | the most capable and the most expensive: 15 GB against 12.7 GB of free VRAM, so 4-bit or offload, and seconds per window. Deferred, not rejected |

**Recommendation: CLAP + LP-MusicCaps.** Together ~2–3 GB, both fast, and between them they cover
both outputs. Qwen2-Audio stays on the list as a later upgrade for the questions CLAP and
LP-MusicCaps cannot reach, because a 7B audio-LLM can answer a *specific* question ("is a
synthesizer audible here?") that a captioner will simply not mention.

There is no music captioner or CLAP checkpoint on disk today. This is the one component that requires
a download, and the disk situation has a clean answer in §10.

## 6. The trust problem, stated plainly

A captioner is a model, so its output is **not evidence of the same kind as a measurement.** The
failure mode is specific and dangerous: the captioner hallucinates "distorted guitars", Jev reads the
caption, Jev returns 0.95, the report shows a green tick for a requirement that was never actually
checked. That is the exact failure the whole project exists to prevent, reintroduced through a new
door.

The rules that follow are set out in [`evidence-classes.md`](evidence-classes.md) and summarised here:

1. Description is the **lowest class of evidence**. It may never be the sole support for a `met` on a
   hard requirement.
2. A captioner claim that **overlaps a deterministic measurement** must agree with it. Caption says
   "sparse arrangement", onset density says otherwise → the disagreement is the finding, and it routes
   to review.
3. A requirement may be decided on description only for the classes where the captioner has **passed
   its gauge** (see §7), and the report records which captioner and which version.
4. Everything else stays `unverified`, with the caption shown as a hint rather than a verdict.

## 7. The gauge: how we would know it works

This is the part that makes the difference between a captioner and a vibe. It is also cheap, because
we already have ten renders and two songs.

1. **Hand-label a gauge set.** For the existing takes: coarse genre, vocal presence and type,
   instrument families, broad production character, and the absence claims. Roughly 10 takes ×
   6 fields = 60 labels, an afternoon's work with the takes already on disk.
2. **Measure per class.** Agreement per requirement class, so the answer is "CLAP is usable for genre
   and vocal type, not for production era" rather than a single useless accuracy number.
3. **Measure disagreement with deterministic facts for free.** Tempo, dynamics, vocal presence,
   onset density and clipping are already measured. Every captioner run produces a free calibration
   signal: does the caption contradict a number we trust? This costs nothing and is the most
   objective test available.
4. **Set the gate per class.** A class below the gate stays `unverified` and says so in its reason.
   The gate is a config value, not a constant, and it is re-measured when the captioner changes.
5. **Re-run the gauge on every model change**, exactly as the Jev thresholds are pinned to a model
   version.

## 8. Integration

**The fact sheet** gains one block, and nothing else in the pipeline changes shape:

```jsonc
"audio_description": {
  "captioner": { "id": "clap+lp-music-caps", "versions": {...}, "weights_sha256": {...} },
  "free_caption": "…",
  "per_section": [ { "label": "Verse 1", "window_s": [12.0, 20.0], "caption": "…" } ],
  "structured": { "genre": {…}, "lead_vocal": {…}, "harmony": {…} },
  "detector_agreement": { "tempo": true, "dynamics": false, "vocal_presence": true },
  "abstentions": ["production era: captioner below gate"]
}
```

**The compliance battery** gains questions that point at it, in the shape the design already uses:
one `score` per dimension against the caption and the structured scores, one `noul` per requirement
phrased as the exact condition, and the caption/lyric consistency questions now have a real caption to
compare against.

**The report** gains a per-verdict `evidence_class` field, so a reader can see at a glance whether a
tick came from a measurement, a description, or an oracle reading a description.

**The UI** gains a caption panel on the takes view, and — the important consequence — the
`UNVERIFIED` block gets shorter while the `decided by description` count becomes visible. That count
is the thing to watch, because it is the one that can be inflated.

## 9. What it must not be used for

- **Absence claims.** "No Synthesizers" is a positive-detection problem, and a captioner that simply
  fails to mention synths proves nothing. The `avoid` bin's selections stay `unverified` or route to
  review until the gauge shows a targeted question can detect presence reliably. This is a
  deliberate limitation on the newest feature, and the honest one.
- **Fine-grained production phrases.** "Muted Funk Chops" versus "Palm-Muted Guitar" is not a
  distinction CLAP was trained to make. Fine-grained bins are scored for information and reported
  `uncertain`, not treated as decidable.
- **Anything a measurement already answers.** Tempo, key, duration, loudness. A caption saying "fast"
  next to a measured 92 BPM is at best redundant and at worst a distraction in the oracle's state.
- **Quality.** "Is this good?" is not a requirement class and no captioner answers it.

## 10. Cost and environment

- **Disk is the constraint, and it has a clean answer. `/` has 22 GB free and `/mnt/ssd4g` has 30 GB,
  but `/mnt/synas` has 6.1 TB free.** Model weights go to the NAS, with `HF_HOME` pointed at it or
  symlinks; nothing new lands on the root filesystem. First load from a network mount costs a few
  seconds per gigabyte, which is acceptable once per session and avoidable by caching the small
  models locally if space ever frees up.
- **The GPU is shared with ComfyUI**, which is often holding several GB. CLAP and LP-MusicCaps are
  small enough to fit alongside, but captioning should be sequenced after a render batch rather than
  competing with it, and both should run acceptably on CPU for a handful of windows.
- **Cost per song:** 8–12 windows × (one embedding pass + one short generation) is seconds on GPU,
  tens of seconds on CPU. Trivial against a 60-second render, and it happens once per take.

## 11. Acceptance criteria

- A captioner adapter exists with declared capabilities: which bins it will score, which requirement
  classes its gauge passed, and its model identity and weight hashes.
- It runs on all ten existing takes and writes `audio_description` into each fact sheet.
- The gauge is labelled and measured, and the per-class results are recorded in the repo.
- Detector agreement is measured and reported; a caption that contradicts a trusted measurement is a
  first-class finding, not a footnote.
- At least genre, vocal presence/type and instrument-family classes move from `unverified` to decided
  — or the gauge says they cannot, and the doc records why.
- Every requirement still `unverified` after this work has a stated missing channel.
- No requirement's verdict rests on caption evidence alone unless its class passed the gauge.

## 12. Phasing

| Step | Content | Gate |
| --- | --- | --- |
| **C0** | `musicmaster/describe.py` adapter + capability declaration; one model wired | runs on one take, writes a fact sheet block |
| **C1** | Gauge set labelled for the ten takes; per-class measurement | per-class numbers exist, and the gate is set from them |
| **C2** | Structured scoring over the vocabulary, shortlisted per bin | scores are contrastive and reproducible across runs |
| **C3** | Free caption per section and whole-song | captions stable across repeated runs on the same window |
| **C4** | Detector-agreement check and the evidence-class field in the report | a contradiction is detected and routed |
| **C5** | Oracle questions over the description; `unverified` count falls | the count is asserted in a test |

C0–C1 are the honest minimum: an adapter and a gauge. C2–C3 are the useful part. C5 is where the
report finally gets shorter.

## 13. Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Hallucinated description becomes a green tick | the exact failure the project exists to prevent | evidence classes; description never sole evidence for a hard requirement |
| Fine-grained tags over-claimed | a confident score on a distinction the model cannot make | capability declaration per bin; shortlists; fine-grained reported `uncertain` |
| Absence claims falsely satisfied | a policy requirement passes because a caption stayed silent | absence stays `unverified` pending a targeted detector and gauge |
| Gauge too small | per-class accuracy on 10 takes is thin | label more takes as they are rendered; report confidence intervals, not a point estimate |
| Model drift on upgrade | thresholds and gates silently rot | pin versions and weight hashes; re-run the gauge on any change |
| Cost creep | per-section description turns one inference into twelve | bounded windows; caption after renders, not during; CPU fallback |
| A captioner that describes the *prompt* rather than the audio | catastrophic and easy to miss | always caption a shuffled/reversed control excerpt in the gauge, and check that the caption changes |
