# Prompting rules from the model's own guide

[ACE-Step 1.5 Ultimate Guide](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/Tutorial.md),
read directly. The guide is written by the model's author and is unusually explicit about the
model's limits, so it is treated here as primary evidence rather than as marketing: several of
its statements contradict what a reasonable designer would otherwise assume, and two of them
correct decisions already made in this design.

The guide also points at a Suno tutorial for "universal prompting ideas". Those are covered
separately in [`suno-prompting-principles.md`](suno-prompting-principles.md); this document is
what ACE-Step itself says.

## 1. The mental model it asks you to adopt

The guide is built on the elephant-rider metaphor: you can give the model direction, but not
precise, instant execution. Two claims follow, and both matter for a compliance system:

- **Text is a dimensionally reduced abstraction of audio.** "What's the most precise control?
  You input the expected audio, and the model returns it unchanged. But as long as you're using
  text descriptions, references, prompts — the model will have room to play. This isn't a bug,
  it's the nature of things." So a text-only compliance check cannot be complete in principle,
  which is exactly why the design keeps deterministic measurement for the checkable half.
- **Caption is a starting point, not an endpoint.** "Don't pursue perfect descriptions. Write a
  general direction first, then iterate based on results." The design's repair loop is that
  iteration, made explicit and recorded.

The guide is also explicit that this is **human-centered generation**, not one-click: the
intended workflow is throw out seeds, keep what is interesting, then adjust with prompt edits,
 **Cover** (keep structure, change details), **Repaint** (local edits) and **Add Layer**. That is
a loop, and it is the reason artifacts and reproducibility matter more than a single perfect
prompt.

## 2. The two brains, and the case for turning the planner off

ACE-Step 1.5 is a hybrid: a **5Hz LM planner** and a **DiT executor**.

```
User Input → [5Hz LM] → Semantic Blueprint → [DiT] → Audio
                 ↓
          Metadata Inference · Caption Optimization · Structure Planning
```

The LM infers metadata by Chain-of-Thought, expands your caption, and generates semantic audio
codes. Crucially, **it is optional**: "If you're very clear about what you want, or already have
a clear planning goal — you can completely skip the LM planning step by not using `thinking`
mode... Here, you replace the LM's work — you become the planner yourself."

**Design consequence.** Music Master *is* a planner: it produces `composition.json`,
`lyrics.md` and `prompt.json` deliberately, with seeds and hashes, before anything is rendered.
So on the reproducible path the LM planner is redundant at best and a source of
non-determinism at worst. The design should **disable CoT planning for the reproducible lane**
and offer it only as an explicit "explore" mode, where its expansions are captured as a
candidate prompt rather than applied silently inside the render. The ComfyUI node exposes this
as `generate_audio_codes`.

There is a second reason beyond determinism: the guide warns that "LM has weaker caption
generalization than DiT. When prompting is unreasonable, the chance of pleasant surprises is
smaller." A silently-rewritten caption is a caption nobody can check.

## 3. What you can control

Three families, per the guide: **input control** (caption, lyrics, metadata, audio references),
**inference hyperparameters** (DiT and LM settings), and **random factors** (seed, LM
temperature, SDE noise). The design's `prompt.json` already separates the first and second from
the third; the guide confirms that separation is the right one and supplies the specific fields.

## 4. Caption rules

