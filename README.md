# [music-master](https://destenson.github.com/music-master)

An easy-to-use, full-featured music generator.

Pick the sound from a labelled vocabulary — genre, mood, tempo, key, instruments, vocal delivery,
structure — write or generate the lyrics, and render the song. Nothing is typed into a prompt box:
every choice shows the exact tag it contributes, so the caption is something you can read, edit and
reproduce rather than a string you have to guess your way to.

The UI is the product. It runs the `musicmaster/` text tier in the browser under Pyodide, so the
form, the caption, the time budget and the lyric findings all come from the same implementation the
renderer uses. Renders go to a ComfyUI target — a local server or Comfy Cloud — running ACE-Step 1.5,
and a preview auditions the whole song at a couple of sampler steps before committing to a full take.

Status: the generator works end to end. The vocabulary, the caption renderer, the lyric checker, the
time budget and the prompt builder are real and packaged as `musicmaster/`, and the browser builds a
song, renders it, previews it and streams it from a radio station. The check that runs before a
render is real too: the caption is decided in code against the selections, and the lyrics are judged
one requirement at a time by a Jev transport behind a key the user supplies. With no key, or where
the API refuses the page's origin, the caption is still checked and every lyric requirement comes
back `unverified` rather than decided.

## What it produces

A song, and the files that make it reproducible. A render is an audio file — ACE-Step 1.5 writes an
MP3 through ComfyUI — and the page also hands you the exact bytes behind the take: `prompt.json`, the
canonical, model-agnostic request; `composition.json`, the arrangement it pins; and `workflow.json`,
the complete ACE-Step 1.5 graph for that take. The graph is not tied to the service the page is
pointed at: download it and queue it on another ComfyUI instance.

The text is the record, because a stochastic render is opaque and hard to diff while the prompt and
the lyrics are cheap, textual and comparable. It is what makes a take reproducible.

```
songs/<song_id>/
  song.json  selections.json  brief.md  lyrics.md
  composition.json  prompt.json  workflow.json  RESULT.md
```

The render itself lands in ComfyUI's output directory and is played from the page; it is not part of
the record, because a new take is a new file. Each part has its own independently runnable stage, so
the lyrics can be rewritten and the song re-rendered without re-planning the composition. The
**prompt is the one to get right first**: it is the input to the generator and so determines the
output, it is a canonical, model-agnostic object rather than a string, it is rendered per target by
the generator adapter, and it is fully checkable *before* any GPU work.

That split also makes an important distinction explicit. **Intent fidelity** — does the prompt
faithfully encode the brief? — is cheap and exact, because the prompt is text. **Realization
fidelity** — does the audio realize the prompt? — is expensive and partly unverifiable. Prompt
verification does not imply audio compliance, so the checking design reports them separately.

## Documents

| Document | What it covers |
| --- | --- |
| [`docs/design/compliance-architecture.md`](docs/design/compliance-architecture.md) | The design: the artifact bundle, the prompt artifact, stages, requirement taxonomy, the compliance battery, gating policy, repair loop, risks, validation plan |
| [`docs/design/pre-render-check.md`](docs/design/pre-render-check.md) | The check that runs before a render: the decision it answers, why the caption is code and the lyrics are the oracle's, the question shape, the gauge, and the non-uses |
| [`docs/design/tag-vocabulary.md`](docs/design/tag-vocabulary.md) | The tag bins: what a bin declares, the UI controls built from them, how selections render into the comma-separated prompt, and how the vocabulary keeps the UI, the prompt and the compliance battery in step |
| [`docs/design/radio-stations.md`](docs/design/radio-stations.md) | The radio: what a station states, how a song is drawn from its pools, the four-stage pipeline and the look-ahead buffer, the output layout, and what the radio cannot do |
| [`docs/design/lyric-templates.md`](docs/design/lyric-templates.md) | Song structures and rhyme schemes as a contract: the writing brief handed to the lyric generator, the bar plan handed to the composer, and the conformance check on the result |
| [`docs/design/ui-plan.md`](docs/design/ui-plan.md) | The front-end plan: readiness, design principles, information architecture, the core/UI seam, the four surfaces that matter, phasing from core extraction to live verification |
| [`docs/design/captioner.md`](docs/design/captioner.md) | The captioner: what audio description entails, the two outputs it must produce, model choices, the gauge that decides what it may decide, and what it must not be used for |
| [`docs/design/evidence-classes.md`](docs/design/evidence-classes.md) | Measurement, description, self-report and oracle: what each may decide alone, why description is never sole evidence for a hard requirement, and the two counts the report must carry |
| [`docs/research/jev-and-decision-models.md`](docs/research/jev-and-decision-models.md) | What Jev is, what it measures, what the sibling projects already learned, and the open alternatives (including self-hosted) |
| [`docs/research/music-generation-landscape.md`](docs/research/music-generation-landscape.md) | Open lyrics-to-song and text-to-music models, controllability, and the MIR tools that make audio judgeable as text |
| [`docs/research/prompting-rules.md`](docs/research/prompting-rules.md) | What the generator's own tutorial says about prompting: the caption/metadata split, structure tags, caption↔lyric consistency, control boundaries, and the three sources of randomness |
| [`docs/research/suno-prompting-principles.md`](docs/research/suno-prompting-principles.md) | The "universal" prompting ideas the ACE-Step guide points at |

