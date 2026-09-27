# Result: rap metal / funk metal groove, 3:08

Second song through the pipeline. The brief was unusually explicit, which made it a good test of
whether the artifacts can actually express what a description says.

## What the brief named, and where it went

| Requirement as written | Control |
| --- | --- |
| "hybrid of heavy metal, punk, funk, and hip-hop" | `genre: Rap Metal` + `fusion: Hip-Hop, Funk, Punk` — **fusion was capped at two**, so four genres could not be stated; raised to three |
| "Dropped D tuning" | new `tuning` bin → `Drop D Tuning` |
| "guitar that mimics turntable scratches, air-raid sirens" | **ten new harmony options**, including `Guitar Scratch Effects`, `Muted Funk Chops`, `Whammy Guitar`, `Dive Bombs` |
| "rapid-fire, confrontational rap delivery" | `Rapid-Fire Delivery` + `Aggressive Delivery` |
| "alternates between spoken-word intensity and shouted anthems" | new `vt_shouted` and `vt_chant` vocal tags, placed per section: verses `[rap] [spoken word]`, choruses `[shouted] [gang vocals]` |
| **"strictly live instrumentation… rather than turntables or synthesizers"** | new **negative-polarity `avoid` bin** |

That last one is the substantive addition. **A brief that insists on absence needs somewhere to say
so**, and there was nowhere. The `avoid` bin holds no tags — its selections are collected as
exclusions, recorded in `prompt.negative.style`, and enforced the only way this target can enforce
them, by never selecting `Synths`, `Vinyl Scratching`, `Drum Machine` or `Electric Piano` in the
positive bins. The ACE-Step ComfyUI node exposes no negative-caption input; the standalone repo's
`lm_negative_prompt` would take these directly.

## The caption

```
Rap Metal, Hip-Hop, Funk, Punk, Syncopated, Breakbeat, Groovy, Offbeat, Live Drums, Punchy
Kick, Fingerstyle Bass, Distorted Bass, Distorted Guitar, Downtuned Guitar, Guitar Riffs, Muted
Funk Chops, Guitar Scratch Effects, Drop D Tuning, Male Rap Vocals, Spoken Word Vocals, Rapid-
Fire Delivery, Shouted, Aggressive Delivery, Harsh Vocals, Gang Vocals, Call-and-Response
Vocals, Raw Production, Live-Room Production, Gritty Production, Raw, Biting, Punchy,
Aggressive, Defiant, Urgent, Very High Energy, Rap-Metal Groove
```

37 tags, none dropped. The five that the old budget of 32 had been cutting — `Call-and-Response
Vocals`, `Raw`, `Biting`, `Punchy` and the structure label — are all back now the budget is 64. No
artist name, and no synth or turntable anywhere.

Fixing the budget also caught a real bug: it was keeping more tags than the cap allowed, because
tags from the same bin share a `(priority, index)` key and that key was used in a set. Ranked by
position now.

## The lyric

8 of 8 sections matched, every section inside its budget, no warnings. Verses 115 and 124 syllables
against a 64–128 budget at ~2.8 syllables/s; the chorus 32 against 32–64, which is a shouted
monorhyme four-liner — `AAAA` — as the template asks. Three lines were carrying 17–18 syllables in
a single phrase, so caesura markers split them: that is what the phrase check and the `/` marker
are for, and it is the first time either has actually changed a lyric.

## Measured

| Requirement | Asked | Measured | Verdict |
| --- | --- | --- | --- |
| Duration | 187.8 s | **187.8 s** | met |
| Tempo | 92 BPM | **184.57 BPM**, 0.6 from the 2× octave | met |
| Key | E minor | **E major** (chroma corr. 0.647) | **unmet** |
| Clipping | ≤ 100 ppm | 1023 samples (**56.7 ppm**), +0.81 dBFS | met |

The key missed — E major instead of E minor. Parallel-key confusion is a known weakness of
chroma-template detection, so this is either a real miss or a measurement artefact; either way it is
reported unmet rather than argued away. The tempo came out at exactly double the request. The
octave tolerance calls that met, which is defensible for a beat tracker but worth flagging: 184 BPM
and 92 BPM are a different feel, and this brief asked for a groove.

## Two findings worth more than the song

**1. The vocal metric's target is genre-dependent, and nothing encodes that.** Harmonicity here is
0.25–0.35, well below the previous song's 0.42–0.52. Read against the nu-metal brief that would be
a failure; read against this one it is **correct** — the lyrics are rapped and shouted and the
`avoid` bin says `No Clean Singing`. The metric has no way to know which song it is looking at. It
needs the expected *direction* from the spec: a chorus tagged `[clean vocal] [melodic vocal]`
should be more harmonic than its verse; one tagged `[shouted] [rap]` should not be. Right now the
analyser reports a number and a human interprets it, which is the wrong division of labour.

**2. Section transitions are still unhonoured.** 1 of 7, 1 of 7 and 0 of 7 met across the three
takes. `gap_ms` is 0–1 at every boundary, so a declared `[stop]` before the breakdown never
happened; `fill_ratio` is 0.00 everywhere. Same result as the previous song, from a different
template and a different caption — so it is a property of the model, not of that one prompt.

Dynamics measured flat (verse→chorus +0.86 dB, brightness −89 Hz). Unlike the nu-metal song, that is
arguably faithful: this genre is relentless rather than quiet-loud, and its dynamics come from groove
and texture. Busyness does rise in the chorus (+0.59 onsets/s), which is the right direction.

## Takes

Not committed: the renders are in
`/home/dennis/src/comfyanonymous--ComfyUI/output/audio/rap-metal-groove_*.mp3`, and any take
is reproducible from its seed with `build_and_submit.py --submit --takes 1 --seed <seed>`.

| file | seed | notes |
| --- | --- | --- |
| `take_s4409.mp3` | 4409 | measured above; key missed |
| `take_s12328.mp3` | 12328 | highest vocal harmonicity (0.339) |
| `take_s20247.mp3` | 20247 | best vocal contrast, +0.036 |

All three are rapped and shouted rather than sung, which is what the brief asked for. What no metric
here can tell you is whether the *groove* works — whether the bass and drums lock, whether the
guitar textures sound like a turntable. That is an ear question, and this song is a harder one for
the machinery than the last, because the thing it is judged on is funk, and nothing in the pipeline
measures funk.
