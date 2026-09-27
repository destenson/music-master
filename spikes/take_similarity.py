"""Are the takes variations of one song, or different songs?

An ear says the eighteen takes of `rap-metal-groove` share an almost identical background beat even
where the caption, the groove tags and the requested tempo were changed. That is a claim about how
much the caption actually controls, so it is worth measuring rather than agreeing with.

For each take it reads the graph ComfyUI embedded in the MP3 (so the *requested* bpm, seed and
caption come from the artifact itself, not from a guess) and measures the audio:

* tempo, against the tempo that was asked for;
* the onset envelope, correlated pairwise between takes — two takes that share a groove have
  correlated onsets, and two that do not, do not.

    NUMBA_CACHE_DIR=spikes/.numba \\
      /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/take_similarity.py

librosa needs a writable NUMBA_CACHE_DIR, as `measurement_probe.py` also found.
"""

from __future__ import annotations

import json
import pathlib
import sys

import librosa
import numpy as np

AUDIO = pathlib.Path("/home/dennis/src/comfyanonymous--ComfyUI/output/audio")
SECONDS = 40.0  # enough for a tempo estimate and a beat pattern; the whole take is not needed


def syncsafe(raw: bytes) -> int:
    value = 0
    for byte in raw:
        value = (value << 7) | (byte & 0x7F)
    return value


def embedded_graph(path: pathlib.Path) -> dict:
    """The graph ComfyUI wrote into the file's ID3 tags: what actually produced this audio."""
    data = path.read_bytes()
    body = data[10 : 10 + syncsafe(data[6:10])]
    position = 0
    while position + 10 <= len(body):
        frame_id = body[position : position + 4].decode("latin-1")
        if not frame_id.strip("\x00"):
            break
        size = syncsafe(body[position + 4 : position + 8])
        if frame_id == "TXXX":
            payload = body[position + 10 : position + 10 + size]
            text = payload[1:].decode("utf-16" if payload[0] in (1, 2) else "utf-8", "replace")
            description, _, value = text.partition("\x00")
            if description == "prompt":
                return json.JSONDecoder().raw_decode(value)[0]
        position += 10 + size
    return {}


def measure(path: pathlib.Path) -> dict:
    graph = embedded_graph(path)
    node = graph.get("4", {}).get("inputs", {})
    y, sr = librosa.load(path, sr=22050, mono=True, duration=SECONDS)
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    return {
        "name": path.name.replace("rap-metal-groove_", "").replace(".mp3", ""),
        "asked_bpm": node.get("bpm"),
        "seed": graph.get("8", {}).get("inputs", {}).get("seed"),
        "caption": str(node.get("tags", ""))[:40],
        "measured_bpm": round(tempo, 1),
        "onsets_per_s": round(float(len(librosa.onset.onset_detect(onset_envelope=onset, sr=sr)) / SECONDS), 2),
        "centroid": round(float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))), 0),
        "onset": onset,
    }


def main() -> int:
    files = sorted(AUDIO.glob("rap-metal-groove*.mp3"))
    if not files:
        print(f"no takes under {AUDIO}")
        return 1
    print(f"measuring {len(files)} take(s), first {SECONDS:.0f}s each\n")

    takes = [measure(path) for path in files]

    print(f"{'take':<7}{'asked':>7}{'measured':>10}{'seed':>7}{'onsets/s':>10}{'centroid':>10}  caption")
    for take in takes:
        print(
            f"{take['name']:<7}{take['asked_bpm']:>7}{take['measured_bpm']:>10}{take['seed']:>7}"
            f"{take['onsets_per_s']:>10}{take['centroid']:>10.0f}  {take['caption']}"
        )

    # Does the beat line up? Two takes sharing a groove have correlated onset envelopes once a small
    # offset is allowed for; two that do not, do not.
    def agreement(a: dict, b: dict) -> float:
        x, y = a["onset"], b["onset"]
        n = min(len(x), len(y))
        x, y = x[:n] - x[:n].mean(), y[:n] - y[:n].mean()
        best = float("nan")
        for lag in range(-11, 12):
            # Sliced explicitly rather than with a negative start, which would count from the end.
            left, right = (x[lag:], y[: n - lag]) if lag >= 0 else (x[: n + lag], y[-lag:])
            if len(left) < 50 or left.std() == 0 or right.std() == 0:
                continue
            value = float(np.corrcoef(left, right)[0, 1])
            best = value if np.isnan(best) else max(best, value)
        return best

    groups: dict[object, list[dict]] = {}
    for take in takes:
        groups.setdefault(take["asked_bpm"], []).append(take)

    print("\nonset-envelope agreement (1.0 = the same beat, 0 = unrelated):")
    for asked, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        values = [agreement(a, b) for i, a in enumerate(members) for b in members[i + 1 :]]
        print(
            f"  asked {asked} BPM, {len(members)} takes: mean {np.mean(values):.2f}, "
            f"min {np.min(values):.2f}, max {np.max(values):.2f}"
        )

    across = [agreement(a, b) for a in takes if a["asked_bpm"] == 92 for b in takes if b["asked_bpm"] == 112]
    if across:
        print(f"  across 92 vs 112 BPM:        mean {np.mean(across):.2f}, min {np.min(across):.2f}, max {np.max(across):.2f}")

    tempos = sorted({t["measured_bpm"] for t in takes})
    print(f"\nmeasured tempos seen: {tempos}")
    for asked in sorted(groups, key=str):
        values = [t["measured_bpm"] for t in groups[asked]]
        print(f"  asked {asked}: measured {min(values)}–{max(values)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
