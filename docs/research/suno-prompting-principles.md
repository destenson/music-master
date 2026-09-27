# Universal prompting principles for AI music generation

**Sourcing.** The Notion guide the ACE-Step tutorial links to is dead (404 after a redirect), and Suno's own "Using Metatags" Notion page renders empty; I could not read either. Its substance is partly recovered because the community [Suno Field Guide](https://github.com/mttkllr/suno-field-guide) cites that exact URL as the primary source for its mental-model and prompt-structure sections — second-hand, not original. **(official)** = Suno-authored; **(community)** = third-party/field-tested.

## Caption / style prompt

- **Length.** Community consensus is a deliberate handful of descriptors: 4–7 ([Blake Crosley](https://blakecrosley.com/guides/suno)), 4–8 ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/)), 3–5 simple up to 8–15, ~20 ceiling ([Field Guide](https://github.com/mttkllr/suno-field-guide)). Fewer leaves defaults; more makes descriptors compete and average into mush.
- **Order matters.** Leading tokens weigh more, so genre first ([SunoMV](https://suno.bi/en/blog/suno-v5-5-prompt-engineering-advanced-techniques-2026)); guides converge on genre → mood → instrument → vocal → production ([MixMasterAI](https://www.mixmasterai.co/suno-prompt-guide), [Field Guide](https://github.com/mttkllr/suno-field-guide)).
- **Tags vs prose — disputed.** Commas are the default, but the Field Guide argues the model was trained on structured metadata, that commas read as optional while periods/"and" mark elements required, and that hovering the desktop style box reveals parsing. An A/B, not a rule.
- **Content.** Subgenre beats broad genre; named instruments beat families. Emotion words outperform technical ones — "desperate" beat "minor key with reverb" across 200+ generations ([Field Guide](https://github.com/mttkllr/suno-field-guide)).
- **BPM/key belong in the style field**, approximate not exact ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/)).
- **Artist references (official).** Suno says it never allowed artist-name prompts and that when one appears it "remove[s] the artist's name and redirect[s] the request toward descriptive musical characteristics" ([Suno](https://suno.com/blog/building-the-future-of-music-responsibly)). Describe characteristics; don't name the artist.
- **Contradictions average out.** Over-stuffed or conflicting prompts (lo-fi *and* reverb-heavy) yield muddy compromise ([Blake Crosley](https://blakecrosley.com/guides/suno), [SunoMV](https://suno.bi/en/blog/suno-v5-5-prompt-engineering-advanced-techniques-2026)).

## Meta / structure tags

- **Canonical set (community):** `[Intro] [Verse] [Pre-Chorus] [Chorus] [Post-Chorus] [Bridge] [Outro] [Instrumental] [Solo] [Interlude] [Break] [Build] [Drop] [Hook] [End]` ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/), [sunomarket](https://sunomarket.com/blog/suno-lyric-metatags-that-work)).
- **Bracket rule.** Square brackets instruct; unbracketed text is sung — the commonest beginner bug is plain-text `Chorus:` ([sunomarket](https://sunomarket.com/blog/suno-lyric-metatags-that-work)). Parentheses read as backing vocals, not production direction ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/), [Field Guide](https://github.com/mttkllr/suno-field-guide)).
- **Modifiers combine.** `[Long Mellow Intro]` is common; pipe-stacking `[Chorus | Anthemic | Stacked Harmonies]` is more reliable, with ~7 elements max and left-to-right priority ([Field Guide](https://github.com/mttkllr/suno-field-guide)). Tags over ~3 words lose effect ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/)).
- **Placement.** Lyrics field, one per line, directly above its section; local beats one global block ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/)).
- **Unknown tags.** No official list or spec exists; an unrecognised tag may be ignored or sung aloud ([sunomarket](https://sunomarket.com/blog/suno-lyric-metatags-that-work)).

## Lyrics

- 6–10 syllables per line, ±1–2 within a section; 4 lines per section typical ([Field Guide](https://github.com/mttkllr/suno-field-guide), [MixMasterAI](https://www.mixmasterai.co/suno-prompt-guide)).
- End lines on open vowels/liquids; avoid consonant clusters, which the model drops or slurs ([SongForgeAI](https://songforgeai.com/songwriting/writing-lyrics-suno-can-actually-sing)).
- Simple rhyme (ABAB/AABB), one central metaphor, concrete images over abstractions ([MixMasterAI](https://www.mixmasterai.co/suno-prompt-guide)).
- Background vocals: parentheses. Intensity: ALL CAPS and punctuation ([Field Guide](https://github.com/mttkllr/suno-field-guide)).
- Blank line between sections; number repeats ([Field Guide](https://github.com/mttkllr/suno-field-guide)).
- **Anti-patterns:** AI clichés ("like a moth to a flame") and overused nouns/rhymes — ghost, ashes, chains; fire/desire, pain/rain; "3 AM" ([SongSmith](https://songsmith.studio/blog/suno-lyric-cliches-to-avoid), [Field Guide](https://github.com/mttkllr/suno-field-guide)).

## Negative prompting

Officially a separate **Exclude Styles** field (Custom Mode → Advanced Options), not inline negation ([Suno Help](https://help.suno.com/en/articles/3161921)). Community: 2–3 specific items, reinforced positively in the style field ([FreeSongwritingTools](https://freesongwritingtools.com/blog/suno-metatags-guide/), [HookGenius](https://hookgenius.app/learn/suno-character-limits/)).

## Reproducibility

No seed or temperature exists. Suno is explicitly non-deterministic ([Blake Crosley](https://blakecrosley.com/guides/suno)); the third-party API schema exposes `styleWeight`, `weirdnessConstraint`, `audioWeight`, `negativeTags` but no seed ([OpenAPI](https://raw.githubusercontent.com/api-evangelist/suno/refs/heads/main/openapi/suno-music-api-openapi.yml)). The widely-cited "same seed" GitHub threads are on [`suno-ai/bark`](https://github.com/suno-ai/bark/issues/540), Suno's open-source TTS repo, not the music service. Substitute: identical prompt templates plus many generations ([SunoMV](https://suno.bi/en/blog/suno-v5-5-prompt-engineering-advanced-techniques-2026)).

## Failure modes practitioners converge on

Genre bleed / pop gravity well, where weak tags lose to strong ([Field Guide](https://github.com/mttkllr/suno-field-guide)); adherence decaying after ~30–60 s, so front-load the essentials and build long songs in sections; ending overrun without `[End]`/`[Outro]` (~85–90% effective, community figure); lyric bleed (singable prose in the style field gets sung); genre-mismatched tags ignored, e.g. `[Drop]` in folk ([sunomarket](https://sunomarket.com/blog/suno-lyric-metatags-that-work)); style-vs-lyrics contradictions ([SunoMV](https://suno.bi/en/blog/suno-v5-5-prompt-engineering-advanced-techniques-2026)).

## What is genuinely universal

Direction over precision: prompt text is a coarse constraint, not a command. Front-load and prioritise; one idea per dimension; avoid contradictions. Separate what it sounds like from what is sung from how it is structured, and keep structure explicit and short. Concrete vocabulary beats abstract. Non-determinism is inherent — iterate, don't expect repeats. Negative direction helps but is weaker than positive. Line and rhythm discipline transfers to any vocal model. [MixMasterAI](https://www.mixmasterai.co/suno-prompt-guide) reports its genre–mood–vocal–production order "adapts to Udio, Mureka, and other AI music tools without changes"; [SongForgeAI](https://songforgeai.com/songwriting/udio-vs-suno-prompt-formatting)'s provider layer finds most Suno formatting transfers across engines.

## What is Suno-specific and should not be copied

Character limits (1,000-char style / 5,000-char lyrics; older 200/3,000) are composer UI constraints, not model properties ([HookGenius](https://hookgenius.app/learn/suno-character-limits/)); contested — one guide still says 200 for v5 ([MixMasterAI](https://www.mixmasterai.co/suno-prompt-guide)). Undocumented syntax — MAX Mode blocks, `[START_ON: TRUE]`, `[DUET_START_ON]`, homophone filter evasion, phonetic respelling — is unofficial ([Field Guide](https://github.com/mttkllr/suno-field-guide)). Sliders, Personas, Voices, Custom Models, Extend/Cover/Repaint, stems and credit economics are platform features ([Blake Crosley](https://blakecrosley.com/guides/suno)). The [stayen/suno-reference](https://github.com/stayen/suno-reference) catalogue (`[aria-rise]`, `[bleep]`, `[accelerando]` with "accepted parameters") reads as speculative/LLM-generated and contradicts the "no official list, tags are short signals" consensus — not a specification.

## What I could not verify

The original Notion guide; any official Suno metatag spec; the `[End]` reliability figure and the pre-header tag-placement rule (both folklore, one flagged untested by its compiler in the [Field Guide](https://github.com/mttkllr/suno-field-guide)); and current character limits, which community sources measure but Suno has never published ([HookGenius](https://hookgenius.app/learn/suno-character-limits/)).
