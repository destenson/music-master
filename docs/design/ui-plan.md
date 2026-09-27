# Music Master — UI and front-end plan

Status: plan, not built. Companion to [`compliance-architecture.md`](compliance-architecture.md),
[`tag-vocabulary.md`](tag-vocabulary.md) and [`lyric-templates.md`](lyric-templates.md).

## 1. Are we ready?

**Yes for a v1 that covers brief → prompt → render → verify → listen.** The hard part is already
done, and it is not the part people expect: the *data model* is the UI. `vocabulary/tag-bins.json`
already declares, per bin, the `control` to draw, the `group` to place it in, `min`/`max_selections`,
`help`, `priority`, `caution`, `emits_tag`, `polarity` and `template_ref`. The original design note
said "adding an option to the file adds a checkbox; no UI code changes" — so a form generator is the
main component, not 32 hand-built forms.

What exists and can be driven today:

| Layer | State | Evidence |
| --- | --- | --- |
| Vocabulary (32 bins, 792 options) | complete, validated | `vocabulary/tag-bins.json`, `validate_vocabulary.py` |
| Lyric grammar (132 tags, 6 pools, 3 mechanisms) | complete, validated | `vocabulary/section-tags.json` |
| Structure templates, rhyme schemes, delivery profiles | 17 / 13 / 6 | `vocabulary/structure-templates.json` and siblings |
| Time budget | working | `vocabulary/timeline.py` |
| Tag rendering with budget and polarity | working | `vocabulary/render_tags.py` |
| Lyric checking (sections, phrases, rhyme, fit, tags, transitions, clichés) | working | `vocabulary/check_lyrics.py` |
| Prompt + workflow build, ComfyUI submit, takes | working | `songs/*/build_and_submit.py` |
| Measurement (mechanical, vocal character, transitions, dynamics) | working | `songs/*/analyse_*.py`, `verify_render.py` |
| Schemas | 9 written | `schemas/` |

What is missing, and what the UI must therefore show honestly rather than fake:

- **No oracle configured.** The whole semantic battery is designed and unrun, so caption/lyric
  consistency, theme adherence and hook payoff are `unverified`.
- **No captioner.** Genre fidelity, production character, instrumentation audibility and vocal
  character have no evidence channel. Building one is now planned **ahead of the UI** — see
  [`captioner.md`](captioner.md), and [`evidence-classes.md`](evidence-classes.md) for the trust
  rules it has to obey.
- **No ASR, deliberately deferred.** Intelligibility and `sung == written lyric` have no evidence
  channel and will keep reporting `unverified`.
- **Transitions and per-section arrangement are not controllable** through lyric tags — measured
  twice, 1/9–2/9 met and 0/7–1/7 met. The UI must not render a control that does nothing.
- **The screening metrics are genre-dependent.** Harmonicity 0.25 is a failure on one song and
  correct on another. A bare score in a UI is a lie by omission.

## 2. What the UI is for

**Goals.**

1. Make the four artifacts (composition, lyrics, prompt, audio) editable and inspectable as a
   bundle, so the source/build distinction is visible rather than notional.
2. Put the constraints where the decisions are made: syllable budget next to the line, tag budget
   next to the tags, time budget next to the section.
3. Make the compliance report the primary output surface, not a footnote — including its
   `unverified` rows.
4. Make a take selectable by seed and reproducible on demand.
5. Keep the creative loop fast: nothing modal, nothing blocking, validation inline.

**Non-goals for v1.**

- Not a DAW. No audio editing, no mixing, no stem surgery.
- Not a model trainer. No LoRA or fine-tuning UI.
- Not multi-user. A single local workspace.
- Not a vocabulary editor in v1 (the file + validator workflow is good enough; see M5).
- Not a phone app.

## 3. Design principles

Each of these is a consequence of something measured or built, not a preference.

1. **The vocabulary is the form.** Controls are generated from `control`; groups from `group`;
   help from `help`; caps from `min`/`max_selections`. No hand-coded field lists anywhere.
2. **Four artifacts, four editors, one bundle.** The user always knows whether they are editing
   source (composition, lyrics, prompt) or looking at a build product (audio).
3. **`unverified` is never green.** Not checked is not passed. Colour, icon and wording must make
   the difference unmissable — this is the failure mode the entire project exists to avoid.
