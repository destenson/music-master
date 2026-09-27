"""Build a per-genre tag atlas: the vocabulary rendered on a bed for each genre preset.

One shared bed made every genre tag a fusion with rock. A preset per genre fixes that: each genre
gets a bed that is a plain, representative example of it, and the vocabulary is rendered as
variations on that bed. The bin under test is always dropped from its own bed, so the tag is the
only instruction on that axis.

Rendering goes through MyToolbox_AceStepBatchTextEncode, which runs the whole batch's LM prompts in
one pass -- the LM is about 1.8s of a 2.6s eight-second render and is the only stage that batches,
because ComfyUI's ACE-Step cannot sample a latent batch. The node emits a conditioning and a latent
per caption, so one KSampler node renders the batch one caption at a time (about 1.8x overall).

Every batch leads with its bin's base caption. The base and its variations then share the batch's
numerics, so the per-band difference recorded against the base is the tag and not a difference
between two takes.

    python3 spikes/genre_atlas.py --preset=trap --limit=24   # one preset, for a listen
    python3 spikes/genre_atlas.py                            # every preset, resumable

Clips land in spikes/genre-atlas/, indexed in index.jsonl. Re-running skips what is already there.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

BASE_URL = "http://127.0.0.1:8288"
CLIENT = "music-master-genre-atlas"
NODE = "MyToolbox_AceStepBatchTextEncode"
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "genre-atlas"

SECONDS = 8.0
STEPS = 8
SEED = 12345
KEYSCALE = "A minor"
LYRICS = "Hold the line, we're moving through the night"
LM = {"cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}
DEPTH = 3     # batches submitted ahead of the download, to keep the GPU busy
# Measured on the 3090 with both models resident: 3.65s/clip at batch 1, 1.10 at batch 8, 1.05 at
# 12. Steps barely matter here (0.80-0.89s/clip for 2, 4 or 8), so denoising is not the cost -- the
# per-item sampler and decode is. The first row of every batch is the bin's base.
BATCH = 12

# Bins whose options are audible in an 8s clip. Genre is excluded because each bed already fixes
# one; lyric_theme, structure and hook do not change an 8s render in any way worth hearing.
EXCLUDED_BINS = {"genre", "lyric_theme", "structure", "hook"}

# Each preset is a plain example of the genre: a groove, kit, bass, harmony, vocal and production.
# A vocal is present on every preset that is not declared instrumental, because most of the
# vocabulary is vocal and a silent bed would make those bins inaudible.
PRESETS: dict[str, dict] = {
    "pop": {"genre": "Pop", "bpm": 118, "bed": {
        "groove": "Four-on-the-Floor", "drums": "Punchy Kick", "bass": "Synth Bass",
        "synth": "Lush Pads", "lead_vocal": "Female Vocals", "production": "Polished Production",
        "space": "Wide Stereo Field"}},
    "hip_hop": {"genre": "Hip-Hop", "bpm": 90, "bed": {
        "groove": "Boom Bap Swing", "drums": "Snappy Snare", "bass": "Fingerstyle Bass",
        "harmony": "Rhodes Piano", "lead_vocal": "Male Rap Vocals", "production": "Raw Production",
        "space": "Dry Mix"}},
    "trap": {"genre": "Trap", "bpm": 140, "bed": {
        "groove": "Trap Hi-Hats", "drums": "808 Kicks", "bass": "Heavy 808 Bass",
        "synth": "Glassy Keys", "lead_vocal": "Male Rap Vocals",
        "production": "Bass-Heavy Production", "space": "Dry Mix"}},
    "r_and_b": {"genre": "R&B", "bpm": 90, "bed": {
        "groove": "Groovy", "drums": "Live Drums", "bass": "Fingerstyle Bass",
        "harmony": "Rhodes Piano", "lead_vocal": "Female Vocals", "vocal_delivery": "Smooth Vocals",
        "production": "Polished Production", "space": "Intimate Space"}},
    "rock": {"genre": "Rock", "bpm": 120, "bed": {
        "groove": "Straight", "drums": "Live Drums", "bass": "Bass Guitar",
        "harmony": "Distorted Guitar", "lead_vocal": "Male Vocals",
        "production": "Live-Room Production", "space": "Room Reverb"}},
    "metal": {"genre": "Metal", "bpm": 150, "bed": {
        "groove": "Driving", "drums": "Live Drums", "bass": "Distorted Bass",
        "harmony": "Power Chords", "lead_vocal": "Male Vocals", "vocal_delivery": "Harsh Vocals",
        "production": "Wall of Sound", "space": "Tight Reverb"}},
    "indie_rock": {"genre": "Indie Rock", "bpm": 125, "bed": {
        "groove": "Straight", "drums": "Live Drums", "bass": "Picked Bass",
        "harmony": "Clean Electric Guitar", "lead_vocal": "Male Vocals",
        "production": "Raw Production", "space": "Room Reverb"}},
    "country": {"genre": "Country", "bpm": 100, "bed": {
        "groove": "Two-Step", "drums": "Live Drums", "bass": "Upright Bass",
        "harmony": "Acoustic Guitar", "lead_vocal": "Male Vocals",
        "production": "Live-Room Production", "space": "Dry Mix"}},
    "folk": {"genre": "Folk", "bpm": 95, "bed": {
        "groove": "Straight", "drums": "Hand Percussion", "bass": "Upright Bass",
        "harmony": "Fingerpicked Guitar", "lead_vocal": "Male Vocals",
        "production": "Minimal Production", "space": "Intimate Space"}},
    "jazz": {"genre": "Jazz", "bpm": 110, "bed": {
        "groove": "Swung", "drums": "Brushed Drums", "bass": "Upright Bass",
        "harmony": "Grand Piano", "lead_vocal": "Male Vocals", "vocal_delivery": "Melodic Vocals",
        "production": "Live-Room Production", "space": "Room Reverb"}},
    "soul": {"genre": "Soul", "bpm": 95, "bed": {
        "groove": "Groovy", "drums": "Live Drums", "bass": "Fingerstyle Bass",
        "harmony": "Hammond Organ", "lead_vocal": "Female Vocals",
        "vocal_delivery": "Soulful Vocals", "production": "Analog Warmth", "space": "Room Reverb"}},
    "reggae": {"genre": "Reggae", "bpm": 75, "bed": {
        "groove": "Offbeat", "drums": "Live Drums", "bass": "Deep Sub Bass",
        "harmony": "Clean Electric Guitar", "lead_vocal": "Male Vocals",
        "production": "Raw Production", "space": "Tape Delay"}},
    "electronic": {"genre": "Electronic", "bpm": 126, "bed": {
        "groove": "Four-on-the-Floor", "drums": "Drum Machine", "bass": "Synth Bass",
        "synth": "Analog Pads", "lead_vocal": "Female Vocals",
        "production": "Polished Production", "space": "Wide Stereo Field"}},
    "techno": {"genre": "Techno", "bpm": 132, "bed": {
        "groove": "Four-on-the-Floor", "drums": "TR-909 Drums", "bass": "Synth Bass",
        "synth": "Resonant Filters", "lead_vocal": "Female Vocals",
        "production": "Heavy Compression", "space": "Wide Stereo Field"}},
    "drum_and_bass": {"genre": "Drum and Bass", "bpm": 174, "bed": {
        "groove": "Breakbeat", "drums": "Live Drums", "bass": "Reese Bass",
        "synth": "Detuned Synths", "lead_vocal": "Female Vocals",
        "production": "Heavy Compression", "space": "Wide Stereo Field"}},
    "dubstep": {"genre": "Dubstep", "bpm": 140, "bed": {
        "groove": "Laid-Back", "drums": "Sub Kick", "bass": "Wobble Bass",
        "synth": "Buzzy Synths", "lead_vocal": "Male Vocals",
        "production": "Bass-Heavy Production", "space": "Wide Reverb"}},
    "synth_pop": {"genre": "Synth-Pop", "bpm": 118, "bed": {
        "groove": "Pulsing", "drums": "LinnDrum", "bass": "Synth Bass", "synth": "Supersaw",
        "lead_vocal": "Female Vocals", "production": "Polished Production",
        "space": "Wide Stereo Field"}},
    "lo_fi_hip_hop": {"genre": "Lo-Fi Hip-Hop", "bpm": 80, "bed": {
        "groove": "Boom Bap Swing", "drums": "Lo-Fi Drums", "bass": "Fingerstyle Bass",
        "harmony": "Rhodes Piano", "lead_vocal": "Male Rap Vocals",
        "production": "Lo-Fi Production", "space": "Tape Delay"}},
    "reggaeton": {"genre": "Reggaeton", "bpm": 92, "bed": {
        "groove": "Dem Bow", "drums": "Punchy Kick", "bass": "Deep Sub Bass",
        "synth": "Plucked Synths", "lead_vocal": "Male Vocals",
        "production": "Club-Ready Production", "space": "Dry Mix"}},
    "ambient": {"genre": "Ambient", "bpm": 70, "instrumental": True, "bed": {
        "synth": "Ambient Pads", "bass": "Deep Sub Bass",
        "production": "Atmospheric Production", "space": "Cavernous Space"}},
}

VOCAL_BINS = {"lead_vocal", "vocal_delivery", "backing_vocal", "vocal_fx"}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def vocabulary() -> tuple[list[str], dict[str, dict]]:
    vocab = load(ROOT / "vocabulary" / "tag-bins.json")
    bins = {b["id"]: b for b in vocab["bins"]}
    order = [b for b in vocab["render_order"]
             if b not in EXCLUDED_BINS and bins.get(b, {}).get("emits_tag", True) and bins.get(b, {}).get("options")]
    return order, bins


def resolve(bins: dict, slug: str, preset: dict) -> dict[str, list[dict]]:
    bed: dict[str, list[dict]] = {}
    # The preset's genre is part of the bed, not a variation axis: it is what makes the bed an
    # example of that genre rather than a genreless instrument stack.
    entries = dict(preset["bed"])
    if preset.get("genre"):
        entries = {"genre": preset["genre"], **entries}
    for bin_id, labels in entries.items():
        labels = labels if isinstance(labels, list) else [labels]
        for label in labels:
            option = next((o for o in (bins[bin_id].get("options") or []) if o["label"] == label), None)
            if option is None:
                raise SystemExit(f"preset {slug!r}: no option {label!r} in bin {bin_id!r}")
            bed.setdefault(bin_id, []).append(option)
    return bed


def caption(bed: dict[str, list[dict]], bin_id: str, test: dict | None) -> str:
    out: list[str] = []
    for other_bin, options in bed.items():
        if other_bin == bin_id:
            continue
        for option in options:
            if test is not None and (option["id"] in (test.get("excludes") or [])
                                     or test["id"] in (option.get("excludes") or [])):
                continue
            out.append(option["label"])
    return ", ".join([*out, test["label"]] if test else out)


def batch_graph(captions: list[str], prefix: str, bpm: int) -> dict:
    workflow = load(ROOT / "songs/rap-metal-groove/workflow.json")
    workflow["11"] = {"class_type": NODE, "inputs": {
        "clip": ["2", 0], "captions": "\n".join(captions), "lyrics": LYRICS, "bpm": bpm,
        "duration": SECONDS, "timesignature": "4", "language": "en", "keyscale": KEYSCALE,
        "seed": SEED, **LM,
    }}
    # One conditioning carrying every caption, so the stock latent node takes the matching batch
    # size and the single KSampler renders the whole batch in one pass.
    workflow["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["11", 0]}}
    workflow["6"]["inputs"].update({"seconds": SECONDS, "batch_size": len(captions)})
    workflow["8"]["inputs"].update({"steps": STEPS, "seed": SEED, "positive": ["11", 0],
                                    "negative": ["5", 0], "latent_image": ["6", 0]})
    # flac, not mp3: encoding twelve MP3s cost 3.5s a batch against 0.2s for flac, and the audio is
    # only ever listened to or measured. The prefix is deliberately outside output/audio/, so this
    # never lands beside the song renders.
    workflow["10"] = {"class_type": "SaveAudio", "inputs": {"audio": ["9", 0],
                                                            "filename_prefix": prefix}}
    return workflow


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(f"{BASE_URL}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=60) as response:
        return json.loads(response.read())


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def output_files(entry: dict) -> list[dict]:
    files: list[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for value in node.values():
            if isinstance(value, list):
                files += [i for i in value if isinstance(i, dict) and "filename" in i]
    return files


class Queue:
    """Submit a few batches ahead so the GPU never idles between HTTP round trips."""

    def __init__(self, index_path: Path, done: set[str]) -> None:
        self.index_path = index_path
        self.done = done
        self.inflight: list[dict] = []
        self.work: deque[dict] = deque()
        self.rendered = 0
        self.failed = 0
        self.started = time.time()

    def add(self, batch: dict) -> None:
        self.work.append(batch)

    def _submit(self, batch: dict) -> None:
        job = post("/prompt", {"prompt": batch_graph(batch["captions"], batch["prefix"], batch["bpm"]),
                               "client_id": CLIENT})["prompt_id"]
        self.inflight.append({**batch, "job": job, "at": time.time()})

    def _record(self, entry: dict) -> None:
        with self.index_path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.done.add(entry["key"])

    def drain(self) -> None:
        while self.work or self.inflight:
            while self.work and len(self.inflight) < DEPTH:
                self._submit(self.work.popleft())
            time.sleep(0.25)
            for batch in list(self.inflight):
                entry = get_json(f"/history/{batch['job']}").get(batch["job"], {})
                status = (entry.get("status") or {}).get("status_str")
                if status not in ("success", "error"):
                    if time.time() - batch["at"] > 900:
                        self.inflight.remove(batch)
                        self.failed += len(batch["clips"])
                    continue
                self.inflight.remove(batch)
                if status != "success":
                    self.failed += len(batch["clips"])
                    print(f"  batch failed: {batch['prefix']}", flush=True)
                    continue
                files = output_files(entry)
                if len(files) != len(batch["captions"]):
                    self.failed += len(batch["clips"])
                    print(f"  batch returned {len(files)} files for {len(batch['captions'])} "
                          f"captions: {batch['prefix']}", flush=True)
                    continue
                base_target = OUT / batch["base_file"]
                base_target.parent.mkdir(parents=True, exist_ok=True)
                base_target.write_bytes(self._fetch(files[0]))
                self._record({"key": batch["base_key"], "slug": batch["slug"], "bin": batch["bin"],
                              "option": "_base", "label": "base", "caption": batch["captions"][0],
                              "file": batch["base_file"], "status": "success",
                              "sha256": hashlib.sha256(base_target.read_bytes()).hexdigest()})
                for index, clip in enumerate(batch["clips"], start=1):
                    target = OUT / clip["file"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(self._fetch(files[index]))
                    self._record({**clip, "status": "success",
                                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
                self.rendered += len(batch["clips"])
                rate = self.rendered / max(time.time() - self.started, 1e-9)
                left = sum(len(b["clips"]) for b in self.work) + sum(len(b["clips"]) for b in self.inflight)
                if self.rendered % 25 < len(batch["clips"]):
                    print(f"  {self.rendered} clips, {self.failed} failed, {left} queued, "
                          f"{rate:.2f} clips/s", flush=True)

    def _fetch(self, item: dict) -> bytes:
        query = urllib.parse.urlencode({"filename": item["filename"],
                                        "subfolder": item.get("subfolder", ""),
                                        "type": item.get("type", "output")})
        return get_bytes(f"{BASE_URL}/view?{query}")


def main(argv: list[str]) -> int:
    only: set[str] = set()
    limit: int | None = None
    for arg in argv[1:]:
        if arg.startswith("--preset="):
            only.add(arg.split("=", 1)[1])
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])

    order, bins = vocabulary()
    slugs = [s for s in PRESETS if not only or s in only]
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.jsonl"
    done: set[str] = set()
    if index_path.exists():
        for line in index_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["key"])
    queue = Queue(index_path, done)
    (OUT / "settings.json").write_text(json.dumps({
        "node": NODE, "seconds": SECONDS, "steps": STEPS, "seed": SEED, "keyscale": KEYSCALE,
        "lyrics": LYRICS, "lm": LM, "batch": BATCH, "presets": {s: PRESETS[s].get("bpm") for s in slugs},
    }, indent=2) + "\n")

    remaining = limit
    for slug in slugs:
        preset = PRESETS[slug]
        bed = resolve(bins, slug, preset)
        bpm = int(preset.get("bpm", 120))
        vocal = preset.get("instrumental", False)
        variation_bins = [b for b in order if not (vocal and b in VOCAL_BINS)]

        for bin_id in variation_bins:
            base_caption = caption(bed, bin_id, None)
            base_key = f"{slug}/{bin_id}/_base"
            base_file = f"{slug}/base/{bin_id}.flac"
            pending = []
            for option in (bins[bin_id].get("options") or []):
                key = f"{slug}/{bin_id}/{option['id']}"
                if key in done:
                    continue
                if remaining is not None and remaining <= 0:
                    break
                pending.append({"key": key, "slug": slug, "bin": bin_id, "option": option["id"],
                                "label": option["label"], "caption": caption(bed, bin_id, option),
                                "file": f"{slug}/audio/{bin_id}__{option['id']}.flac"})
                if remaining is not None:
                    remaining -= 1
            for start in range(0, len(pending), BATCH - 1):
                chunk = pending[start:start + BATCH - 1]
                captions = [base_caption, *[c["caption"] for c in chunk]]
                queue.add({"slug": slug, "bin": bin_id, "bpm": bpm, "captions": captions,
                           "clips": chunk, "base_key": base_key, "base_file": base_file,
                           "prefix": f"mm-atlas/{slug}-{bin_id}-{start//(BATCH-1):03d}"})
            if remaining is not None and remaining <= 0:
                break
        if remaining is not None and remaining <= 0:
            break

    print(f"{len(slugs)} preset(s): {len(queue.work)} batches, {len(done)} already done", flush=True)
    queue.drain()
    print(f"finished {queue.rendered} clips, failed {queue.failed}", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
