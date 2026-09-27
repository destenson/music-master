# Evidence classes

Status: design. Amends the enforcement model in
[`compliance-architecture.md`](compliance-architecture.md) §5–6 and underpins
[`captioner.md`](captioner.md).

## 1. The problem

A verdict currently records *what was asked*, *what was measured* and *who decided*. It does not
record **what kind of evidence** supported it — and that turns out to matter more than any of the
others.

A tempo read from the waveform by a beat tracker and a genre read from a caption a language model
wrote about the waveform are both "the audio says so". They are not remotely the same claim. The
first is a measurement that will reproduce to the decimal; the second is a generated sentence that may
be fluently wrong. Flattened into one green tick, the second inherits the first's credibility, and the
report becomes a machine for manufacturing confidence.

The enforcement modes already in the design describe *how strongly* a requirement can be checked —
`enforced`, `verified`, `conditioned + verified`, `measured`, `unverified`. They say nothing about the
reliability of the thing doing the checking. Evidence class is the missing axis.

## 2. The classes

| Class | What it is | Reproducible | Examples |
| --- | --- | --- | --- |
| **Measurement** | arithmetic or signal processing over the artifact | to the decimal, on any machine | duration, tempo, key, loudness, peak, onset density, vocal-band harmonicity, section boundaries, stem presence |
| **Description** | a model's generated account of the artifact | approximately, same model and version | CLAP scores over the vocabulary, a music caption, an audio-LLM's answer to a question |
| **Self-report** | the *generator's* account of its own output | approximately | ACE-Step's audio understanding and quality score |
| **Oracle judgement** | a System One model's probability over a stated question | approximately, pinned to a version | the Jev battery: theme, mood, hook, policy |

Description and self-report are both model output; they are separated because **independence is the
whole point of adding a captioner.** A third-party captioner shares no conditioning pathway with the
generator; the generator's own understanding does, and is therefore weaker evidence for the same
claim.

Transcription — ASR of the rendered vocal — would be a fifth class and sits between measurement and
description: model output, but against a checkable reference (the written lyric) and with an
objective error metric. It is out of scope for now and the class is reserved.

## 3. What each class may decide alone

| Requirement severity | Measurement | Description | Self-report | Oracle |
| --- | --- | --- | --- | --- |
| **hard** | yes | only if the class passed its gauge, and never alone where a measurement overlaps | never | only with a companion signal (top-2 margin, not `confidence`) |
| **soft** | yes | yes, reported as a score | as a hint | yes |
| **policy** | yes, where it is lexical or numeric | never alone | never | yes, with the action/review bands |

The rule that matters is in the first row: **a hard requirement may never rest on description alone.**
If the only evidence for "the chorus is sung rather than shouted" is a caption saying so, the honest
verdict is `unverified` with the caption attached as a hint — not `met`.

## 4. The four rules

1. **Description is never sole evidence for a hard requirement.** It corroborates; it does not decide.
2. **Overlap must agree.** Where a descriptive claim overlaps something measured, the two must agree,
   and a disagreement is itself a first-class finding — usually the most informative one in the run,
   because it means either the describer or the measurer is wrong, and both matter. A caption reading
   "sparse, restrained" over an onset density of 5.9/s is not a rounding error.
3. **Capability is declared, not assumed.** A describer states which bins it will score and which
   requirement classes its gauge has passed. A class that has not passed stays `unverified`. This is
   the same discipline as `MusicGenerator.capabilities` in the design's generator adapter, applied to
   the evidence side.
4. **Identity is recorded.** Every verdict that rests on a model records which model, which version
   and which weights hash. "The captioner said so" is not reproducible; "lp-music-caps at revision
   `abc123` said so" is.

## 5. How the report shows it

Each verdict gains two fields alongside the existing evidence:

```jsonc
{
  "requirement_id": "genre",
  "severity": "hard",
  "enforcement": "conditioned + verified",
  "evidence_class": "description",       // measurement | description | self_report | oracle
  "verdict": "uncertain",                // not "met", because it is description alone on a hard requirement
  "supported_by": [
    { "class": "description", "source": "clap@rev-9f2", "value": {"rap_metal": 0.41, "nu_metal": 0.29} },
    { "class": "measurement", "source": "audio.dsp.onset_density", "value": 4.94 }
  ],
  "note": "Description alone on a hard requirement; margin 0.12 is below the 0.5 gate."
}
```

The two headline counts in the report become:

- **decided by measurement** — the number to trust.
- **decided by description** — the number to watch, because it is the one that can be inflated
  without anyone noticing.

A report that says "12 met, 6 of them on description" is a different document from "12 met", and only
one of them is honest.

## 6. What this changes in the taxonomy

Nothing structural, and that is the point — it is an additional axis, not a new model.

| Existing | Now also carries |
| --- | --- |
| `enforcement` (enforced / verified / conditioned + verified / measured / unverified) | an `evidence_class` per supporting item |
| the "self-evaluation is not verification" rule | generalised: *any* model's account is a class, and independence ranks above capability |
| the compliance report schema | two new fields per verdict, and a `decided by description` count |
| the oracle's state (the fact sheet) | the description block, with its own provenance |

## 7. Why this is not bureaucracy

The failure it prevents is concrete and would look like success. Without classes:

1. A captioner hallucinates a detail that the brief happened to ask for.
2. Jev reads the caption and returns 0.94.
3. The gate passes on margin.
4. The report shows a green tick for a requirement that was never checked.
5. The user ships a song believing something about it that is not true.

Every step is individually reasonable and the composite is a lie. Classifying the evidence is what
stops it at step 4, because a description-derived verdict on a hard requirement is `uncertain` by
construction rather than by anyone's judgement in the moment.

The same reasoning produced the existing `unverified` state, and this is its natural extension: the
project's whole claim is that it reports what it does not know. As the number of ways to *appear* to
know grows — captions, self-reports, audio LLMs — the bookkeeping has to grow with it.

## 8. Open questions

1. **Should a gauge-passed description class be allowed to decide a hard requirement alone?** The
   current answer is no. If CLAP reaches a measured 95% on genre against a labelled gauge, that rule
   is arguably too strict — but loosening it needs the gauge to be large enough to trust, which today
   it is not. Keep the rule until the gauge earns its way out of it.
2. **How are two descriptions combined?** Two independent captioners agreeing is stronger than one,
   but there is no principled way to combine them yet, and naive averaging of scores across models is
   meaningless. Treat a second describer as a disagreement detector, not a vote.
3. **Does the oracle's own reading of a description need a class of its own?** An oracle judgement
   over a caption is a model reading a model. The recommendation is to keep it as `oracle` but record
   the description it read, so a wrong chain is traceable to its link.
4. **What is the smallest useful gauge?** Ten takes and six fields is a start and not a statistic.
   The class gates should be revisited as takes accumulate rather than fixed now.
