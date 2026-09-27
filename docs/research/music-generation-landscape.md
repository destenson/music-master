# Music generation for a natural-language brief: controllability, verification, and compliance

Research memo for the `music-master` design, from primary sources (arXiv, GitHub, HuggingFace, official docs). Unconfirmed items are labeled **unverified**.

## 1. Full-song, lyrics-to-song open models

| Model | Params | User lyrics | Vocals | Max duration | License | Realistic VRAM |
|---|---|---|---|---|---|---|
| [ACE-Step v1](https://github.com/ace-step/ACE-Step) | 3.5B | Yes (tags + `[verse]`/`[chorus]` structure tags) | Yes | ~4 min | Apache-2.0 | 8 GB with offload |
| [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) | 2B/4B DiT + 0.6–4B LM planner | Yes; 50+ languages | Yes | 10 s–10 min | MIT | <4 GB (2B turbo) |
| [YuE v1](https://arxiv.org/abs/2503.08638) | LLaMA2-family, stage-1 ~7B (**unverified**) | Yes | Yes | ~5 min | code/weights on the preserved [YuE-v1 branch](https://github.com/multimodal-art-projection/YuE/tree/YuE-v1) — verify there | 24 GB-class |
| [YuE2-3B](https://github.com/multimodal-art-projection/YuE) | 3B | Yes **plus an editable ABC score/melody-chord plan** (`abc=`, `cot=`) | Yes | Full song, 48 kHz stereo | Weights CC BY-NC 4.0; code Apache-2.0 | 24 GB |
| [DiffRhythm](https://huggingface.co/ASLP-lab/DiffRhythm-full) | ~1B-scale DiT + VAE (**unverified**) | Yes, but **lyrics + style prompt only** | Yes | 4 m 45 s (base 1 m 35 s) | Card says Apache-2.0 for code/DiT weights but also lists `stable-audio-community` — treat as ambiguous | Moderate (**unverified**) |
| [SongGen](https://github.com/LiuZH-19/SongGen) | 1.3B | Yes (lyrics + description + optional 3 s voice ref) | Yes | **30 s, English only** | Weights released; license not stated in repo — **unverified** | Moderate |
| [SongCreator](https://proceedings.neurips.cc/paper_files/paper/2024/file/92a7a03e1c716970848a4a86cc8243ee-Paper-Conference.pdf) | Research system | Lyrics | Yes | Not verified | Research release | — |

Key facts: DiffRhythm generates full songs in ~10 s from lyrics + style only, with no chord/tempo/key control and no reference-audio style conditioning ([paper](https://arxiv.org/abs/2503.01183)); its successor [DiffRhythm+](https://arxiv.org/abs/2507.12890) adds multi-modal style conditioning (text + reference audio) and preference optimization. SongGen's own README admits a 30 s, English-only ceiling and reports weak key/chord agreement. ACE-Step 1.5 is the only release here that advertises explicit **BPM, key/scale, time-signature and duration metadata control**, plus audio understanding that extracts those from audio — and the installed ComfyUI node confirms all five are real inputs. One caveat learned from the code rather than the README: those controls are injected as a Chain-of-Thought **text prompt** (`_metas_to_cot` in `comfy/text_encoders/ace15.py`), so they bias generation rather than constrain it, and must be verified by measurement (§7).

## 2. Instrumental / text-to-music conditioning

- **MusicGen / AudioCraft** ([docs](https://github.com/facebookresearch/audiocraft/blob/main/docs/MUSICGEN.md)): 300M/1.5B/3.3B; text prompt exposed in all checkpoints; **melody conditioning only in the `-melody` checkpoints**, implemented as chromagram conditioning (`generate_with_chroma`). Continuation is supported; there is **no chord, tempo, key, or stem conditioning in released checkpoints**. Weights CC-BY-NC 4.0, code MIT ([model card](https://github.com/facebookresearch/audiocraft/blob/main/model_cards/MUSICGEN_MODEL_CARD.md)). The card states the model "is not able to generate realistic vocals" — the released models were trained on Demucs-separated instrumentals.
- **MAGNeT** ([model card](https://facebookresearch.github.io/audiocraft/model_cards/MAGNET_MODEL_CARD.html)): 300M/1.5B, non-autoregressive masked transformer, text-to-music and text-to-sound, 10 s/30 s variants, weights CC-BY-NC 4.0. The paper ([arXiv:2401.04577](https://arxiv.org/abs/2401.04577)) claims melody conditioning and continuation, but these are not first-class released conditioning knobs like MusicGen's melody checkpoints.
- **Stable Audio Open 1.0** ([arXiv](https://arxiv.org/abs/2407.14358), [HF](https://huggingface.co/stabilityai/stable-audio-open-1.0)): open-weights text-to-audio, 44.1 kHz stereo, ~47 s, CC-licensed training data; gated under the Stability AI Community License (not OSI). `stable-audio-tools` exposes prompt + timing conditioning, which supports audio-to-audio and inpainting-style editing.
- **Riffusion**: the original spectrogram-diffusion model is open ([riffusion/riffusion-model-v1](https://huggingface.co/riffusion/riffusion-model-v1)); the commercial "FUZZ" system is proprietary.
- **Mustango** ([arXiv:2311.08355](https://arxiv.org/abs/2311.08355)): MusicGen-based and explicitly conditions on **chords, beats, tempo, and key**, predicted from the caption by MuNet; shipped with MusicBench (52K instances). The clearest research example of music-theory controls the mainstream checkpoints omit.
- **MusicGen-Stem** ([arXiv:2501.01757](https://arxiv.org/html/2501.01757v2)): autoregressive multi-stem generation (bass, drums, other).
- **AudioLDM 2**: open text-to-audio with text and melody conditioning ([diffusers](https://huggingface.co/docs/diffusers/main/api/pipelines/audioldm2)).
- **ACE-Step 1.5** exposes repaint, cover, track separation, vocal-to-BGM, and BPM/key/time-signature control.

Pattern: text prompts are universal; **melody conditioning exists in a few checkpoints; chord/tempo/key conditioning is essentially research-only**. Anything beyond text usually means re-training or LoRA, not a switch on a checkpoint.

## 3. Symbolic / MIDI generation

- **text2midi** ([GitHub](https://github.com/AMAAI-Lab/text2midi), [arXiv:2412.16526](https://www.arxiv.org/pdf/2412.16526v2), AAAI 2025): first end-to-end caption→MIDI model (REMI tokens, MidiCaps 168K). Reported objective accuracy: tempo-bin-with-tolerance 65.8%, correct key 33.6%, and weak chord matching (human Likert 2.5/7 for chords, 3.64/7 for key). **Caption-conditioned MIDI is currently unreliable for hard key/chord constraints.**
- **MuseCoco** is the main baseline and scores lower still.
- **Rule-based symbolic** is more controllable: `music21`, [PyTheory](https://pytheory.org/), and progression templates let a system *author* chord progressions, keys, tempo, and verse/chorus forms deterministically, then render or hand off to an audio model.
- **YuE2's ABC score plan** is the strongest hybrid: the model emits an inspectable, editable melody-and-chord score before rendering audio, which is exactly the text-like artifact a text-only judge can inspect.

## 4. Controllability and evaluation research

- **Lyric prosody / syllables**: [multi-level syllable-count control with song-form awareness](https://arxiv.org/abs/2411.13100) (word/phrase/line/paragraph, verse/chorus); [XAI-Lyricist](https://www.ijcai.org/proceedings/2024/0872.pdf) for singability/prosody explanations; [REFFLY](https://arxiv.org/html/2409.00292) for melody-constrained lyric editing.
- **Objective audio metrics**: FAD (often on VGGish), KLD on PaSST tags, CLAP score — the standard trio in Meta model cards ([MusicGen card](https://github.com/facebookresearch/audiocraft/blob/main/model_cards/MUSICGEN_MODEL_CARD.md)). SongGen adds CLaMP3 (symbolic-text alignment), PER (phoneme error rate, i.e. lyric intelligibility), SECS (speaker/voice similarity), and human CE/CU/PC/PQ.
- **Auto-tag/caption models** usable as verifiers: CLAP (audio-text similarity), MERT/MERT2 (genre/mood/tag probes; YuE2 reports MERT2-30s at 91.72% GTZAN genre accuracy), and captioners ([LP-MusicCaps](https://github.com/seungheondoh/lp-music-caps), [SonicVerse](https://arxiv.org/html/2506.15154)). These give **probabilistic**, corpus-calibrated reads, not ground truth.
- **MIR tools for deterministic checks**: [Beat This!](https://huggingface.co/papers/2407.21658) and librosa/madmom for tempo/beats; CREMA/librosa for key; [autochord](https://github.com/cjbayron/autochord) and Chordino for chords; [Demucs](https://github.com/facebookresearch/demucs) for vocal separation; [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) for EBU R128 LUFS; `cmudict`/`pyphen` for syllable counts. These are text-outputtable, cheap, and reproducible.

## 5. Audio-to-text surrogates

- **Captioning**: LP-MusicCaps and SonicVerse turn audio into descriptive text a text-only judge can read.
- **Audio→score/MIDI**: YuE2's [SheetSage2](https://huggingface.co/m-a-p/SheetSage2) claims SOTA audio-to-score (vocal-melody pitch-class F1 82.5% RWC-Pop, 67.1% Rock Corpus); [basic-pitch](https://github.com/spotify/basic-pitch) and [MT3](https://github.com/magenta/mt3) degrade on dense mixes. All are far from exact on harmony.
- **Chord recognition**: autochord/Chordino — coarse checks only.
- **Lyric ASR**: Whisper on Demucs-separated vocals; SongGen's pipeline runs two Whisper variants and discards clips whose transcripts disagree by >20% edit distance — direct evidence of hallucination risk. [Separation improves lyrics transcription](https://arxiv.org/html/2506.15514); [Whisper on Lieder](https://aclanthology.org/2024.nlp4musa-1.3/) documents limits.
- **Pitch/melody**: CREPE and RMVPE for F0; reliable monophonic, weak on mixtures.

## 6. Prior art on verifier / constraint loops

- Best-of-N with a verifier is the dominant test-time pattern ([survey](https://arxiv.org/pdf/2508.16665v3.pdf); [Review, Refine, Repeat](https://arxiv.org/abs/2504.01931)). YuE2 ships **best-of-8 selection**, and DiffRhythm+ uses direct preference optimization — the field is already moving toward this loop.
- **LLM judges are biased**: [self-preference bias](https://arxiv.org/abs/2410.21819) shows judges favor low-perplexity text regardless of origin; [Limits of Automatic Evaluation of Creativity](https://arxiv.org/abs/2608.23705) documents creativity-eval failures. A typed-probability judge fits *classification of extracted facts* better than scoring musical quality directly.

## 7. What this machine already has

The tables above are the field. This section is the deployment, measured by read-only recon
of the actual workstation rather than assumed.

**Resources and constraints.** 32 cores, 125 GB RAM. The GPU is not visible under the
default sandbox (the device nodes are masked, so `nvidia-smi` cannot reach the driver); any
synthesis or training work needs an escalated run. Disk is the binding constraint: root is
99% full with ~22 GB free and `/mnt/ssd4g` is 100% full with ~30 GB free, so the design must
assume **no new model downloads** and reuse what is already on disk.

**Generators already on disk.**

| Asset | Size | Path | Role |
| --- | --- | --- | --- |
| HeartMuLa OSS 3B + HeartCodec | 15 GB + 6.2 GB | `/home/dennis/source-archived/heartlib/ckpt` | Genuine lyrics + tags → full song. Runner `examples/run_music_generation.py`; ComfyUI node `HeartMuLa_ComfyUI` with a `Generate Music.json` workflow |
| ACE-Step v1 3.5B | 7.17 GB | `/mnt/ssd4g/models/ComfyUI/checkpoints/ace_step_v1_3.5b.safetensors` | Lyric-conditioned song generation |
| **ACE-Step 1.5 XL turbo** (DiT) | 9.3 GB | `/mnt/ssd4g/models/ComfyUI/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors` | **The reference generator and the intended target model.** 30 outputs already produced from it on this machine |
| ACE-Step 1.5 text encoder (4B LM) | 7.9 GB | `/home/dennis/src/comfyanonymous--ComfyUI/models/text_encoders/qwen_4b_ace15.safetensors` | Chain-of-thought metadata/caption encoding |
| ACE-Step 1.5 audio-code LM (0.6B) | 1.2 GB | `/home/dennis/src/comfyanonymous--ComfyUI/models/text_encoders/qwen_0.6b_ace15.safetensors` | Generates audio semantic tokens (`generate_audio_codes`) |
| ACE-Step 1.5 VAE | 322 MB | `/home/dennis/src/comfyanonymous--ComfyUI/models/vae/ace_1.5_vae.safetensors` | Latent decode |
| Stable Audio Open 1.0 | 4.52 GB | `/mnt/ssd4g/models/ComfyUI/checkpoints/stable-audio-open-1.0.safetensors` | Instrumental beds |
| Qwen3-TTS | 4.9 GB | `/home/dennis/src/comfyanonymous--ComfyUI/models/qwen-tts` | Speech/vocal synthesis |
| Demucs 4.0.1, MelBandRoFormer, audio-separation nodes | — | ComfyUI `custom_nodes/` | Stems: the basis of any vocal-presence or vocal-only measurement |
| ffmpeg / ffprobe 6.1.1, sox 14.4.2 | — | system | I/O, format conversion, loudness tooling |

ACE-Step is built into ComfyUI core (`comfy/ldm/ace/`, `comfy_extras/nodes_ace.py`), and
`user/default/workflows/audio_ace_step_1_t2a_song.json` is a ready text/tags-to-song graph.
ComfyUI is not currently running.

**Measurement tooling already on disk.** In the ComfyUI venv
(`/home/dennis/src/comfyanonymous--ComfyUI/.venv`): torch 2.10, torchaudio, transformers,
**librosa 0.11**, soundfile, **pyloudnorm**, pedalboard, demucs. That is enough for the
mechanical half of the design — duration, tempo, key, loudness, true peak, clipping,
spectral features, onset density, and vocal presence via stem separation.

**What is missing, and why each gap matters.**

- **No ASR** (no faster-whisper, whisperx, or similar). The "does the sung lyric match the
  written lyric, and is it intelligible" check has no model behind it yet.
- **No captioner** — no CLAP, LP-MusicCaps, Qwen2-Audio or equivalent. There is currently
  nothing on this machine that turns rendered audio into a descriptive sentence.
- **No MIR beyond librosa** — no CREMA, essentia, madmom, autochord, basic-pitch or CREPE.
  Key detection is therefore the chroma-template approach, which handles relative and
  parallel ambiguity poorly, and chord recognition is not available at all.
- **No other music generator** — no MusicGen/AudioCraft, YuE, DiffRhythm, Magenta or
  Riffusion. The models with the strongest advertised control (ACE-Step 1.5's BPM/key/
  time-signature conditioning, YuE2's editable ABC plan) are represented only partly or not
  at all here.
- **No software synth or notation tool** — no fluidsynth, timidity, musescore, lilypond or
  lmms. **This is the gap that changes the design.** The symbolic-first lane cannot render
  audio here without adding a small synth, so today the audio must come from HeartMuLa or
  ACE-Step. Symbolic artifacts (MIDI, chord charts, section maps) are still producible and
  still valuable as *control and verification text*, but "authored by construction" is not
  available end-to-end on this machine yet.

**Feasibility probe.** `spikes/measurement_probe.py` synthesises a known signal — a 92 BPM
click over an F# minor triad — and measures it back with the installed libraries. Result:
tempo **92.29 BPM** against a 92.0 target (0.29 error), key **F# minor** exactly, duration
exact, plus LUFS, true peak, clipping count, spectral centroid and onset count. The
deterministic layer the design depends on is real, not aspirational.

The probe also earned its keep by failing twice, which is the argument for validating every
measurement rather than trusting a library that merely exposes one:

1. librosa raised `RuntimeError: cannot cache function '__o_fold': no locator available`
   under numba until `NUMBA_CACHE_DIR` was pointed at a writable directory. Any deployment
   that containerises this must set it.
2. The first version called `beat_track` directly and returned **0.0 BPM**, because the
   pad's own amplitude modulation dominated the onset envelope. Switching to onset-strength
   autocorrelation with a sensible `start_bpm` fixed it. A tempo gate that "worked" because
   the library returned a number would have been wrong on the first real input.

**Recommended stack for this machine, no downloads.**

- **Generation:** **ACE-Step 1.5 XL turbo is the primary and reference lane.** All four
  weights are on disk, and the packaged graph
  `comfyui_workflow_templates_json/templates/audio_ace_step1_5_xl_turbo.json` is the
  canonical integration — 13 nodes, `UNETLoader → ModelSamplingAuraFlow → KSampler`
  (8 steps, cfg 1) `→ VAEDecodeAudio`, with `DualCLIPLoader` loading both the 0.6B and 4B
  encoders. Through its `TextEncodeAceStepAudio1.5` node it accepts `bpm`, `duration`,
  `timesignature`, `keyscale`, `language`, `seed`, `tags` and `lyrics` as conditioning, plus
  per-field negative metadata. HeartMuLa OSS 3B remains a viable alternate lyrics→song path,
  and Stable Audio Open covers instrumental beds.
- **Conditioning is prompt-level, not architectural.** In `comfy/text_encoders/ace15.py`,
  `_metas_to_cot` renders bpm/duration/keyscale/timesignature into a Chain-of-Thought text
  prompt and `_metas_to_cap` into a caption string, while duration also sets the LM token
  budget (`duration * 5` at 5 Hz). So BPM, key and meter are a strong prior rather than a
  guarantee, and any design must measure what it asks for.
- **Mechanical verification:** librosa + pyloudnorm + demucs, all installed. Tempo, key,
  duration, loudness, peak and vocal presence are covered.
- **Semantic verification:** the text-native half — plan and lyrics — is fully checkable
  today, because it is already text. ACE-Step 1.5 also advertises audio understanding (BPM,
  key, time signature, caption) and quality scoring, which can partly bridge the missing
  captioner — but it is the generator reading its own output, so it belongs in the fact sheet
  only as a flagged `generator_self_report` field, never as authoritative evidence.
  Independent ASR and a captioner are still absent, which leaves `sung == written lyric` and
  intelligibility `unverified` for now.
- That asymmetry is a finding in its own right: **on this machine, lyric and plan
  requirements are cheap and reliable to verify, while audio requirements are expensive and
  currently unverifiable.** Where a user can accept a requirement expressed at the lyric or
  plan level, that is where it should be expressed.

## Design implications

1. **A text-only judge cannot hear the track.** Every audio requirement must be converted to text/numeric evidence first: duration, tempo (Beat This!/librosa), key (CREMA), chord sequence (autochord), LUFS (pyloudnorm), vocal presence (Demucs), and lyric transcript (Whisper on vocals). Jev should adjudicate those extracted facts, not the waveform.
2. **Some requirements are exactly decidable and should be hard gates, not probabilities.** Duration, sample rate, loudness, and (with tolerance) tempo are deterministic. Key and chord are only probabilistic: text2midi tops out near 33.6% correct key, and audio key detection has relative/parallel ambiguity. Do not let a typed probability substitute for a measurement.
3. **Vocal-presence ≠ lyrics-compliance.** ASR hallucinates on sung vocals; require consensus between separated-vocal Whisper passes and an edit-distance threshold against the intended lyrics, as SongGen's preprocessing does.
4. **Generate symbols before audio.** A lyrics-then-ABC/MIDI-then-render pipeline (YuE2, ACE-Step 1.5) makes structure, key, tempo, and syllable counts inspectable and revisable in text. Pure audio models (DiffRhythm, SongGen, MusicGen) expose almost none of that.
5. **Respect hard capability ceilings.** SongGen: 30 s English; MusicGen/MAGNeT: instrumental only, no vocals; YuE: ~5 min; ACE-Step 1.5: 10 min. A brief outside these limits must be rejected or routed differently before generation.
6. **Licenses constrain commercial use.** MusicGen and MAGNeT weights are CC-BY-NC 4.0; YuE2 weights CC BY-NC 4.0; Stable Audio Open uses a gated community license; ACE-Step v1 (Apache-2.0) and ACE-Step 1.5 (MIT) are the cleanest permissive options. DiffRhythm's license metadata is contradictory — verify before shipping.
7. **Best-of-N only works with a calibrated verifier.** Self-preference and perplexity biases mean an LLM judge will reward fluent, conventional output. Use Jev for structured classification of extracted facts with explicit thresholds, and keep a deterministic MIR layer as the authority for measurable constraints.
8. **Subjective fields (mood, era, explicitness, vocal style) are genuinely uncertain.** Label them as probabilities (Score/Noul) and surface unresolved conflicts rather than silently passing them; no available tool measures "90s production" or explicitness in audio deterministically.
