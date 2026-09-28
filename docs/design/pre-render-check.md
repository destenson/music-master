# The pre-render check: what the decision model is for

Status: design, implemented in `musicmaster/precheck.py`, `musicmaster/spec.py` and the page's
Check tab. Companion to [`compliance-architecture.md`](compliance-architecture.md),
[`tag-vocabulary.md`](tag-vocabulary.md) and [`../research/jev-and-decision-models.md`](../research/jev-and-decision-models.md).

## 1. The decision

> **Given the caption that will be sent and the lyrics that were generated, does each requirement
> the brief implies hold — well enough to spend a render on it?**

That is the only question this page answers, and it is a decision rather than a report: a hard
requirement that fails here costs a text call to fix, and the same requirement discovered after
synthesis costs a full render. Code owns the flow; the model supplies bounded judgements about the
words; the user decides whether to render, regenerate the lyric, or change the caption.

The consumer is written down because a check with no consumer is how a report becomes a wall of
rows nobody acts on. Every verdict on this page routes somewhere: a failed caption property names
the bin whose tag went missing, and a failed lyric property names the requirement the words did not
satisfy.

## 2. Why the compliance battery is not this

`compliance-architecture.md` §7.2 specifies a battery that runs after a track is rendered, against a
fact sheet built from measurements, an independent caption, a chord transcription and an ASR
transcript. It asks whether the *audio* delivered what was asked for.

This page runs before any audio exists, and it used to run that battery anyway. The consequence was
not a wrong answer but an unanswerable question: the questions name `measured` and `chords`, which
only exist after a render, and they name a `target` that was built by the spec and then never placed
in the state sent to the model. A model asked whether the production matches "the era named in
`brief.era`" — with no era in the state — still answers, and answered `met` at level 5. That is the
failure this page exists to make impossible: a fluent verdict for a comparison that never happened.

The Stage-5 battery is not wrong; it is simply downstream of artifacts this page does not have. It
stays in the design, and it runs when a captioner and a measurement pass exist to feed it.

## 3. Two artifacts, two kinds of check

Everything the brief demands is checked on **one of exactly two artifacts**, and which artifact it
is decides the checker.

**The caption is checked in code.** The caption is the comma-separated tag string rendered from the
selections. "Does the caption carry the distorted guitar I selected" is a containment test over a
string this repository produced, not a judgement: it is exact, free, and reproducible to the byte.
Asking a model to judge whether a tag list fits a genre would compare the brief to itself and could
never discover that the renderer dropped a tag.

**The lyrics are checked by the oracle.** Whether a lyric is about a theme, reads as a mood, delivers
a hook, or stays inside an explicitness limit cannot be computed. Each is one narrow question with a
typed answer.

The properties of the *rendered audio* — the genre the track actually reads as, the instruments a
listener hears — are absent here by construction. They need a measurement or an independent
description of a file that does not exist yet.

| Requirement | Artifact | Checker | Evidence |
| --- | --- | --- | --- |
| Caption coverage: every selected sound property is named | caption | `code.caption.coverage` | measurement |
| Caption exclusions: no excluded element is named | caption | `code.caption.exclusions` | measurement |
| Caption coherence: no unknown, over-limit or mutually-exclusive selection | caption | `code.caption.coherence` | measurement |
| Caption budget: the tag budget dropped nothing | caption | `code.caption.budget` | measurement |
| Theme: the words are about the theme | lyrics | `jev.theme_adherence` | oracle |
| Mood: each selected mood axis reads as asked | lyrics | `jev.mood_axis` | oracle |
| Hook: the flagged section pays off | lyrics | `jev.hook_payoff` | oracle |
| Explicitness: within the limit the brief set | lyrics | `jev.explicitness` | oracle |
| Content policy: the lyric contains none of the excluded content kinds, one question each | lyrics | `jev.content_policy` | oracle |
| Absence: the lyric does not name an element the brief avoided, one question each | lyrics | `jev.absence_of` | oracle |
| Imitation: no deliberate reproduction of a named artist | lyrics | `jev.artist_pastiche` | oracle |