4. **Never conflate the two guarantees.** Intent fidelity (does the prompt encode the brief?) is
   cheap and text-native. Realization fidelity (does the audio realize the prompt?) is expensive
   and partly impossible. Separate panes, separate headings, separate counts.
5. **Show the budget always.** Every authoring control displays its cost live: tags used, syllables
   used, seconds used. A choice whose cost is invisible is a choice made blind.
6. **Do not offer controls that do not work.** Transition tags are declared and verified but rarely
   honoured by the model; a disabled checkbox with a reason beats an enabled one that lies.
7. **A metric needs an expected direction.** Never show a bare score. Show it against what the spec
   asked for, derived from the template's vocal tags and the `avoid` bin.
8. **Artifacts are content-addressed, not ordinal.** Address takes by seed, prompts by hash. The
   `take1.mp3` collision that overwrote a batch is why.
9. **Reproducibility is a button.** "Re-render exactly this" from the recorded prompt hash, seed,
   vocabulary version and sampler settings.
10. **The report is evidence, not a score.** For every verdict, show what was measured, what was
    asked, and which checker decided.
11. **Keyboard-first.** This is a text-heavy creative tool; the mouse is for audio.

## 4. Information architecture

```mermaid
flowchart LR
    WS[Workspace] --> BR[Brief]
    BR --> SP[RequirementSpec<br/>confirm assumptions]
    SP --> BD[Builder<br/>tag bins]
    SP --> ST[Structure and time]
    BD --> PV[Prompt preview<br/>+ negatives, metadata]
    ST --> PV
    LY[Lyric editor] --> PV
    PV --> RN[Render console]
    RN --> TK[Takes]
    TK --> RP[Report]
    RP -->|unmet or uncertain| BD
    RP -->|unmet or uncertain| LY
    TK -->|keep| BUN[(Song bundle)]
    RP --> BUN
```

Eleven surfaces, of which four carry the weight: **Builder**, **Lyric editor**, **Takes**, **Report**.

| # | Surface | Purpose | Milestone |
| --- | --- | --- | --- |
| 1 | Workspace | songs, statuses, new song | M1 |
| 2 | Brief & spec | brief in, typed requirements out, confirm assumptions | M2 |
| 3 | Builder | the generated bin form, live caption | M2 |
| 4 | Structure & time | template, tempo, duration, timeline, transitions | M2 |
| 5 | Lyric editor | text + grammar lens + per-section inspector | M3 |
| 6 | Prompt | canonical prompt, negatives, metadata, target, diff, hash | M3 |
| 7 | Render console | preflight, queue, progress, retry | M4 |
| 8 | Takes | seed-addressed grid, waveform by section, A/B, keep | M4 |
| 9 | Report | intent vs realization, per-requirement evidence, unverified | M1 (read-only) → M5 (live) |
| 10 | Vocabulary | browse, validate, extend | M6 |
| 11 | Settings | oracle, key, target, paths, egress statement | M4 |

## 5. The core/UI seam

The single biggest architectural risk is reimplementing the checks in the UI. Everything the
interface shows already exists as a script; the UI must call it, not copy it.

**Extract the scripts into one package** (`musicmaster/`), with the current files becoming modules
with the same logic and no duplicated rules:

```
musicmaster/
  # Text tier -- pure, stdlib only, JSON in / JSON out. Runs under CPython and under Pyodide.
  vocabulary.py   # load, validate, options, polarity, label maps   (from validate_vocabulary.py)
  timeline.py     # build_timeline, check_fit, rates                (from timeline.py)
  templates.py    # template lookup, brief, bar plan, scaling        (from structure_templates.py)
  lyrics.py       # parse, check, template conformance               (from check_lyrics.py)
  render.py       # render tags, budget, negatives                   (from render_tags.py)
  prompt.py       # canonical prompt, target rendering, hashing      (M2/M3; no source script yet)

  # Boundary -- the manifest is pure (hashing, staleness); reading and writing the song directory is not.
  bundle.py       # song directory, manifest, manifest hashes

  # Execute tier -- needs a GPU, a filesystem or a network. Host only.
  generate.py     # Generator protocol, ComfyUI adapter       (from build_and_submit.py)
  measure.py      # mechanical, vocals, transitions, dynamics (from analyse_*.py)
  oracle.py       # Jev / local / replay

  api.py          # what the local backend exposes; the SPA imports the text tier directly
  cli.py          # musicmaster brief|compose|lyrics|prompt|render|verify
```