## The tag vocabulary

The tag string is **rendered from selections**, not typed. 30 bins of properties — genre,
scene, tempo, drums, bass, harmonies, synths, vocals, delivery, production, timbre, mood,
exclusions and more — with **743 options** between them, each labelled with the exact tag text it
emits. The lyrics have their own vocabulary too: **59 section tags** across 5 pools, with a
grammar and the caption/lyric consistency rules.

```bash
python3 vocabulary/validate_vocabulary.py     # bins, ids, labels, references, limits, tags
python3 vocabulary/render_tags.py vocabulary/examples/late-night-trap.json
python3 vocabulary/check_lyrics.py vocabulary/examples/lyrics-late-night-trap.md \
    --selections=vocabulary/examples/late-night-trap.json
python3 vocabulary/check_lyrics.py --self-test
```

Rendering the motivating example yields 13 tags, and the renderer reproduces the fixture
exactly. It is 13 rather than 14 because the example's `95 BPM` was **moved out of the caption
into `metadata.bpm`** — the generator's own guide says tempo, key and time signature belong in
the metadata parameters and should not be written into the caption, so those bins are
metadata-only.

The lyrics fixtures are the real paired example — the caption and lyrics that ship together with
the packaged ComfyUI template. Running the checker on them found: no blank line between sections
(four warnings, against explicit guidance), no modifiers or performance tags anywhere, almost no
internal rhyme or alliteration (it reads as a technical jingle rather than a crafted lyric), and
heavy technical jargon the model is likely to slur.

It also caught a modelling error in the checker itself. Counting syllables per printed line flagged
ten verse lines as over-long; counting per **phrase** — `Open up the canvas` / `blank slate on my
screen` is 6/5, not 11 — flags the two lines that genuinely have no internal break. Cadence splits
lines, so the line is the wrong unit. Cross-line embedded rhyme is now deliberately not reported at
all: stress and vowel length decide whether two syllables rhyme and spelling encodes neither, so
that number would have been an artifact.

## Templates

Writing is easier and checkable when the shape is chosen first. **15 song structures**, **13
rhyme schemes** and **6 delivery profiles** are held as data, and each template is used four ways —
as a brief, as a bar plan, as a time budget, and as a conformance check:

```bash
python3 vocabulary/structure_templates.py --list
python3 vocabulary/structure_templates.py --template=pop_standard --brief --bpm=95 --duration=180
python3 vocabulary/structure_templates.py --template=pop_standard --timeline --bpm=95 --duration=180
python3 vocabulary/check_lyrics.py lyrics.md --template=pop_standard --bpm=95
```

A template is a contract rather than a label: it carries the section order, bar counts, lines per
section, the rhyme scheme each section is written to, an energy arc, and where the hook is. The
`structure` bin in the vocabulary points at one via `template_ref`, so choosing a form in the UI is
what selects the contract. Section sequence and line counts are checked exactly; rhyme conformance
is advisory, because the detector is spelling-based and demonstrably misses real rhymes. The brief's
own notes are not lyrics: a model that copies a line such as `Energy 3/5` into a section has it
stripped from the finished draft, and the checker reports one that was typed or pasted by hand. The
same repair reads a direction the model wrote without brackets — `Low energy`, `Melodic hook`,
`(instrumental)` — because the renderer only sees brackets and sings everything else: a tag the
grammar takes bare is bracketed, a multi-word name it has no tag for is dropped, and a transition
glued to the last lyric line is moved onto its own line. A one-word name is left alone, because `Raw`
at the top of a section is as likely a lyric as a direction. Only a tag at a section's edge, or
directly under one that is already bracketed, is read that way; the same words mid-phrase are a
lyric. The repair is never silent: the Lyrics tab names every line it dropped or rewrote, with the
line number to jump to, so what changed in the words is visible rather than assumed.