## 4. The shape of a question

Four rules, taken from the measured behaviour of the sibling integrations and enforced by the
question bank rather than by convention:

1. **One requirement, one question.** A requirement is never folded into a general "is this song
   good" question. "Does the chorus function as the payoff the brief asks for" is one question;
   "how is the song" is none.
2. **The question names the fields it reads by backticked path**, and every one of those paths
   resolves in the state that is actually sent. A question whose fields are absent is a construction
   bug, not a verdict.
3. **The thing asked for travels in the state.** The requirement's target is placed under
   `targets.<requirement_id>` and the question points at it. A model cannot compare an artifact to a
   target that was never sent.
4. **No holistic scores on this page.** Scores are for a graded magnitude on a written scale
   (a mood axis); a property that is simply present or absent is a `noul`. Where a bounded score is
   used, it is decided by the mass on the passing side of the bound, not by the distance between the
   top two adjacent levels — adjacent levels of a bounded score are not a meaningful margin.

## 5. What code owns

- **The requirement set.** Derived from the vocabulary's own `maps_to`, so a bin cannot oblige a
  check that does not exist and a checker cannot be added without a bin that uses it.
- **The caption checks**, which are string operations.
- **The thresholds and the band.** A `noul` inside `[0.30, 0.70]` is `uncertain`, never a pass.
  Thresholds are per question and re-measured, never ported between primitives.
- **The repair.** A verdict that did not pass carries a `suggestion`: one concrete change, naming the
  thing that failed — the missing tag, the mood axis, the excluded element. Where a rewrite can
  satisfy it, it carries a `repair_instruction` too, an imperative the lyric generator can act on.
  Both are written in `musicmaster/repairs.py` from the requirement and the measured failure, never
  by the model, because a repair a model wrote about its own judgement would be as unverifiable as
  the judgement it was explaining. The page offers to apply the instructions and runs the check
  again afterwards.
- **The summary.** The report opens with one paragraph saying what already holds and what to do
  before rendering. Counts are a table; the sentence is what a person reads first.
- **The verdict and the routing.** The model never writes a repair and never chooses the next step.
- **The projection.** Only the fields the questions name are sent, so the artifact under judgement
  leaves the machine and the working draft does not.

## 6. The gauge

A question that cannot separate a satisfied requirement from a violated one measures nothing, and
the way to know is a labelled pair, not an argument. `spikes/jev_property_probe.py` asks one
matched and one violated artifact for each property and reports whether each arm separates them.
The arms it compares are the comparative score question the stage used to ask, that same question
with the target placed in the state, a narrow property `noul`, and a deterministic code check.

The result on the nu-metal fixture is what settled the split: the comparative questions separated
**5/10** properties (5–6 across runs), the same questions with the target in the state **9/10**,
narrow property `noul`s **10/10**, and code containment **7/7**. Two changes did it — put the target
in the state, and ask for the property rather than a comparative quality — and a third followed from
the table: the properties the caption is rendered from are code's to check, not the oracle's.

Per-question thresholds are re-measured against that gauge when a question is reworded or the pinned
model version changes, because a threshold tuned against one wording does not carry to another.

## 7. Non-uses

- **Audio properties.** Genre as heard, instrumentation as heard, vocal character, era, loudness.
  These wait for a captioner and a measurement pass.
- **Anything arithmetic.** Syllable counts, bar counts, tempo comparison, budget arithmetic and
  structure conformance are all computed in code, and Jev's own documentation names counting as a
  failure mode.
- **Generation.** It cannot write the repaired lyric; a generative model does that, from an
  instruction code assembles out of the failed question.
- **Privilege or destructive action.** The page recommends; it does not delete a take or block a
  render on a model's word alone.