Those three groups are not a filing convention; they are the seam, and the thing that varies across
it is **runtime capability** — what a WebAssembly sandbox can do versus what needs a GPU, a
filesystem and a network. Putting the seam there is what lets the UI be static without becoming a
second implementation of the checks:

- **CPython** imports the text tier for the CLI, the tests and the local backend.
- **Pyodide** imports the same source in the browser, as a WebAssembly CPython.

Two adapters means a real seam, and the deletion test passes: remove the text tier and the checks
reappear in TypeScript, which is the drift this section exists to prevent. It also makes the
interface a handful of pure functions — `render`, `build_timeline`, the lyric checks — rather than a
route list, which is far less for a caller to learn.

**The invariant that keeps it true: the text tier imports nothing outside the standard library.**
That is an interface fact, not a style preference — a Pyodide caller cannot install numpy — so it is
asserted by a test rather than left to review. A dependency that breaks it means the module has
crossed into the execute tier and should move.

None of this is assumed. [`spikes/pyodide_text_core`](../../spikes/pyodide_text_core/README.md) runs
the current scripts under both runtimes: **seven CLI invocations byte-identical** between native
CPython 3.12.3 and Pyodide 3.14.2, and the full per-caret lyric check at **~12 ms median / ~17 ms
p95** — about twice native, and inside a frame.

The execute tier keeps an HTTP surface, because it genuinely needs one, but it is optional rather
than the only way in: a thin local server exposes `api.py` over HTTP/JSON plus server-sent events for
progress. The CLI, the SPA and the local backend are three clients of one core.

What that buys, per surface:

| Surface | Static SPA, nothing running | Optional local backend |
| --- | --- | --- |
| Workspace, brief & spec, builder, structure & time | live — vocabulary, rendering, timeline | — |
| Lyric editor, prompt | live — grammar lens, checks, hashing | — |
| Report — intent fidelity | live | — |
| Report — realization fidelity | only if measurements were committed | live measurement |
| Render console, takes, settings, oracle | unavailable, and says so | required |

The API the local backend needs, at minimum:

```
GET  /api/songs                          -> [{id, status, caption, updated}]
POST /api/songs                          -> create from a brief
GET  /api/songs/:id/bundle               -> artifacts + hashes + manifest
GET  /api/songs/:id/spec                 -> RequirementSpec + assumptions pending
POST /api/songs/:id/spec/confirm         -> confirm inferred requirements
GET  /api/vocabulary                     -> bins, options, groups, controls, cautions
GET  /api/templates                      -> templates + rhyme schemes + profiles
POST /api/songs/:id/render               -> {caption, prompt}      -> prompt + tag budget + coherence
GET  /api/songs/:id/timeline?bpm&duration-> rows + totals + budgets
POST /api/songs/:id/lyrics/check         -> findings, per-section inspector data
POST /api/songs/:id/lyrics/brief         -> the writing brief for this template
GET  /api/songs/:id/prompt               -> canonical prompt, hash, target rendering
POST /api/songs/:id/render               -> queue takes; SSE /api/jobs/:id for progress
GET  /api/songs/:id/takes                -> seed-addressed takes + screening metrics
POST /api/songs/:id/takes/:seed/keep     -> promote a take
GET  /api/songs/:id/report               -> per-requirement verdicts + evidence + unverified
GET  /api/capabilities                   -> target capabilities (for gating controls)
```

Capability gating matters: `GET /api/capabilities` is how the builder knows to disable `5/4` and
`7/8` with a reason, and how a future model swap changes the form without a code change.

Several of those routes are text-tier work the SPA now does itself — vocabulary, templates, timeline
and the lyric checks. They stay on the backend for callers that have no WASM core: a script, a CI job,
another machine. That is deliberate duplication of the *transport*, never of the logic, which is the
distinction the seam exists to keep.

## 6. The four surfaces that matter

### 6.1 Builder