The guide calls the caption "the most important factor affecting generated music", accepts
comma-separated tags, plain style words or natural language ("we've trained to be compatible
with various formats, ensuring text format doesn't significantly affect model performance"), and
gives nine canonical dimensions:

| Dimension | Examples |
| --- | --- |
| Style / Genre | pop, rock, jazz, hip-hop, R&B, lo-fi, synthwave |
| Emotion / Atmosphere | melancholic, uplifting, dreamy, dark, nostalgic, intimate |
| Instruments | acoustic guitar, piano, synth pads, 808 drums, strings, brass |
| Timbre Texture | warm, bright, crisp, muddy, airy, punchy, lush, raw, polished |
| Era Reference | 80s synth-pop, 90s grunge, 2010s EDM, vintage soul |
| Production Style | lo-fi, high-fidelity, live recording, studio-polished, bedroom pop |
| Vocal Characteristics | female vocal, breathy, powerful, falsetto, raspy, choir |
| Speed / Rhythm | slow tempo, mid-tempo, fast-paced, groovy, driving, laid-back |
| Structure Hints | building intro, catchy chorus, dramatic bridge, fade-out ending |

And seven practical principles, which the design's vocabulary and linter both encode:

1. **Specific beats vague.** "sad piano ballad with female breathy vocal" over "a sad song".
2. **Combine multiple dimensions.** One dimension gives the model too much room.
3. **Use references well** — "in the style of 80s synthwave". (The design treats a *named
   living artist* as a policy question, not a style hint.)
4. **Texture words are useful** — they influence mixing and timbre.
5. **Don't pursue perfect descriptions.**
6. **Granularity determines freedom** — less description, more randomness; more description,
   more constraint. This is a user-facing control, not a defect.
7. **Avoid conflicting words.**

### 4.1 The correction that matters: metadata does not belong in the caption

> "**Recommended Practice**: Don't write tempo, BPM, key, and other metadata information in
> Caption. These should be set through dedicated metadata parameters (`bpm`, `keyscale`,
> `timesignature`, etc.), not described in Caption. Caption should focus on style, emotion,
> instruments, timbre, and other musical characteristics."

The motivating example prompt for this project is
`Late Night Trap, 95 BPM, Heavy 808 Bass, ...` — it puts `95 BPM` in the caption. Per the model's
own guidance that is wrong, and the design has been changed: the tempo bin no longer emits its
number as a tag, and BPM, key and time signature render into `metadata` only. See
[`tag-vocabulary.md`](../design/tag-vocabulary.md).

### 4.2 Conflicts, and the two sanctioned remedies

Conflicting style combinations "easily lead to degraded output" — the guide's example is wanting
"classical strings" and "hardcore metal" at once. It offers two ways out, and both are features
the design should expose rather than errors it should merely block:

- **Repetition reinforcement** — repeat the element you want to dominate.
- **Conflict to evolution** — turn the conflict into a *temporal* one: "Start with soft strings,
  middle becomes noisy dynamic metal rock, end turns to hip-hop." This is a structure-level
  solution, and it lands in the lyric section tags, not the caption.

## 5. Lyrics rules

"Caption describes the music's overall portrait; Lyrics is the music's temporal script." The
lyrics field carries far more than words: the text, **structure tags**, vocal-style hints,
instrumental sections, and energy changes.

### 5.1 Structure tags are the strongest tool — and the easiest to misuse

The guide calls them "the most powerful tool in Lyrics" and provides the canonical set:
`[Intro]`, `[Verse]`/`[Verse 1]`, `[Pre-Chorus]`, `[Chorus]`, `[Bridge]`, `[Outro]`, plus dynamic
(`[Build]`, `[Drop]`, `[Breakdown]`), instrumental (`[Instrumental]`, `[Guitar Solo]`,
`[Piano Interlude]`) and special (`[Fade Out]`, `[Silence]`) tags.

Modifiers attach with a hyphen, and **only one**:

```
✅  [Chorus - anthemic]
❌  [Chorus - anthemic - stacked harmonies - high energy - powerful - epic]
```

Two stated risks of stacking: "the model might mistake tag content as lyrics to sing", and "too
many instructions confuse the model". The design therefore encodes the grammar as data
(`vocabulary/section-tags.json`, `max_modifiers: 1`) and validates every bracket before
rendering — an unrecognised tag may be sung, so it is a defect, not a style choice.

### 5.2 Caption and lyrics must tell the same story

> "**Models are not good at resolving conflicts.** If descriptions in Caption and Lyrics
> contradict, the model gets confused and output quality decreases."

The guide gives a checklist: instruments in caption ↔ instrumental section tags; emotion in
caption ↔ energy tags; vocal description ↔ vocal control tags. The design turns that checklist
into `consistency` rules in the section-tag file, runs the exactly-checkable part in code (no
vocal tag when the lead vocal is Instrumental), and defers the semantic part to the oracle.

### 5.3 Writing lyric text

- **6–10 syllables per line**, and keep lines in the same position across sections within
  **±1–2 syllables**: "The model aligns syllables to beats — if one line has 6 syllables and the
  next has 14, rhythm becomes strange."
- **Uppercase means louder delivery**, used sparingly.
- **Parentheses mean background vocal or harmony** — "Content in parentheses is processed as
  background vocals or harmonies."
- **Extending vowels by repetition** ("Feeeling so aliiive") works but "effects are unstable,
  sometimes ignored or mispronounced."
- **Blank lines between sections**, so boundaries are unambiguous.
- Use `[Instrumental]` for purely instrumental music.

And five named anti-patterns for "AI-flavoured" lyrics: adjective stacking, rhyme chaos, blurred
section boundaries, no breathing room, and mixed metaphors. The guide's remedy for the last is
specific and checkable enough to ask the oracle about: **"Stick to one core metaphor per song,
exploring its multiple aspects."**

## 6. Metadata: control boundaries, and why tolerances are not optional

The guide is explicit that metadata parameters are "**guidance** rather than **precise
commands**", and describes the mechanism:

> The model doesn't mechanically execute `bpm=120`... Uses `120 BPM` as an **anchor point**,
> samples from distribution near this anchor, final result might be 118 or 122.

| Parameter | Reliable | Unreliable |
| --- | --- | --- |
| `bpm` | 60–180 common | extremes like 30 or 280, sparse data |
| `keyscale` | common keys (C, G, D, Am, Em) | rare keys "may be ignored or shifted" |
| `timesignature` | 4/4 most reliable; 3/4 and 6/8 usually OK | 5/4, 7/8 "advanced, effects vary by style" |
| `duration` | 30–60 s and 2–4 min stable | very long may repeat or lose structure |

This is the empirical justification for the design's `conditioned + verified` enforcement mode:
the parameter is a lever, the measurement is the verdict, and the tolerance is set from the
model's own documented spread rather than from a wish. It also justifies the `caution` field now
on the 5/4 and 7/8 options — the model's own documentation says they are unstable.

The guide adds a diagnostic worth automating: "If you manually set metadata but generation
results clearly don't match — check if there's conflict with Caption/Lyrics. For example, Caption
says 'slow ballad' but `bpm=160`."

## 7. Audio control is a different control surface

Three mechanisms, each with a different range: **reference audio** (VAE latents, temporal
information averaged, acts globally on timbre/mix/performance), **source audio** for Cover
(semantic structure: melody, rhythm, chords, orchestration), and **Repaint** (context-based local
completion, 3–90 s, supports infinite extension by chaining). The Base model adds `extract`,
`lego` and `complete`.

Design consequence: these are **task types**, and they belong in the prompt's target block
alongside the generator id — `text2music`, `cover`, `repaint`, `lego`, `extract`, `complete`.
The design's "lanes" were under-specified; this is the real control surface, and it changes what
the generator can be asked for at all ("add a bassline to my voice memo" is `lego`, not
`text2music`).

## 8. Reproducibility: a seed is necessary but not sufficient

The guide is unusually clear that randomness has three sources:

1. **DiT initial noise**, controlled by `seed`.
2. **LM sampling**, when `lm_temperature > 0` — "Same prompt, each sampling may choose different
   tokens."
3. **SDE noise**, when `infer_method = "sde"`.

So "fix the seed" alone does not reproduce a render. The design's reproducibility contract is
therefore amended: the prompt's target block records `infer_method` and the LM sampling settings
alongside the seed, and the reproducible lane uses `ode` with CoT planning disabled. The guide's
own advice for tuning — "we recommend fixing random factors when tuning — by setting a fixed
`seed` value" — is the same control-discipline the design's validation plan already required.

## 9. Screening: the model ships its own scorer

The guide recommends **large batch + automatic scoring**: generate `batch_size` 2/4/8, let
AutoGen keep producing batches, score automatically, then pick by hand. Its favourite metric is
the **DiT Lyrics Alignment Score**, which "evaluates the alignment degree between lyrics and
audio in generated audio".

This is valuable and dangerous in equal measure. Valuable, because it is a cheap first-pass
filter and it addresses — partially — the requirement this design had marked `unverified`
(`sung == written lyric`). Dangerous, because it is the generator scoring its own output, and the
guide notes precision limits elsewhere ("Audio to Caption... precision is limited"). So it is
admitted as a **screening signal and a `generator_self_report` field**, never as the authoritative
evidence for a requirement, and disagreement with independent measurement routes to review. That
is the same rule already applied to ACE-Step's audio understanding.

## 10. What this changes in Music Master

| Finding | Change |
| --- | --- |
| Metadata must not be in the caption | Tempo no longer emits `95 BPM`; tempo, key and time signature render to `metadata` only. `value_emits_tag` added; `emits_tag: false` on time signature and key |
| Nine caption dimensions | Added a **Timbre texture** bin; the other eight were already represented |
| One modifier per structure tag; unrecognised tags may be sung | New `vocabulary/section-tags.json` + schema, with `max_modifiers: 1`; every bracket is validated pre-render |
| Caption ↔ lyrics consistency is critical | `consistency` rules in the section-tag file; the mechanical one runs in code, the rest deferred to the oracle |
| 6–10 syllables per line, ±1–2 by position | Lyric gate updated from an arbitrary target to the model's own recommended band, applied positionally |
| Uppercase and parentheses carry meaning | Lyric parser treats them as delivery and backing-vocal markers, not formatting |
| Metaphor discipline | New oracle question: does the lyric mix unrelated core metaphors? |
| Metadata is an anchor, not a command | Tolerances set from the documented spread; `conditioned + verified` is now empirically justified rather than cautious |
| 5/4 and 7/8 are unstable | `caution` field on those options, surfaced in the UI and the pre-prompt check |
| Randomness has three sources | Target block records `infer_method` and LM sampling settings; reproducible lane uses `ode` |
| The LM planner is optional and we already have one | CoT planning disabled on the reproducible lane; offered only as an explicit explore mode whose output is a candidate prompt |
| Audio references, Cover, Repaint, lego, extract, complete | These are task types and belong in the target block; they widen what the generator can be asked to do |
| Conflicts have two sanctioned remedies | Repetition reinforcement and temporal evolution become UI affordances, not just blocked states |
| The model ships a lyrics-alignment scorer | Admitted as screening and self-report only, never as authoritative evidence |

## 11. Where the two guides disagree

Reading the [Suno principles](suno-prompting-principles.md) alongside ACE-Step's own guide
surfaces three genuine conflicts. All three resolve the same way, and the resolution is an
architectural constraint rather than a preference: **the canonical artifact stores intent; the
target adapter decides how to express it.**

| Question | ACE-Step 1.5 says | Suno practice says | Resolution |
| --- | --- | --- | --- |
| Where do BPM and key live? | In the metadata parameters, **not** the caption | In the style field, because Suno exposes no metadata fields | `metadata` stays canonical; the adapter renders it into metadata fields *or* into the caption string, depending on what the target supports |
| How are structure-tag modifiers written? | `[Chorus - anthemic]`, **one** modifier maximum | `[Chorus \| Anthemic]`, stacking several is common | The lyric artifact stores the section plus an ordered modifier list; the adapter renders the syntax and enforces the target's own maximum |
| Does tag order matter? | Not stated | Leading tokens are weighted more heavily; genre first is the consensus | Ordering is canonical *and* prioritised — the leading tags are exactly the ones the budget protects first, which is already how `render_order` and `priority` behave |

The third is a confirmation. The first two correct an assumption this design was carrying
implicitly: that there is one right way to express a prompt. There is not. There is one right way
to *record* it, and a per-target way to render it — the same conclusion the generator adapter
reached for capabilities (§5.8 of the design), arrived at from the opposite direction.

## 12. What the guide does not settle

- **Tag order.** ACE-Step's guide is silent, but the Suno consensus is that leading tokens are
  weighted more heavily and that genre belongs first. That is consistent with the design's
  canonical order, and it upgrades the reason for it: the order is chosen for priority, and
  happens to also make the hash stable.
- **Optimal tag count.** The guide says granularity determines freedom but gives no number.
  Community practice converges on 4–8 descriptors with roughly 20 as a ceiling, which suggests
  the design's budget of 14 is above the sweet spot. To be measured, not assumed.
## 13. Closing note

Also carried over from the Suno consensus, because each is cheap and mechanical:

- **End lyric lines on open vowels and liquids** where possible: the model matches phonemes to
  melody and will drop or slur consonant clusters.
- **A stock-phrase and overused-word list is a usable soft gate.** Names recurring across
  sources — ghost, ashes, chains, throne, shadow, ember, neon, midnight — plus rhyme pairs like
  fire/desire and pain/rain and the "3 AM" motif. Implemented as warnings in
  `vocabulary/lyric-cliches.json` and `check_lyrics.py`, because cliché is a judgement and the
  hard verdict belongs to the oracle's freshness score.
- **Prompt adherence decays over a long song**, so front-load what must be present and build long
  songs in sections. This is an argument for the section-wise task types (`cover`, `repaint`) over
  one very long `text2music` render.
- **Artist references are stripped by Suno and redirected to descriptive characteristics**
  (Suno's own published policy). That is the same conclusion the design reached for policy
  reasons: describe the characteristics, and never require the name.
- **How much the LM planner would help.** Disabling it trades quality for control, and the guide
  is honest that the LM "improves usability" for people who have not planned. For a system that
  plans explicitly, the trade is probably worth it — but it is an assumption, not a measurement.
