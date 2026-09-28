# Radio stations

A radio station plays songs that sound like each other and are not the same song. That is the whole
requirement, and it decides the design: a station cannot be a preset, because a preset renders one
arrangement forever. A station is a **range** — a genre, its scenes and era, a tempo band, and for
every bin that makes a sound, a pool of options that are all in character — and each song draws its
own subset from those pools.

```
[Station] --> plan --> write --> render --> play
              ^          ^         ^          |
              |          |         |          |
        master.radio   ollama   ComfyUI   the panel
```

## What a station states

Two kinds of statement, and nothing else:

- **`fixed`** — the identity. A trap station is trap, it is late-night, it is of its era. These bins
  are the same on every song.
- **`pools`** — the range. Each names a bin, the options that are in character, and how many of them
  one song carries. A pool may sit alongside `fixed` options for the same bin, so a station can
  always have live drums and *sometimes* a tambourine as well.

The planner owns `tempo`, `structure` and `key_mode`; a station that fixed one of those would have it
silently overridden, so the validator refuses the document rather than letting the two disagree.

Consecutive songs from one station therefore differ in their groove, kit, bass, harmony, synths,
vocal, delivery, backing, production, space, timbre, mood and key, and share the genre, the scenes,
the era and the tempo band. `vocabulary/radio-stations.json` holds **39 stations** across eight
families; a typical one has over a million distinct shapes before the seed is even drawn.

## The draw

`musicmaster.radio.plan_song(doc, station_id, index, seed=…)` is a pure function. It walks the
station's pools with a small reproducible generator seeded from `(station, position, seed)`, so a
take is derivable from those three values and the browser and the CLI cannot disagree about what a
station is. The renderer draws the seed, exactly as it does for a hand-built song; the position
names the song and rotates the subject a lyric is written about.

The subject is rotated rather than drawn, and the difference is the point. A station carries five
subjects, and a draw from five repeats one within any six songs by pigeonhole, so consecutive songs
regularly came out about the same thing even though the model wrote different words for each. The
position therefore walks the subjects in order — every subject is played before one returns — and a
second, slower rotation over a pool shared by every station changes **how the subject is told**
(`told as a list of things you kept`, `told from the other side of the same night`), so the second
telling of a subject is a different song rather than a paraphrase. With five subjects and twelve
ways to tell them, a subject and its telling only meet again after sixty songs.

Three rules keep a draw coherent:

- **Caps are respected.** `count` is clipped by the bin's `max_selections` and by whatever `fixed`
  already puts in that bin.
- **Conflicts are never taken.** An option is skipped if it excludes something already chosen, or if
  something chosen excludes it, so a pool that contains `no_drums` beside real kits still yields a
  playable song.
- **Variety is checked, not assumed.** `--list` reports each station's shape count, and the validator
  renders eight songs per station and refuses a station whose songs come out identical.

## One song, four stages

| Stage | Owner | What it produces |
| --- | --- | --- |
| plan | `musicmaster.radio` | selections, tempo, key, template, subject, song id |
| write | ollama (optional) | a lyric for that subject, or an instrumental take |
| render | ComfyUI | a full 8-step MP3 under the station's output directory |
| play | the panel | the audio element, skip, save |

A full render is slow, so the engine keeps `keep ahead` songs (3 by default) either ready or in
flight, and starts playback as soon as the **first** is ready rather than waiting for the whole
buffer. A station's finished songs are listed per station in browser storage, because the page
cannot list ComfyUI's output directory; the files themselves are the durable record.

The lyrics come from the same generator the Lyrics tab uses, with the station's subject as the theme,
the station's rotated angle as the way it is told, and the station's own brief as the contract. A
model is optional: with none chosen or reachable, the
song is re-planned as an **instrumental** and the caption stops describing a singer who is not
there. The panel's **instrumental** checkbox skips the model entirely. Because it is optional, the
lyric call is bounded rather than open-ended: it is capped at 150 s and runs one at a time — the
buffer fills several songs at once, and a cloud model answers a parallel burst slowly — and a call
that times out or fails yields an instrumental take rather than costing the song its place in the
queue. The panel shows how long each in-progress song has been in its stage.

## Starting on what the station already has

Pressing play should mean playing, not waiting two minutes for a render. So a station's existing
takes are found **before** anything new is queued, from two places:

- the page's own saved history, which is the durable record and survives a reload or an update; and
- the renderer's `/history`, which catches takes the page never recorded — one that was rendered but
  never played, or one rendered from somewhere else — and is a bonus rather than the record, since a
  restarted renderer remembers nothing.

The two are merged by file, so a take both know about is queued once, and a file whose name is not
this station's take naming is ignored. One slot is deliberately left for something new: the station
starts on what it has and renders its next song behind that, so it neither replays a whole repertoire
nor stops producing. A take's kind comes from a marker in its **file name** and its number from the
renderer's counter in the same name ([`takes.ts`](../../web/src/lib/takes.ts)), which is what orders
a station's takes; the caption and seed are read back from the graph the renderer kept.

ComfyUI's history has recorded that graph in two shapes a version apart — the bare API graph, and the
queue tuple `[number, prompt_id, graph, extra_data, outputs]` — so both are read rather than betting
on one. That parsing is pure and unit-tested in the smoke run rather than only exercised against a
live server.

## Output layout

A radio take is not a repository song, so it does not pretend to live in `songs/<id>/`. The graph
writes under the station, and the prompt's `composition_ref`, `lyrics.ref`, `graph_ref` and
`provenance.builder` point into `radio/<station>/<song_id>/` — the song's record, which the renderer
never writes. That split is one change to `prompt.build`, and the default for a song built by hand is
unchanged byte for byte.

```
ComfyUI/output/radio/<station>/
  <station>_00001.mp3               # a sung take
  <station>-instrumental_00001.mp3  # an instrumental take, self-classifying
```

The **file name** carries the station and, for an instrumental take, says so — and carries no number
of ours, because ComfyUI appends its own (`<prefix>_00001.mp3`, counting past what is already in the
folder) and a second counter beside it would number one file twice. The record's directory stays
keyed by the song, because an empty lyric is part of that song's record rather than a different song.

## Checking it

```bash
python3 vocabulary/radio_stations.py                 # schema + semantics for every station
python3 vocabulary/radio_stations.py --list          # the stations and how much they vary
python3 vocabulary/radio_stations.py --plan=neon-drive --index=3 --seed=42
```

The validator checks what a typo would otherwise hide: real bins, real options, counts inside each
bin's cap, a tempo inside the target's range, a template that has a `structure` option, a key that
exists, and then renders a sample of every station — normal and instrumental — to confirm each song
is coherent, inside the tag budget, and different from the song before it.

## What it does not do

- It does not let the model choose the arrangement. The pools are curated data; the draw only
  selects from what an author put in character for the station.
- It does not cancel a render already queued on ComfyUI. Stopping abandons the wait and the model
  call, but a job ComfyUI has begun will finish and its file stays on disk.
- It cannot play a **v2** target: those surfaces return outputs without a browser-reachable URL, so
  the radio needs a native ComfyUI.