```
┌ Music Master ─── rap-metal-groove ───────── target: ACE-Step 1.5 XL turbo ──────── [Render ▸] ┐
│ ┌ Style ──────────────────┐ ┌ Rhythm ─────────────────┐ ┌ Live caption ─────────────────────┐ │
│ │ Genre     [Rap Metal ▾] │ │ Tempo   92 ──●───── BPM │ │ Rap Metal, Hip-Hop, Funk, Punk,   │ │
│ │ Fusion    ☑ Hip-Hop     │ │ Time sig [4/4     ▾] ⛔ │ │ Syncopated, Breakbeat, Groovy,    │ │
│ │           ☑ Funk        │ │ Key      [E ▾][minor▾]  │ │ Offbeat, Live Drums, Punchy Kick, │ │
│ │           ☑ Punk        │ │ Tuning   [Drop D  ▾]    │ │ Fingerstyle Bass, Distorted Bass, │ │
│ ├ Groove ─────────────────┤ ├ Vocals ────────────────┤ │ Distorted Guitar, Downtuned …     │ │
│ │ ☑ Syncopated ☑ Breakbeat│ │ Lead ☑ Male Rap Vocals  │ │                                   │ │
│ │ ☑ Groovy     ☑ Offbeat  │ │      ☑ Spoken Word      │ │ tags 32 / 32    omitted 5 ⓘ       │ │
│ └─────────────────────────┘ └─────────────────────────┘ │ [Copy] [Diff] [Export]            │ │
│                                                          └───────────────────────────────────┘ │
│ ⚠ 1 caution (5/4 unreliable)   ⛔ 2 unavailable on this target   ⚠ 1 coherence note            │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Groups are collapsible and remember their state; the group order comes from the data.
- The budget meter is always visible; over-budget tags show what will be dropped, by priority.
- `caution` renders as a warning chip on the option, not a tooltip nobody reads.
- Capability-unavailable options are disabled with the reason inline (`⛔ unreliable on this model`).
- The `avoid` bin is a separate panel labelled **Must not appear**, visually distinct because it
  subtracts rather than adds.

### 6.2 Lyric editor

The hardest surface, and the one with a real design decision: **the lyric is the user's text, and it
must stay a text file.** Structured editing that cannot round-trip is a trap. So: a text editor with
a grammar lens, plus an inspector that reads it.

```
┌ Lyrics ── rap-metal-groove ────────────── [copy writing brief] [check ✓ clean] ────────────────┐
│ ┌ text ───────────────────────────────┐ ┌ section inspector ────────────────────────────────┐ │
│ │ [Verse 1]                           │ │ [Verse 1]    16 bars · 41.7s · 8 lines            │ │
│ │ [rap]                               │ │  syllables   115 / 64–128     ceiling 271  2.8/s  │ │
│ │ [spoken word]                       │ │  phrases     ▇▇▇▇▇▇▇▇▇▇ all inside 8–16            │ │
│ │ [driving]                           │ │  rhyme       internal · 2 interior pairs ✓        │ │
│ │ [aggressive]                        │ │  tags        rap ✓ spoken word ✓ driving ✓        │ │
│ │ They sold you the future, then…     │ │  exit        [build-up] ✓                         │ │
│ │ …                                   │ │  notes       ⚠ line 16 crowded — add a caesura /  │ │
│ │ [build-up]                          │ └───────────────────────────────────────────────────┘ │
│ └─────────────────────────────────────┘                                                       │
│ ┌ timeline ─────────────────────────────────────────────────────────────────────────────────┐  │
│ │ 0:00 ▏Intro 0:10 ▏Verse 1 0:52 ▏Chorus 1:13 ▏Verse 2 1:55 ▏Chorus 2:35 ▏Solo 2:56 ▏Chorus │  │
│ │      ░░░░░      ▓▓▓▓▓▓▓▓▓▓      ███████      ▓▓▓▓▓▓▓▓▓▓      ███████      ▒▒▒▒▒▒      ██████│  │
│ └───────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Behaviour:

- Tag autocomplete from the six pools, filtered by what the current slot allows (a modifier is only
  offered after a section header; a transition is only offered near the end of a section).