### The time budget

A three-minute song is not three minutes of words, so the plan separates them and each section gets
a **budget** (`lines x band`, what the writer is asked for) and a **ceiling** (`singable seconds x
syllables per second`, what the clock allows). The budget is clipped by the ceiling, because stating
a band the section cannot physically hold is advice that is wrong on its face — a 4-bar pre-chorus
with 4 lines cannot carry 10 syllables a line at 95 BPM, so the brief says "at most 8 here".

The band is delivery-dependent and lives in `delivery-rates.json`: a caption containing "Male Rap
Vocals" gets 8–16 syllables per line and a 6.5/s ceiling, where a ballad gets 5–9 and 2.6. Intros,
outros, interludes and solos are instrumental by construction, and writing words into one is an
**error** — which is exactly what running the real fixture against `pop_standard` produced:

```
ERROR: [Outro]: 36 syllables written into an instrumental section (10.1s); there is no vocal there
```

The timeline also reports **density**, which catches what scaling does: filling an exact duration
stretches every section, so `pop_standard` stretched to three minutes at 95 BPM comes out with five
sparse sections at 1.58 syllables/s against a comfortable 2.3. Hitting a duration and keeping a
density are different goals.

Adding a bin is a four-part change — options, a control, a render position, and a checker —
because a bin is simultaneously a UI element, a prompt field and a compliance obligation.
`maps_to` is the field that keeps the three in step, and it is orthogonal to `emits_tag`, so a
bin like `tempo` can create a requirement without contributing a tag.

## Radio stations

Picking tags one at a time is the wrong shape for "just play me something". **39 radio stations**
ship as data — [`vocabulary/radio-stations.json`](vocabulary/radio-stations.json) — across hip-hop,
rock and metal, pop, electronic, soul and funk, folk and country, Latin and Afro, and jazz and
cinematic.

A station is a **range, not a preset**. It fixes only its identity — genre, scenes, era, tempo band —
and declares a **pool** for every bin that makes a sound: the instruments, production, groove,
delivery and moods that are in character, and how many of them one song carries. Each song draws its
own coherent subset, so consecutive songs differ in their kit, their synths, their mix and their key
and still sound like the station. The draw is a pure function of the station, the song's position and
the seed, and it is conflict-aware: an option that excludes something already chosen is never taken.
The song's **subject rotates by position**, not by draw — a station carries seven, and a random draw
repeats one within any eight songs, so a station plays every subject it has before it plays one
again. The **way that subject is told** rotates on a slower cycle of its own, from a pool shared by
every station, so a subject that does come back comes back told a different way. A third shared pool,
the **detail** — the place, the object or the form a song is actually made of — rotates one per song,
so a subject and a telling that do meet again do not meet as the same song; with seven subjects,
twelve tellings and nineteen details, the three line up again only after 1,596 songs.

```bash
python3 vocabulary/radio_stations.py            # every station is playable: bins, options, counts, tempos, budget
python3 vocabulary/radio_stations.py --list     # the stations and how many shapes each can draw
python3 vocabulary/radio_stations.py --plan=neon-drive --index=3 --seed=42
```

The UI's **Radio** tab streams a station: it keeps three songs ready or rendering ahead, starts
playing as soon as the first is done, and skips to the next ready one. Each song is a full 8-step
render into `ComfyUI/output/radio/<station>/`, so a station's songs are organised by station and easy
to find; a take's file name carries the station and, for an instrumental, says so, with ComfyUI's own
counter supplying the number. A lyric is written per song from the station's subject by the same
generator the Lyrics tab uses; with no model reachable, or with the panel's **instrumental** box
ticked, the take is planned and captioned as an instrumental instead. The current song can be
downloaded, and the songs played on a station are listed there while the browser remembers them.

**Pressing play plays.** A station that has songs already starts on them and renders new ones behind,
so a station you have used before never makes you wait for a replacement first. It finds them in two
places — the takes this browser saved, and the ones the renderer still remembers, including songs it
rendered but that were never played — and merges them by file, so nothing is queued twice.

