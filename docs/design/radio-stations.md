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

The lyrics come from the same generator the Lyrics tab uses, with the station's subject as the theme
and the station's own brief as the contract. A model is optional: with none chosen or reachable, the
song is re-planned as an **instrumental** and the caption stops describing a singer who is not
there. The panel's **instrumental** checkbox skips the model entirely.

## Output layout

A radio take is not a repository song, so it does not pretend to live in `songs/<id>/`. The graph
writes to `output/radio/<station>/<song_id>`, and the prompt's `composition_ref`, `lyrics.ref`,
`graph_ref` and `provenance.builder` point into `radio/<station>/<song_id>/` with it — one change to
`prompt.build`, and the default for a song built by hand is unchanged byte for byte.

```
ComfyUI/output/radio/<station>/
  <station>-000_00001_.mp3   # a SaveAudioMP3 take; ComfyUI numbers it so takes never collide
```

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
