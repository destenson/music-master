# Result: nu-metal / rap-rock, 3:04

## Iteration 1 → 3 in one page

The first render was compliant on every mechanical requirement and bad. Three rounds of fixes, each
driven by a measurement rather than a guess:

| Iteration | Change | What the measurement said |
| --- | --- | --- |
| 1 | one take, global caption, one modifier per section | mechanical checks all met; chorus was the **least** harmonic part of the song — the yelling was where the singing should be |
| 2 | vocal control moved into per-section standalone tags; caption rebuilt around the fusion | the inversion fixed in **4 of 4** takes |
| 3 | transitions declared per section and verified against the audio | the model **largely ignores them**: 1 of 9 and 2 of 9 met |

## What the caption is now

```
Rap Rock, Nu Metal, Electronic, Driving, Syncopated, Live Drums, Drum Machine, Distorted Bass,
Distorted Guitar, Power Chords, Palm-Muted Guitar, Guitar Riffs, Electric Piano, Detuned Synths,
Male Rap Vocals, Male Tenor Vocals, Clean Vocals, Melodic Vocals, Soaring Vocals, Harsh Vocals,
Gang Vocals, Layered Harmonies, Polished Production, Layered Production, Punchy, Bright,
Aggressive, Defiant, Dynamic Energy, Vinyl Scratching, Nu-Metal Rap-Rock
```

`Screamed Vocals`, `Raspy Vocals`, `Rapid-Fire Delivery`, `Wall of Sound`, `Heavy Compression` and
`Distorted Production` are gone — they were global, so they applied everywhere and hardest in the
chorus. `Clean`, `Melodic` and `Soaring Vocals` replaced them. Genre is `Rap Rock` + `Nu Metal`
rather than `Metal` + `Hip-Hop`, because the vocabulary had **no nu metal or rap rock label at
all** — the words the brief uses were not available as a control, which is the likeliest reason the
rap came out as a different style entirely.

## Three tag mechanisms, not one

The guide presents three, and the design had collapsed them:

| Mechanism | Budget | Where |
| --- | --- | --- |
| Section header + one hyphenated modifier | `max_modifiers: 1` | `[Chorus - anthemic]` |
| Standalone performance tags | `max_tags_per_section: 4` | `[rap]`, `[clean vocal]`, `[building energy]` |
| Transition tags | `max_transitions_per_section: 1` | `[stop]`, `[riser]`, `[drum fill]` |

Pools went from 8 vocal tags to **41**, 8 energy tags to **19**, and a new **19-tag transition
pool**. Each template section declares `vocals`, `energy_tags` and `transition_out`, so the writing
brief states them and the checker verifies each one was placed.

## Vocal character, measured

Harmonic energy as a share of total in the 150–3500 Hz band. A sung note is harmonic; a shout is
broadband noise, so a higher figure means more sung.

| take | verse | chorus | delta |
| --- | --- | --- | --- |
| iteration 1 | 0.508 | **0.372** | **−0.136** |
| iteration 2, seed 2204 | 0.276 | 0.543 | **+0.266** |
| iteration 2, seed 10123 | 0.518 | **0.560** | +0.042 |
| iteration 2, seed 18042 | 0.380 | 0.496 | +0.116 |
| iteration 2, seed 25961 | 0.340 | 0.515 | +0.175 |
| iteration 3, seed 3307 | 0.302 | 0.510 | **+0.208** |
| iteration 3, seed 11226 | 0.324 | 0.295 | **−0.028** |

The fix works most of the time and **not always**: one take in the third batch inverted again. That
is the argument for the measurement rather than against it — `take_s11226` is exactly the take the
metric catches and a listener would have to sit through to discover.

## Transitions, measured

Boundaries, declared against detected:

```
take_s3307:  transitions met: 1 of 9
  Intro -> Verse 1        drum fill    step_up      +3.21 dB   gap 1ms   fill 0.00
  Verse 1 -> Pre-Chorus   build-up     smooth       +0.37 dB   gap 0ms   fill 0.00
  Pre-Chorus -> Chorus    stop         step_up      +4.36 dB   gap 1ms   fill 0.00
  Chorus -> Verse 2       downlifter   smooth       -1.03 dB   gap 0ms   fill 0.00
  Pre-Chorus -> Chorus    riser        riser        +0.43 dB   gap 0ms   fill 0.00   met
  Chorus -> Outro         crossfade    step_up      +4.54 dB   gap 1ms   fill 0.00
```

Three things stand out:

- **No gaps anywhere.** `gap_ms` is 0–3 ms at every boundary, so a declared `[stop]` never
  happened. The oldest transition trick there is, and it is simply absent.
- **No fills.** `fill_ratio` is 0.00 at every boundary in both takes — the outgoing section's last
  bar is never denser than the rest of it.
- **Level steps do happen** (±3–5 dB), so the sections do change loudness. It is the *connective
  devices* that are missing: the boundaries are mostly `smooth`, with the arrangement changing
  underneath a continuous texture rather than being punctuated.

So transitions join per-section arrangement in the same category: expressible in the artifacts,
measurable in the audio, and **not reliably controllable through lyrics tags on this model.**

## Takes

Run outputs are not committed: renders, measurements and per-seed prompt records are
regenerated rather than stored. The renders are in
`/home/dennis/src/comfyanonymous--ComfyUI/output/audio/nu-metal-rap-rock_*.mp3`, and any take
is reproducible from its seed with `build_and_submit.py --submit --takes 1 --seed <seed>`.

Named by seed, because two batches with the same index collided and one batch was overwritten:

| file | seed | chorus harmonicity | note |
| --- | --- | --- | --- |
| `take_s2204.mp3` | 2204 | 0.543 | biggest rap-to-sung contrast of iteration 2 (+0.266) |
| `take_s10123.mp3` | 10123 | **0.560** | most sung chorus, cleanest overall |
| `take_s18042.mp3` | 18042 | 0.496 | |
| `take_s25961.mp3` | 25961 | 0.515 | |
| `take_s3307.mp3` | 3307 | 0.510 | best of iteration 3 (+0.208) |
| `take_s11226.mp3` | 11226 | 0.295 | **inverted — screening rejects this one** |

## Still unverified

No independent ASR, so `sung == written lyric` and intelligibility have no evidence channel. No
captioner, so genre fidelity and production character are unchecked — including the one the ear
objected to most, whether the rap is the right *style*. No oracle configured, so caption/lyric
consistency is reported for review rather than decided. The harmonicity ratio says whether a vocal
moved from shouted toward sung; it cannot say whether the result is any good.
