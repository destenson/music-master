"""Measure whether the vocal reads as sung or as shouted, per section.

"You sound like you are yelling instead of singing" is a real, testable distinction. A sung note is
harmonic: energy sits in a stable stack of partials over a pitched fundamental. A shout or a raw
scream is broadband noise with an unstable pitch. So in the vocal band, a sung vocal has a high
harmonic-to-total energy ratio, low spectral flatness and a low zero-crossing rate, and a shouted
one moves all three the other way.

This is a proxy, not a verdict -- a good metal harsh vocal is *pitched* noise, which lands in
between, and no code can decide whether a performance is good. Its job is to say whether a change
moved the vocal in the intended direction, and by how much.

    NUMBA_CACHE_DIR=... python analyse_vocals.py --audio audio.mp3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

HERE = Path(__file__).resolve().parent
SR = 22050
VOCAL_BAND = (150.0, 3500.0)
WINDOW_S = 10.0


def band_limit(y: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    sos = butter(4, [lo / (sr / 2), hi / (sr / 2)], btype="band", output="sos")
    return sosfilt(sos, y)


def vocal_stats(seg: np.ndarray, sr: int) -> dict | None:
    if len(seg) < sr:
        return None
    yb = band_limit(seg, sr, *VOCAL_BAND)
    if not np.any(np.abs(yb) > 1e-4):
        return None

    S = np.abs(librosa.stft(yb, n_fft=2048, hop_length=256))
    harmonic, _ = librosa.decompose.hpss(librosa.stft(yb, n_fft=2048, hop_length=256), margin=2.0)
    h_energy = float(np.sum(np.abs(harmonic) ** 2))
    t_energy = float(np.sum(S ** 2)) or 1e-12

    rms = float(np.sqrt(np.mean(yb ** 2)))
    return {
        "harmonic_ratio": round(h_energy / t_energy, 4),
        "flatness": round(float(librosa.feature.spectral_flatness(S=S).mean()), 6),
        "zcr": round(float(librosa.feature.zero_crossing_rate(yb).mean()), 4),
        "rms_dbfs": round(float(20 * np.log10(max(rms, 1e-9))), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=str(HERE / "audio.mp3"))
    ap.add_argument("--composition", default=str(HERE / "composition.json"))
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    comp = json.loads(Path(args.composition).read_text())
    audio, a_sr = sf.read(Path(args.audio), always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    y = librosa.resample(mono, orig_sr=a_sr, target_sr=SR)

    rows = []
    for sec in comp["sections"]:
        if sec["instrumental"]:
            continue
        start, dur = sec["start_s"], sec["dur_s"]
        mid = start + max(0.0, (dur - WINDOW_S) / 2.0)
        seg = y[int(mid * SR):int((mid + min(WINDOW_S, dur)) * SR)]
        st = vocal_stats(seg, SR)
        if st:
            st.update({"role": sec["role"], "label": sec["label"]})
            rows.append(st)

    name = args.label or Path(args.audio).name
    print(f"{name}:  (vocal band {VOCAL_BAND[0]:.0f}-{VOCAL_BAND[1]:.0f} Hz, "
          f"{WINDOW_S:.0f}s window per section)")
    print(f"  {'section':<22}{'harmonic':>10}{'flatness':>11}{'zcr':>8}{'rms dBFS':>10}")
    for r in rows:
        print(f"  {r['label'][:20]:<22}{r['harmonic_ratio']:>10.4f}{r['flatness']:>11.6f}"
              f"{r['zcr']:>8.4f}{r['rms_dbfs']:>10.2f}")

    def mean_of(role: str, key: str) -> float | None:
        vals = [r[key] for r in rows if r["role"] == role]
        return round(float(np.mean(vals)), 4) if vals else None

    summary = {}
    print("\n  sung-vs-shouted summary (higher harmonic + lower flatness/zcr = more sung):")
    for key in ("harmonic_ratio", "flatness", "zcr"):
        v, c = mean_of("verse", key), mean_of("chorus", key)
        if v is None or c is None:
            continue
        summary[key] = {"verse": v, "chorus": c}
        print(f"    {key:<16} verse {v:>9}   chorus {c:>9}   delta {c - v:>+9.4f}")
    all_h = round(float(np.mean([r["harmonic_ratio"] for r in rows])), 4)
    print(f"    {'overall harmonic':<16} {all_h}")

    out = HERE / (f"vocal_analysis_{args.label}.json" if args.label else "vocal_analysis.json")
    out.write_text(json.dumps({"audio": name, "sections": rows, "summary": summary,
                               "overall_harmonic_ratio": all_h}, indent=2) + "\n")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
