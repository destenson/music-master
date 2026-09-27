"""Measure the dynamic contrast between sections.

The signature of quiet-loud music is not a caption, it is a measurable difference between how loud,
bright and busy the verse is and how loud, bright and busy the chorus is. If the sections measure
the same, no tag list will save it. This checks the one thing that actually matters for this genre
and that the mechanical compliance pass never looked at.

    NUMBA_CACHE_DIR=... python analyse_sections.py --audio audio.mp3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 22050


def db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def section_stats(y: np.ndarray, sr: int, audio: np.ndarray, a_sr: int,
                  start: float, dur: float, meter) -> dict:
    a0, a1 = int(start * a_sr), int((start + dur) * a_sr)
    seg = audio[a0:a1]
    y0, y1 = int(start * sr), int((start + dur) * sr)
    ys = y[y0:y1]
    if len(seg) == 0 or len(ys) == 0:
        return {}

    rms = float(np.sqrt(np.mean(seg ** 2)))
    onset = librosa.onset.onset_detect(y=ys, sr=sr)
    centroid = float(librosa.feature.spectral_centroid(y=ys, sr=sr).mean())
    flatness = float(librosa.feature.spectral_flatness(y=ys).mean())
    try:
        lufs = float(meter.integrated_loudness(seg))
    except Exception:
        lufs = float("nan")

    # A crude "is the vocal present" proxy: energy in the 200 Hz - 4 kHz band relative to total.
    spec = np.abs(librosa.stft(ys, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (freqs >= 200) & (freqs <= 4000)
    vocal_ratio = float(spec[band].sum() / max(spec.sum(), 1e-9))

    return {
        "start": round(start, 1),
        "dur": round(dur, 1),
        "rms_dbfs": round(db(rms), 2),
        "lufs": round(lufs, 2) if lufs == lufs else None,
        "onset_per_s": round(len(onset) / dur, 2),
        "centroid_hz": round(centroid),
        "flatness": round(flatness, 5),
        "midband_ratio": round(vocal_ratio, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=str(HERE / "audio.mp3"))
    ap.add_argument("--composition", default=str(HERE / "composition.json"))
    args = ap.parse_args()

    comp = json.loads(Path(args.composition).read_text())
    audio, a_sr = sf.read(Path(args.audio), always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    y = librosa.resample(mono, orig_sr=a_sr, target_sr=SR)
    meter = pyln.Meter(a_sr)

    rows = []
    for sec in comp["sections"]:
        st = section_stats(y, SR, audio, a_sr, sec["start_s"], sec["dur_s"], meter)
        if st:
            st["role"] = sec["role"]
            st["label"] = sec["label"]
            st["instrumental"] = sec["instrumental"]
            rows.append(st)

    print(f"{'section':<22}{'start':>6}{'dur':>6}{'RMS dBFS':>10}{'LUFS':>8}"
          f"{'onset/s':>9}{'centroid':>10}{'mid%':>7}")
    for r in rows:
        print(f"{r['label'][:20]:<22}{r['start']:>6.1f}{r['dur']:>6.1f}{r['rms_dbfs']:>10.2f}"
              f"{(r['lufs'] if r['lufs'] is not None else float('nan')):>8.1f}"
              f"{r['onset_per_s']:>9.2f}{r['centroid_hz']:>10}{r['midband_ratio']*100:>7.1f}")

    def mean_of(role: str, key: str) -> float | None:
        vals = [r[key] for r in rows if r["role"] == role and not r["instrumental"] and r[key] is not None]
        return round(float(np.mean(vals)), 2) if vals else None

    print("\ncontrast (the thing that makes quiet-loud music work):")
    report = {"sections": rows, "contrast": {}}
    for key, label, unit in (("rms_dbfs", "loudness", "dB"), ("centroid_hz", "brightness", "Hz"),
                             ("onset_per_s", "busyness", "onsets/s")):
        v, c = mean_of("verse", key), mean_of("chorus", key)
        if v is None or c is None:
            continue
        delta = round(c - v, 2)
        report["contrast"][key] = {"verse": v, "chorus": c, "delta": delta}
        verdict = "FLAT" if abs(delta) < (1.0 if key == "rms_dbfs" else
                                          (150 if key == "centroid_hz" else 0.5)) else "contrast"
        print(f"  {label:<11} verse {v:>8} {unit}   chorus {c:>8} {unit}   "
              f"delta {delta:>+7}   {verdict}")

    (HERE / "section_analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    print("\nwrote section_analysis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