**A take carries its own record.** ComfyUI writes the graph it executed into the MP3's tags, so a
recovered song shows the caption and the lyrics it actually had, read from the file rather than from
the renderer's memory — which a restart erases. Because those words are text, two takes that sing the
same words are found by comparison alone, and each is labelled as a rendition of the same song
(`rendition 3 of 11`) while keeping its own place in the queue. An instrumental has no words to
compare, so it is never mistaken for a rendition of another.

## The core package

Every check lives once, in `musicmaster/`, as a **text tier**: JSON in, JSON out, standard library
only. That purity is not tidiness — it is what lets the same code run under the CLI and, in the
browser, under a WebAssembly CPython, so a static SPA reuses the one implementation instead of a
rewrite that drifts from it.

```
musicmaster/
  render.py  lyrics.py  timeline.py  templates.py  vocabulary.py  radio.py   # text tier, stdlib only
```

The scripts in `vocabulary/` are thin wrappers that delegate to it, so existing command lines and
`songs/*/build_and_submit.py` keep working unchanged.

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_text_tier.py` covers both halves: the standard-library guard, and unit tests for the
values the tier computes — the tag budget, the bar-to-seconds arithmetic, the syllable budget, and
each song satisfying its own template. Expectations are written inline and derived from the
definitions wherever they can be, so the suite fails when the arithmetic or the mapping is wrong,
not when a message is reworded or the vocabulary grows.

## The UI

`web/` is a static SPA (Svelte 5 + Vite) that runs the text tier **in the browser** under Pyodide, so
the form, the caption, the time budget and the lyric findings all come from the same Python the CLI
uses. No server is in the loop, and there is no second implementation to drift from the first.

```bash
cd web && npm install
npx vite                 # http://127.0.0.1:5173/
npx vite build           # static bundle in web/dist, repository and runtime copied in
node scripts/smoke.mjs   # checks the browser glue and the lens against the CLI, without a browser
node scripts/smoke.mjs --generate --theme="…"   # one real draft, scored by the checker
```

`.github/workflows/pages.yml` builds that bundle and deploys it to GitHub Pages on every push to
`master`, so the page can be opened from the internet without a local server. The bundle is
self-contained — the repository and the Pyodide runtime are copied into it — but a render still needs
a ComfyUI the **browser** can reach: over HTTPS the page cannot post to a loopback ComfyUI, so point
the Render tab's target at a non-loopback address and start ComfyUI with `--enable-cors-header` for
the deployed origin. The render-target note below has the rest.

The page reads the vocabulary, the text tier and the songs out of the repository itself, so the form
cannot disagree with the renderer about what a bin is: adding an option to `tag-bins.json` adds a
control, and nothing in `web/` changes.

What it does today: opens `rap-metal-groove`, generates the whole bin form from the vocabulary,
renders the caption live with its tag budget, dropped tags, negatives and coherence notes, draws the
timeline with its syllable budget, and gives the lyric a generator and an editor. A fourth tab,
**Radio**, streams one of 39 stations continuously — see [Radio stations](#radio-stations).

**The generator has a deterministic half and a model half.** The deterministic half is the scaffold
and the writing brief, both from the text tier: no network, and correct by construction — a fresh
scaffold passes the checker immediately, with every section, performance tag and transition already
in place. The model half sends that same brief, plus the caption and a one-line theme, to a model
through ollama. Cloud models are listed first because the local ones compete for the GPU ComfyUI
renders on, and the panel states which you have chosen and what leaves the machine. **A write sends
sampling, not just a prompt**: every call carries a temperature and a seed — the temperature is yours
to set in the panel, the seed is the song's — so pressing Generate again asks a new question instead
of the same one, and a model that would otherwise answer a prompt identically writes a different
song.

**The editor is a text file with a grammar lens**, not a structured form, because a lyric that cannot
round-trip is a trap. The lens reads the same `section-tags.json` the checker reads, so it cannot
invent a rule: tag autocomplete that offers a modifier only after a section header, findings shown on
the line they are about, section headers and caesura breaks marked, and a per-section inspector that
follows the caret. One rule is a gate and the rest is ordering — after a blank line a tag may be
either the transition leaving a section or the header of the next, so both are offered rather than
guessed between.

**The render path runs in the page too.** `musicmaster.prompt` builds the canonical `prompt.json`
and the ComfyUI graph from the same inputs the CLI uses, so the Render tab shows the prompt hash,
downloads the exact bytes that hash is taken over, and queues the graph itself — with the service's
own rejection text shown verbatim rather than reduced to "failed". The smoke test asserts that the
browser's `prompt.json` and `workflow.json` are byte-identical to the CLI's, so the prompt hash in
the page is the prompt hash in the repository.

**A render target is a preset, and the protocol follows from it, because there are two.** A
self-hosted ComfyUI speaks `POST /prompt` and `/history/{id}`; [Comfy API
v2](https://docs.comfy.org/api-reference/v2/overview) speaks `POST /api/v2/jobs` with a bearer token
and returns a durable, pollable job. The presets are this project's service on `:8288`, ComfyUI's own
default on `:8188`, a self-hosted [`comfy-api-proxy`](https://github.com/Comfy-Org/comfy-api-proxy)
on `:8189`, [Comfy Cloud](https://cloud.comfy.org) on v2, or any address you supply. The graph is API
format, which is the one v2 accepts — it rejects the `nodes`/`links` UI export. The dev server proxies
`:8288` and `:8188`, so a local render needs nothing — and it has to, because ComfyUI refuses a POST
to a loopback address whose `Origin` does not match its `Host`, its guard against a random site
queueing renders through `127.0.0.1`. A page served from elsewhere therefore **cannot** post to a
loopback ComfyUI however it is configured: it has to reach ComfyUI at a non-loopback address, with
`--enable-cors-header` set for the page. Comfy Cloud needs a paid subscription, and an API key typed
there is held in the tab's session storage rather than saved, because a page cannot keep a secret.

A render picks a **fresh seed** by default, so each one is a new take. The same seed with the same
inputs *is* the same take — of the eighteen takes on disk, the only two whose graphs matched came out
byte-identical, and every other pair differed because something in the inputs had. The top bar
therefore carries **both actions, always**: `render` generates a seed, and `re-render <seed>` sends the
one on screen. Neither consults a mode, because a button whose meaning depends on a checkbox in a
panel you might not have open is worse than no button. The Render panel keeps the checkbox for its own
button, where the seed field is next to it and nothing is hidden. Holding the seed is what keeps the
arrangement put while the caption varies, which is the only way to hear what a caption change actually
did rather than hearing it mixed with whatever a different seed would have produced anyway. A
**preview and an A/B never take a new seed**: they hold the seed of the last take, so a preview is
the arrangement of audio that exists rather than a fresh one, and a seed a render generated — or one
typed into the field — reaches a preview only once a take has been rendered with it. The panel shows
the seed it is holding. Each caption is previewed as its own graph and the rendered clip is
remembered, so an A/B sends the tag and reuses the current caption rather than rendering it again; a
row says `cached` when it came back rather than being rendered. An A/B can also be heard **as one
track**: the panel downmixes both takes to mono and hard-pans them, the current caption on the left
and the variant on the right, so the balance control picks a side and the centre is the sum — two
players started together are not a comparison, because they drift and the ear loses which is which.
The mix is built in the page from the two clips, so it costs no render. A **new song** is a blank
draft you name, that you export and commit — the same loop as everything else, since a page cannot
write a song directory.

**State is browser-local by design.** The working state — selections, lyric, template, tempo, seed, brief — is autosaved to `localStorage` so a reload does not throw an edit away, and any number of **named drafts** can be saved, loaded and deleted from the top bar, so several directions can exist at once. A `differs from repo` marker with one-click revert appears whenever the working state no longer matches the files in `songs/<id>/`. The marker is there because the distinction is real: the song directory is the record, and a page cannot write to it.

**A deployed page updates itself.** A static host has no server to push a change into a tab that is already open, and it serves even a fresh page from its cache for minutes, so the page has to notice for itself. The bundle carries its own build id, compiled in at build time, and the build also publishes a `version.json` naming the deployed commit; the page re-reads that while it is open, and anything other than its own id makes it reload through a cache-busting URL. Compiling the id in is the part that matters: asking the host which build is deployed tells a page served from cache that it is already current, which is the one page that most needs to reload. Repository fetches carry the same id, so a reload cannot pair new code with the previous build's cached data. Nothing holds it back either — a station or a render is always "busy", so waiting for idle would have meant never.

**The model server is a setting, not an assumption.** It defaults to this machine's daemon. A page
served from somewhere else — GitHub Pages, say — reaches it over CORS, which ollama refuses by
default, because its allow-list is localhost and a few app schemes and the deployed origin is not on
it. Point the address somewhere you control, or let ollama allow the page:

```
OLLAMA_ORIGINS=https://you.github.io ollama serve
```

Chrome may additionally ask permission for a public page to reach a local address. When nothing
answers, the panel says so and prints that command with the real origin filled in, rather than
surfacing a bare "Failed to fetch".

The **Check** tab verifies the caption and the lyrics before a render is spent on them. The caption
is compared, in code, against what was selected — every tag that should be sent, nothing that was
excluded, no contradictory pair, and nothing dropped by the tag budget. The lyrics are judged one
requirement at a time, including the cross-artifact consistency rules the lyric checker can pose but
not answer, which used to sit in the Lyrics tab as a deferred list. The report leads with a plain
sentence and, for each thing that did not pass, says what to change and where — written in code from
the measured failure, never by the model. When the fixes need a rewrite, the page offers to make
them: it hands the generator the instructions the failed checks localised, checks the text the
generator returned, and says whether the rewrite resolved anything. With no key and no service the
caption is still checked and every lyric requirement is reported `unverified` with the reason, which
is a report rather than a failure. What is not checkable yet is said so rather than shown as an empty
pane: a rendered track's genre, instrumentation or era need a measurement or an independent caption,
and neither exists here. The page also needs to be served over HTTP — WASM and ES modules will not
load from a `file://` URL.

