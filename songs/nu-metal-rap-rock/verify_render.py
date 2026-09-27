"""Measure the render against what the prompt asked for.

This is the realization-fidelity half of the design: the prompt was verified as text before the
render, and this checks whether the audio actually complies. Everything measurable is measured in
code and compared in code -- no model is asked to judge a number.

Run with the ComfyUI venv, which has librosa, soundfile and pyloudnorm:

    NUMBA_CACHE_DIR=songs/nu-metal-rap-rock/.numba \
      /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python \
      songs/nu-metal-rap-rock/verify_render.py --audio songs/nu-metal-rap-rock/audio.mp3
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import librosa
import librosa.feature.rhythm  # lazy_loader does not expose this submodule as an attribute
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 22050

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 3.66, 2.29, 2.88, 5.19, 2.29, 3.66, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def measure(path: Path) -> dict:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    out: dict = {"duration_s": round(len(mono) / sr, 3), "channels": audio.shape[1], "sample_rate": sr}

    # Tempo: onset-envelope autocorrelation. Beat trackers legitimately report half or double the
    # pulse, so the comparison later is octave-tolerant.
    y = librosa.resample(mono, orig_sr=sr, target_sr=SR)
    hop = 512
    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop)
    tempo = librosa.feature.rhythm.tempo(
        onset_envelope=onset_env, sr=SR, hop_length=hop, start_bpm=120.0, std_bpm=4.0
    )
    out["tempo_bpm"] = round(float(np.atleast_1d(tempo)[0]), 2)

    # Key: chroma against Krumhansl-Schmuckler profiles, on a middle window to keep it quick.
    mid = y[len(y) // 3 : 2 * len(y) // 3]
    chroma = librosa.feature.chroma_cqt(y=mid, sr=SR).mean(axis=1)
    best = None
    for i, name in enumerate(NAMES):
        for mode, profile in (("major", MAJOR), ("minor", MINOR)):
            r = float(np.corrcoef(chroma, np.roll(profile, i))[0, 1])
            if best is None or r > best[0]:
                best = (r, f"{name} {mode}")
    out["key"], out["key_correlation"] = best[1], round(best[0], 3)

    meter = pyln.Meter(sr)
    out["integrated_lufs"] = round(float(meter.integrated_loudness(audio)), 2)
    out["true_peak_dbfs"] = round(float(20 * np.log10(max(np.max(np.abs(audio)), 1e-9))), 2)
    out["clipped_samples"] = int(np.sum(np.abs(audio) >= 0.999))
    out["spectral_centroid_hz"] = round(float(librosa.feature.spectral_centroid(y=y, sr=SR).mean()), 1)
    out["onset_count"] = int(len(librosa.onset.onset_detect(y=y, sr=SR)))
    return out


def verdicts(measured: dict, expected: dict) -> list[dict]:
    checks = []

    def add(req, want, got, ok, note=""):
        checks.append({"requirement": req, "expected": want, "measured": got,
                       "verdict": "met" if ok else "unmet", "note": note})

    dur_tol = 2.0
    add("duration", f"{expected['duration_s']}s +/- {dur_tol}",
        f"{measured['duration_s']}s",
        abs(measured["duration_s"] - expected["duration_s"]) <= dur_tol)

    want_bpm, got_bpm = expected["bpm"], measured["tempo_bpm"]
    octave_error = min(abs(got_bpm - want_bpm * m) for m in (0.5, 1.0, 2.0))
    add("tempo", f"{want_bpm} BPM +/- 6 (octave-tolerant)", f"{got_bpm} BPM",
        octave_error <= 6,
        f"closest octave is {octave_error:.1f} BPM away")

    want_key = f"{expected['key']} {expected['mode']}"
    add("key", want_key, measured["key"], measured["key"] == want_key,
        f"chroma correlation {measured['key_correlation']}; relative and parallel keys are "
        f"routinely confused by this method")

    # Clipping is not a binary. A decoded lossy file routinely overshoots by a fraction of a dB
    # because of the codec, and a handful of samples at full scale in eight million is inaudible.
    # The gate is therefore the clipped *proportion* plus the true peak, and the raw count is still
    # reported so nothing is hidden.
    total = measured["duration_s"] * measured["sample_rate"] * measured["channels"]
    ppm = measured["clipped_samples"] / total * 1e6
    add("clipping", "<= 100 ppm at full scale and true peak < +1.5 dBFS",
        f"{measured['clipped_samples']} samples ({ppm:.1f} ppm), peak "
        f"{measured['true_peak_dbfs']:+.2f} dBFS",
        ppm <= 100 and measured["true_peak_dbfs"] < 1.5,
        "this artifact is an MP3, so the measurement is of the decoded signal and codec overshoot "
        "is expected; a WAV master would be the artifact of record")
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=str(HERE / "audio.mp3"))
    ap.add_argument("--prompt", default=str(HERE / "prompt.json"))
    args = ap.parse_args()

    prompt = json.loads(Path(args.prompt).read_text())
    measured = measure(Path(args.audio))
    checks = verdicts(measured, prompt["metadata"])

    print(json.dumps(measured, indent=2))
    print()
    for c in checks:
        mark = "met    " if c["verdict"] == "met" else "UNMET  "
        print(f"  [{mark}] {c['requirement']:<10} expected {c['expected']:<32} got {c['measured']}")
        if c["note"]:
            print(f"            {c['note']}")

    report = {
        "song_id": prompt["song_id"],
        "audio": str(Path(args.audio).name),
        "measured": measured,
        "checks": checks,
        "overall": "compliant" if all(c["verdict"] == "met" for c in checks)
        else "non_compliant",
        "note": "Mechanical requirements only. Lyric, semantic and policy requirements are checked "
                "against the text artifacts and the oracle, not here.",
    }
    (HERE / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\noverall: {report['overall']}; wrote report.json")
    return 0 if report["overall"] == "compliant" else 1


if __name__ == "__main__":
    raise SystemExit(main())
