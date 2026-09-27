# Brief: rap metal / funk metal groove, three minutes

**Ask.** A song inspired by Rage Against the Machine.

## Why the band is named only here

The prompt describes the *characteristics* — fusion, tuning, guitar method, vocal manner, and what
must be absent. Same three reasons as before: the generator's guide and Suno's policy both redirect
artist names to descriptive characteristics, this project's `content_exclusions` carries
`no_artist_imitation`, and a description is a control where a name is a hope.

What the brief actually specifies, and where each part is expressed:

| Requirement as written | Where it lives |
| --- | --- |
| "hybrid of heavy metal, punk rock, funk, and hip-hop" | `genre: Rap Metal` + `fusion: Hip-Hop, Funk, Punk` — three fusion slots, because four genres cannot fit in two |
| "Dropped D tuning" | `tuning: Drop D Tuning` — a real parameter with its own bin, not an adjective |
| "guitar work that mimics turntable scratches, air-raid sirens, dub basslines" | `harmony: Guitar Scratch Effects`, `Guitar Riffs`, `Muted Funk Chops`, `Downtuned Guitar`, `Distorted Guitar` |
| "syncopated, funk-infused basslines" | `bass: Fingerstyle Bass`, `Distorted Bass` |
| "pounding, breakbeat-inspired drums" | `drums: Live Drums, Punchy Kick` + `groove: Breakbeat, Syncopated, Groovy, Offbeat` |
| "rapid-fire, confrontational rap delivery" | `lead_vocal: Male Rap Vocals, Spoken Word Vocals` + `vocal_delivery: Rapid-Fire Delivery, Aggressive Delivery` |
| "alternates between spoken-word intensity and shouted anthems" | verses `[rap] [spoken word]`, choruses `[shouted] [gang vocals]` — per section, not global |
| **"strictly live instrumentation… rather than turntables or synthesizers"** | `avoid: No Synthesizers, No Keyboards, No Turntables, No Samples, No Drum Machine, No Electronic Beats` — and no synth or turntable option is selected anywhere |
| "socially conscious lyricism… corporate America, institutional racism, government oppression" | the lyric text, not the caption |

That last row is the interesting one. **A brief that insists on absence needs a place to say so.**
The `avoid` bin is negative-polarity: its selections never become tags, they are recorded as
exclusions and checked. The ACE-Step ComfyUI node exposes no negative-caption input, so on this
target the exclusions are honoured the only way they can be — by never selecting `Synths`,
`Vinyl Scratching`, `Drum Machine` or `Electric Piano` in the positive bins. The bin records the
intent, and the compliance report can be asked whether it held.

## Shape

`rap_metal_groove`, added for this brief: 72 bars at 92 BPM → 3:08. Riff intro, two 16-bar rap
verses, a shouted monorhyme chorus three times, and an instrumental guitar breakdown between the
second and third chorus. Groove-first, so the verse sits on a repeating funk figure; the breakdown
is instrumental because the guitar textures are the point of it.

Transitions are declared per boundary — `[hard cut]` after the intro, `[build-up]` into each
chorus, `[stop]` before the breakdown — and are verified against the audio rather than assumed.
The previous song measured 1 of 9 and 2 of 9 met, so expect the same here; that is the honest state
of boundary control on this model.

## One metaphor

**The ledger.** Who bills whom, what is metered, what the columns say. It carries the anti-corporate
and anti-state themes without sloganeering, and it rhymes.