## Checking the brief

The generator is the product; checking is what the design aims to add on top of it, and it is why the
text tier is kept apart from the audio.

**The check that runs before a render** is specified in [`docs/design/pre-render-check.md`](docs/design/pre-render-check.md).
It answers one decision: given the caption that will be sent and the lyrics that were generated,
does each requirement the brief implies hold well enough to spend a render on it? The caption is
decided in code, because it is the tag string the renderer produced and "does it carry the distorted
guitar" is a containment test over that string. The lyrics are decided by the oracle, one narrow
question per requirement, with the thing asked for carried in the state so the question compares the
words to the brief rather than to nothing. Properties of the rendered audio wait for a captioner and
a measurement pass, and are reported as such rather than guessed at.

Requirements split into mechanical ones that code computes exactly (duration, BPM, key,
syllables, rhyme, banned words, loudness) and semantic ones that are irreducibly judgments
(theme, mood, genre, hook, cliché, imitation, explicitness). The mechanical half runs today
and never touches a model.

The semantic half is where the ambition sits, and its seam is built: the question set, the
uncertainty band, the evidence gate and the report are real and packaged in `musicmaster/oracle.py`,
and the obligations a draft implies are derived from the vocabulary's own `maps_to` in
`musicmaster/spec.py` rather than from a second hand-kept table. What it needs is a **Jev-like**
model: one that answers typed questions over a text state with calibrated probabilities rather than
prose, so code can consume the answer directly. The "-like" is load-bearing. Jev is the quality
reference and the easiest to adopt, but it is a hosted API, so it needs a key and it sends the
lyrics — the user's private intent — off the machine. That is a property of the service, not of the
interface: a small open model read the same way, straight from its logits in one forward pass, gives
the same typed answers with no egress at all, and the page's no-server shape points at hosting one in
the browser beside the Pyodide text tier.