- Unknown or mis-stacked tags get squiggles, not a modal, with the fix in the tooltip.
- Caecura markers (`/`, `|`) render as a visible thin break so phrase segmentation is legible.
- The inspector is per-section and updates on the caret, not on save.
- Clicking a finding ("add a caesura") inserts the marker at the right place. Findings are
  actionable, not just reported.
- The "copy writing brief" button emits exactly what `structure_templates.py --brief` prints, so a
  user can take the same brief to an external model and paste the result back.

### 6.3 Takes

```
┌ Takes ── rap-metal-groove ──────────────────────────── [render 3 more] [render exactly seed 4409]┐
│ ┌ seed 4409 ────────────────────────────────┐ ┌ seed 12328 ───────────────────────────────┐   │
│ │ ▁▂▅▇▅▂▁▂▅▇▅▂▁▂▅▇▅▂▁▂▅▇▅▂  ▶ 3:08          │ │ ▁▂▅▇▅▂▁▂▅▇▅▂▁▂▅▇▅▂▁▂▅▇▅▂  ▶ 3:08         │   │
│ │ ▏Intro▏Verse▏Chorus▏Verse▏Chorus▏Solo…    │ │ ▏Intro▏Verse▏Chorus▏Verse▏Chorus▏Solo…   │   │
│ │ harmonicity 0.25 ─ expected LOW ✓         │ │ harmonicity 0.34 ─ expected LOW ✓        │   │
│ │ transitions 1/7 · dynamics flat           │ │ transitions 1/7 · dynamics flat          │   │
│ │ [keep] [discard] [details]                │ │ [keep] [discard] [details]               │   │
│ └───────────────────────────────────────────┘ └──────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

The pane also gains a **caption panel**: the free caption per section, the structured scores against
the vocabulary, and the detector-agreement flags. Captions and scores are labelled with their evidence
class, so a reader can see that "distorted guitar 0.38" is a describer's opinion and "4.94 onsets/s" is
a measurement.

Every metric carries its **expected direction**, derived from the spec — that is the difference
between this pane and a dashboard. "harmonicity 0.25 ✓ expected LOW" is information; "0.25" alone is
noise a user will misread.

### 6.4 Report

```
┌ Compliance ── rap-metal-groove / seed 4409 ───────────────── overall: 4 met, 1 unmet ──────────┐
│ INTENT FIDELITY      checked on the text, before rendering                        12 / 12 met  │
│ REALIZATION FIDELITY measured on the audio                                          4 / 5 met  │
│                                                                                               │
│ requirement   asked            measured                verdict   decided by                    │
│ duration      187.8s ± 2       187.8s                  met       code · audio.dsp.duration     │
│ tempo         92 BPM ± 6       184.57  (2× octave)     met       code · audio.dsp.tempo        │
│ key           E minor          E major   (corr 0.647)  UNMET     code · audio.dsp.key          │
│ clipping      ≤ 100 ppm        56.7 ppm                met       code · audio.dsp.peak         │
│                                                                                               │
│ UNVERIFIED — nothing checked these. Not passed, not failed.                                   │
│   genre fidelity · production character · vocal intelligibility · sung == written lyric       │
│   needs: a music captioner and an independent ASR                                             │
│                                                                                               │
│ DEFERRED — no oracle configured                                                               │
│   caption/lyric consistency · theme adherence · hook payoff                                   │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

The pane that makes this project worth building is the `UNVERIFIED` block, and it must be visually
louder than the green ticks. A compliance report that quietly omits what it could not check is
exactly the artefact this design was written to prevent.

## 7. Data and persistence

No database. **The song directory is the record**, which is already true on disk and is the design's
whole point:

```
songs/rap-metal-groove/
  brief.md  song.json  selections.json  lyrics.md      <- source, hand-edited
  composition.json  prompt.json  workflow.json         <- generated, regenerable
  RESULT.md                                            <- hand-written write-up
  build_and_submit.py  verify_render.py  analyse_*.py  <- tooling
```

A static SPA cannot write to the song directory, so the loop is explicit: it edits in memory and
**exports** the changed source files (`brief.md`, `selections.json`, `lyrics.md`, `prompt.json`), and
they land in the repo as a commit. That is a real cost, and it is the honest one — the alternative is
letting a browser hold the record. The local backend, when it is running, may write the files
directly, which removes the copy step without changing where the truth lives.

