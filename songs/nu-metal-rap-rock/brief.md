# Brief: nu-metal / rap-rock, three minutes

**Ask.** A three-minute song inspired by Linkin Park.

## Why the band is not in the prompt

Linkin Park are named in this brief and nowhere else. The prompt describes the *characteristics* —
the fusion, the dynamics, the vocal split — for three reasons:

1. The generator's own guide and the Suno policy both state that artist names are stripped and
   redirected to descriptive musical characteristics. A name is not a control; a description is.
2. This project's own `content_exclusions` bin carries `no_artist_imitation`, and the design treats
   a named living artist as a policy question rather than a style hint.
3. It prompts better. "Metal, Hip-Hop, Electronic, Screamed Vocals, Dynamic Energy" tells the model
   what to do. A band name asks it to recall a training distribution and hope.

What the band actually contributed to this brief, expressed as things a model can act on:

| Characteristic | Where it lives |
| --- | --- |
| Heavy metal + hip-hop + electronic fusion | `genre` + `fusion` |
| Rapped verses against sung, shouted choruses | `lead_vocal`, `vocal_delivery`, section tags |
| Quiet/loud dynamics as the structural device | section modifiers, not the caption |
| Downtuned distorted guitars under electronic drums | `harmony`, `drums`, `synth` |
| Cathartic, anthemic, shoutable hook | the chorus, 8 syllables a line |
| Alienation and defiance as subject matter | `lyric_theme`, and the lyric's one metaphor |

## Shape

`nu_metal_rap_rock` — a template added for this brief, because the library had no rap-rock form and
`pop_standard`'s 4-line verses are half the length a rap verse needs. 92 bars at 120 BPM: intro 8,
verse 16 (8 lines), pre-chorus 8, chorus 8, verse 16, pre-chorus 8, chorus 8, bridge 8, chorus 8,
outro 4.

Dynamics are carried by the **section tags**, not the caption, because that is where the guide says
performance direction belongs: `[Chorus - explosive]`, `[Bridge - stripped back]`,
`[Chorus - powerful]`. The last chorus is loud because the bridge was not — the form does the work.

## One metaphor

The lyric holds a single image throughout: **signal against static**. Interference, a frequency that
cannot be named, a wall built out of noise, and finally turning the volume up until the doubt is
inaudible. No mixed metaphors, per the guide's discipline.