**Jev is the first provider wired up, and it runs on a key the user supplies.** The wire format is
`musicmaster/jev.py` — one implementation, two transports: urllib for the CLI and `fetch` for the
page, both handing the seam the same parsed answers, so a difference between them is the transport
and never the battery. Nothing is asked for without a key, and with no key every semantic requirement
is reported `unverified` rather than guessed at. Two things are worth knowing before typing one:

- **A page cannot call the API directly.** Its preflight advertises `Authorization` and credentials
  but never returns `access-control-allow-origin`, for every origin tried, including TypeSafe's own,
  so a browser refuses the response before the key is ever used. That is why local development goes
  through the dev server instead: `vite.config.ts` relays `/jev`, adding `Authorization` from the
  same `TYPESAFE_API_KEY` the CLI reads, so in development the key never enters the browser and CORS
  never applies. A deployed page has no relay, so it calls the API itself and the panel reports a
  refusal as a refusal — a CORS block and a bad key are indistinguishable to a naive caller, and
  saying which one happened is the difference between a five-minute fix and an afternoon.
- **The key and the song leave the machine.** The request carries the projected fact sheet — the
  caption, the chords and the lyrics the questions name, and nothing else. In development the key
  stays in the dev server's environment; in a deployed page it is kept in session storage unless the
  user ticks "remember this device", and it is never written to a song directory, a report, or a log.