Where the UI does have the directory, it writes only the source files plus the manifest. Generated
artifacts are rebuilt. The manifest records hashes, seeds, vocabulary version and environment, so the
workspace listing can show "stale" when a source artifact changed after the last render — which is
the UI's most valuable piece of bookkeeping and costs nothing because the hashes already exist.

Git is the versioning system. The UI does not invent one; it offers "show diff" and "revert file".

## 8. Long-running work

Renders take ~60 s each on the 3090 and the GPU is shared with other work, so:

- Submission is asynchronous and the UI never blocks. Progress over SSE.
- A preflight before queueing: is the service up, which models are loaded, how much VRAM is free.
- Failure is a first-class state: a rejected workflow shows ComfyUI's own error text, not "failed".
- A queue view with cancel. Batch renders are N sequential submissions, not one batch, because peak
  VRAM and per-take reproducibility both matter (already the behaviour in `build_and_submit.py`).

## 9. Honesty in affordances

Four specific places where the UI must resist a nicer-looking lie:

| Temptation | Instead |
| --- | --- |
| A green tick per requirement | `unverified` gets its own colour, its own heading, and a stated reason |
| A quality number for the take | the number plus its expected direction, plus "advisory" where the detector is approximate |
| An enabled transition control | enabled, but marked **declared — usually not honoured by this model** and always verified |
| A page that looks complete with no backend running | the surfaces that need one read **unavailable, and why**, rather than rendering empty; the build stamps the artifact hashes and vocabulary version it was made from |

## 10. Tech stack

**Recommended: a static single-page app that is useful with no server at all**, plus an optional
local backend for the work that needs a GPU.

- **The SPA** is a component-framework build (Svelte or React) with `wavesurfer.js` for the waveform,
  served as static files. It carries the text tier as a Pyodide runtime and calls it directly, so the
  builder, the time budget and the lyric inspector are live on a page that has never talked to a
  server.
- **The local backend** is FastAPI over the same core: render submission and progress (SSE),
  measurement, the audio files, and the oracle. It is optional. With it absent the SPA degrades to
  the text tier and says so, in place of the surfaces it cannot populate.

Reasons for the static default: it deploys anywhere or opens from a checkout, it has no port to keep
and no service to leave running, and the checks the UI shows are the same code the CLI runs. It also
keeps `unverified` honest — a page that never reached an oracle has nothing to fake it with.

Rejected: Gradio/Streamlit (fast for a demo, cannot express the inspector-and-editor layout or the
audition grid); Electron/Tauri (no benefit over a static page, more packaging); a native toolkit
(would duplicate the audio and layout work for nothing).

"Static" means no *application* server, not `file://`: WASM and ES-module loading want to be served
over HTTP, which any static host or `python3 -m http.server` provides. Hosting is undecided and
nothing here depends on GitHub Pages specifically; the two things a project-page deploy would need —
a configurable base path, and hash routing or a 404 fallback — are cheap and deferred.

The local backend runs on a dedicated port (e.g. `127.0.0.1:8787`) and is separate from the DSH Web
GUI on 3080. A deployed page reaching it is an enhancement, never a dependency: browsers treat
`127.0.0.1` as a trustworthy origin so an HTTPS page may call it, but CORS and Chrome's Private
Network Access preflight both apply, and the text tier must never assume the service is there.

## 11. Phasing

| Milestone | Content | Done when |
| --- | --- | --- |
| **C** | **Captioner and evidence classes** — `describe.py`, the gauge, structured scoring, captions ([`captioner.md`](captioner.md)) | per-class gauge measured; genre, vocal and instrument classes either decided or explicitly not; `unverified` count falls by the classes that passed |
| **M0** | Extract `musicmaster/` package + CLI into the text and execute tiers; current scripts become thin wrappers | the two existing songs build, check and report **byte-identically** through the package; the suite asserts the values it computes, and a guard test asserts the text tier imports only the standard library |
| **M1** | Read-only workspace + report viewer, shipped as a static build with nothing running | opening either existing song shows its artifacts and verdicts, with `unverified` correct and no backend required |
| **M2** | Brief → spec → builder → structure/time | a new song can be authored to a valid prompt without touching a file |
| **M3** | Lyric editor with grammar lens and inspector | the rap-metal lyric can be written in the UI, and every finding the CLI produces is reproduced |
| **M4** | Render console, takes, audition, settings, oracle wiring | render 3 takes, compare, keep one, see the report |
| **M5** | Live compliance battery (oracle + captioner + ASR) | `unverified` rows start disappearing, and the count is shown |
| **M6** | Vocabulary browser/editor, presets, prompt import | a new option can be added from the UI and validated |

M0 is the critical one and it is invisible. Building UI first would guarantee two implementations of
the same checks, and the second one would drift.

## 12. Open questions

1. **Where does the metric expectation come from?** Derivable for vocal character from the template's
   `vocals` plus the `avoid` bin, but transition and dynamics expectations are ad hoc. Needs a small
   declared-expectation field on the requirement, or a per-song expectations block.
2. **How structured is the lyric editor?** Text-with-lens is the recommendation because it round-trips,
   but section reordering and line-count enforcement are much nicer structurally. Worth a spike.
3. ~~Do we build the captioner and ASR before the UI?~~ **Resolved: the captioner goes first, ASR is
   deferred.** The captioner covers roughly ten requirement classes, which is most of what the UI
   would otherwise show as `unverified`; ASR covers two and its weights are not on disk. The `unverified`
   state is still built into the UI from day one — it just starts smaller than it would have.
4. **One song at a time or a project?** The bundle is per-song; a project would group songs sharing a
   vocabulary version and a brief.
5. **Does the vocabulary admin belong in the app?** The file-plus-validator loop is good and the
   validator catches things a form would not. A read-only browser may be the whole answer.
6. **How much audition UI?** Waveform, section markers, A/B and blind comparison is real work; a track
   list with an audio element is an afternoon. Start small.
7. **Where does the UI live, now that the core is split?** Resolved in shape: the text tier runs
   wherever the page runs and so has no location, and only the execute tier does — reached over HTTP
   wherever it is hosted. The file-path assumptions in the current scripts are what still has to go,
   and M0 removes them.
8. **How does an edit get back into the repo?** Export-and-commit works with no server and is the
   default; the local backend may write files directly when it is running. Committing through the
   GitHub API with a token would let a deployed page save, and is deferred rather than rejected.

## 13. Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Two implementations of the checks | the UI's green tick and the CLI's verdict diverge | M0 first, and the text tier runs in the browser as the same WASM Python the CLI uses, so there is no second implementation; a guard test keeps it stdlib-only |
| The builder is a 792-option wall | users bounce off a form that looks like a spreadsheet | presets, search, progressive disclosure by group, and defaults from the brief |
| Green ticks creep in | the exact failure the project exists to prevent | `unverified` styling is a review gate, and the count is asserted in tests |
| ComfyUI is shared and external | renders fail or stall while the UI looks broken | preflight, explicit queue states, ComfyUI's own errors surfaced verbatim |
| Scope | eleven surfaces is a large v1 | milestones, and M1 is genuinely useful alone |
| Metric theatre | a dashboard of numbers nobody can act on | every metric shows its expected direction and its detector's reliability |
| Pyodide is several MB before the first check runs | a cold cache makes the SPA feel broken before it does anything | load it after first paint, behind the first surface that needs it; the vocabulary payload itself is ~150 KB |
| A deployed page looks finished while the execute tier is absent | overstating what was checked is the failure this project exists to prevent | the absent backend is a rendered state rather than an empty one, and `unverified` plus the build stamp stay visible |
| The local backend is unreachable from a deployed page | the enhancement fails silently and the UI looks broken | optional by construction — the text tier never depends on it, and a CORS or private-network failure surfaces as "backend unavailable" |

## 14. First commit of the next session

1. `musicmaster/` package skeleton, extracting the five text modules verbatim into the stdlib-only
   tier, with the current files becoming thin wrappers.
2. Unit tests for the values the tier computes, with expectations derived from the definitions
   rather than captured from output, plus the same package running under Pyodide.
   [`spikes/pyodide_text_core`](../../spikes/pyodide_text_core/README.md) covers the runtime half;
   the arithmetic and mapping assertions live in `tests/test_text_tier.py`.
3. A guard test asserting the text tier imports nothing outside the standard library.
4. Nothing else. The SPA starts once the core has one entry point and one proven runtime story.