The battery runs without any of that, because the oracle is a seam rather than a dependency. A
**replay** oracle serves recorded answers, and `--print-request` prints the bytes that would be sent
before a key is involved, so the egress statement is something readable rather than something to be
trusted:

```bash
python3 vocabulary/check_compliance.py vocabulary/examples/compliance-indie-folk.json
python3 vocabulary/check_compliance.py vocabulary/examples/compliance-indie-folk.json --print-request
python3 vocabulary/check_compliance.py vocabulary/examples/compliance-indie-folk.json --json
TYPESAFE_API_KEY=... python3 vocabulary/check_compliance.py <fixture.json> --oracle=jev
```

Every verdict names the class of evidence behind it and the threshold that decided it, and the report
counts what was decided by measurement against what rests on a model's account of the artifact: a
report that says "twelve met, six of them on description" is a different document from "twelve met",
and only one of them is honest. The CLI reports by default and gates only under `--strict`.

The constraint every oracle shares is that it takes *text only*, so it cannot hear the
track: every audio artifact must first be reduced to a text surrogate (measured MIR facts,
chord transcription, vocal transcript, music caption). And because a requirement that can
only be checked after synthesis is expensive to fail, the generation path is chosen so most
requirements become observable as early as possible.

## Schemas

- [`schemas/prompt.schema.json`](schemas/prompt.schema.json) — the canonical generation
  request: style, metadata, form, lyric reference, negative conditioning, target identity and
  seed. The input artifact.
- [`schemas/song-bundle.schema.json`](schemas/song-bundle.schema.json) — the manifest: content
  hashes, per-stage seeds, dependency edges and environment, so any artifact can be re-derived
  and any output traced to its inputs.
- [`schemas/tag-vocabulary.schema.json`](schemas/tag-vocabulary.schema.json) — the shape of the
  bin vocabulary: bins, controls, priorities, render positions, options and cautions.
- [`schemas/radio-stations.schema.json`](schemas/radio-stations.schema.json) — the shape of the
  station document: a fixed identity, per-bin pools with draw counts, tempo bands, themes and keys.
- [`schemas/section-tags.schema.json`](schemas/section-tags.schema.json) — the lyric metatag
  vocabulary and its grammar, including the caption/lyric consistency rules.
- [`schemas/structure-templates.schema.json`](schemas/structure-templates.schema.json) — the shape
  of a song-structure template: sections, bars, lines, rhyme scheme, energy and hooks.
- [`schemas/rhyme-schemes.schema.json`](schemas/rhyme-schemes.schema.json) — the rhyme-pattern
  library and each scheme's strictness.
- [`schemas/delivery-rates.schema.json`](schemas/delivery-rates.schema.json) — the delivery
  profiles: syllables per line, and the rate ceilings the time budget is built from.
- [`schemas/requirement-spec.schema.json`](schemas/requirement-spec.schema.json) — the typed
  interpretation of a brief, where every requirement names its checker and its provenance.
- [`schemas/compliance-report.schema.json`](schemas/compliance-report.schema.json) — the
  per-requirement verdict with evidence; `unverified` is distinct from `met`.

The prompt, manifest, vocabulary, spec and report schemas are written. `composition.json` and
`lyrics.md` are described in the design but do not yet have schemas of their own — by intent,
since the prompt is the input to the generator and is being specified first.

## Spikes

- [`spikes/measurement_probe.py`](spikes/measurement_probe.py) — synthesises a known 92 BPM
  F# minor signal and measures it back with the libraries already installed, to check that
  the design's deterministic layer is real. Measured 92.29 BPM and an exact key. The run
  also documents two failure modes worth knowing: librosa needs a writable
  `NUMBA_CACHE_DIR`, and a naive beat tracker returned a confident `0.0 BPM`.

  ```bash
  NUMBA_CACHE_DIR=spikes/.numba \
    /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/measurement_probe.py
  ```

- [`spikes/pyodide_text_core/`](spikes/pyodide_text_core/README.md) — runs the text core under a
  WebAssembly CPython, to check that a static SPA can use the same implementation the CLI does
  instead of a rewrite that drifts. Seven CLI invocations came back **byte-identical** between native
  CPython 3.12.3 and Pyodide 3.14.2, and the full per-caret lyric check measured ~12 ms median / ~17 ms
  p95 — about twice native, and inside a frame. It also pins the invariant that makes it possible:
  the text tier imports nothing outside the standard library.

  ```bash
  cd spikes/pyodide_text_core && npm install
  node parity.mjs      # correctness, byte-for-byte
  node latency.mjs     # is the per-caret check inside a frame budget?
  ```

- [`spikes/browser_oracle/`](spikes/browser_oracle/README.md) — asks whether a small open model could
  answer the battery in the page itself, with no key and no server: one forward pass over the state,
  the declared option probabilities read straight off the logits, and the battery's own questions
  crossed with four states that vary one thing at a time. Three findings. The mechanism works and
  costs about half of generate-and-parse, but a per-option softmax is a silent, total failure — it
  sums to one by construction, so a two-way question reads `0.500` and a five-level question reads
  uniform for every input while still looking like a probability vector. A confident answer can be one
  the model never made: Qwen3-1.7B returned a noul of `1.000` with `0.000` of its probability mass on
  the options. And at browser-plausible sizes the models score below a constant baseline (6/16
  and 9/16 against 12/16 for answering the same thing every time), which is consistent with the 0.407
  the research document records for Qwen3-0.6B. The in-browser figure of 16 s a question is
  `onnxruntime-web` under WASM rather than a browser limit: SemIf runs the same readout through wllama
  on WebGPU at 0.70 s for 0.6B and 3.27 s for 4B, so the tier is a real option rather than a dead end,
  and the spike says which runtime a future attempt has to use.

  ```bash
  cd spikes/browser_oracle && npm install --cache ./.npm-cache
  node selftest.mjs                       # the readout arithmetic; needs no model
  node node_measure.mjs --models=onnx-community/Qwen3-0.6B-ONNX --dtype=q8
  PLAYWRIGHT_BROWSERS_PATH=./.pw-browsers node browser_measure.mjs --device=wasm
  ```

- [`spikes/take_similarity.py`](spikes/take_similarity.py) — reads the graph ComfyUI embeds in each
  rendered MP3, so the requested tempo, seed and caption come from the artifact itself rather than
  from a note about it, and measures the audio against them. It exists to test an ear's claim that
  the takes of one song are variations of a single underlying track. Three findings: the requested
  tempo **does** take effect (112 asked, 107.7–112.3 measured; 92 asked, 92.3 measured); the beat
  tracker's octave ambiguity is not rare, at 3 of 17 takes measuring exactly double; and onset-envelope
  agreement runs about 0.15–0.20 within a tempo against 0.04 across tempos, so the takes are
  distinguishable — but 14 of the 17 shared one seed, and a seed is what fixes a take's underlying
  structure, so the caption was varying the surface of a common arrangement.

  ```bash
  NUMBA_CACHE_DIR=spikes/.numba \
    /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/take_similarity.py
  ```

## Target model

**ACE-Step 1.5** (XL turbo) is the reference generator, driven through its ComfyUI graph. All
four of its weights are on disk and this machine has already produced output from it. It
accepts `bpm`, `duration`, `timesignature`, `keyscale`, `language` and `seed` as conditioning
parameters, which is what lets several mechanical requirements be *requested* rather than
only measured — but that conditioning is injected as a text prompt, not a hard constraint, so
every conditioned requirement is still verified afterwards.

The composer sits behind a `MusicGenerator` adapter whose capabilities are declared, and a
model swap that would weaken any requirement's enforcement mode is a hard error rather than a
silent downgrade. See `docs/design/compliance-architecture.md` §5.8.

## Rules for the semantic checker

The oracle is a seam, not a dependency. Hosted Jev, a local logit-readout model and a
recorded replay fixture all satisfy one method — `evaluate(state, questions)` — so egress,
cost and quality are configuration rather than architecture
([`docs/design/compliance-architecture.md`](docs/design/compliance-architecture.md) §9).
Hosted Jev is the quality reference and the only one of the three that needs a key; the
local path is the egress-safe one and is materially weaker, so it should expect more
`uncertain` verdicts. Whichever is wired up, these rules govern it. They are carried from
measurements in sibling projects, not from anything this repository has run:

1. **Never ask the model something code can compute exactly.** Counting, arithmetic, dates
   and numeric comparison are documented weak spots.
2. **Never consume a `choice` without a companion `noul`.** A choice settles *which* of
   your options; a noul settles *whether* — and can be low for all of them.
3. **Uncertainty is an outcome, not a pass.** A probability in the uncertain band is
   reported as uncertain and routed to repair or review.

Those sibling integrations, and the reusable clients they produced, are catalogued in
[`docs/research/jev-and-decision-models.md`](docs/research/jev-and-decision-models.md) §3.
