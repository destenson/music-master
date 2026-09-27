"""Compare the short render, the full render, and the low-step draft.

Run with the ComfyUI venv:

    NUMBA_CACHE_DIR=songs/rap-metal-groove/.numba \
      /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/prefix_probe_measure.py
"""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent / "preview-8s"
SR = 22050


def load(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    return audio.mean(axis=1), sr


def first_seconds(path: Path, seconds: float) -> np.ndarray:
    mono, sr = load(path)
    return librosa.resample(mono[: int(seconds * sr)], orig_sr=sr, target_sr=SR)


def spectrum(y: np.ndarray) -> np.ndarray:
    return librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=SR, n_mels=64, hop_length=512), ref=np.max)


def mel_delta(a: np.ndarray, b: np.ndarray) -> dict:
    frames = min(a.shape[1], b.shape[1])
    a, b = a[:, :frames], b[:, :frames]
    return {
        "mean_abs_db": round(float(np.mean(np.abs(a - b))), 2),
        "correlation": round(float(np.corrcoef(a.ravel(), b.ravel())[0, 1]), 3),
    }


def wave_delta(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    return round(float(20 * np.log10(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(a**2)) + 1e-12) + 1e-12)), 1)


def main() -> int:
    short = HERE / "full-8s.mp3"
    full = HERE / "song-8step.mp3"
    draft = HERE / "song-2step.mp3"
    for path in (short, full, draft):
        if not path.exists():
            print(f"missing {path.name}; run spikes/prefix_probe.py first")
            return 1

    for name in ("full-8s", "song-8step", "song-2step"):
        mono, sr = load(HERE / f"{name}.mp3")
        print(f"{name:<12} {len(mono)/sr:6.2f}s")

    short8 = first_seconds(short, 8.0)
    full8 = first_seconds(full, 8.0)
    draft8 = first_seconds(draft, 8.0)

    result = {
        "first_8s": {
            "short_vs_full": {**mel_delta(spectrum(short8), spectrum(full8)), "wave_db": wave_delta(short8, full8)},
            "draft_vs_full": {**mel_delta(spectrum(draft8), spectrum(full8)), "wave_db": wave_delta(draft8, full8)},
            "draft_vs_short": {**mel_delta(spectrum(draft8), spectrum(short8)), "wave_db": wave_delta(draft8, short8)},
        },
        "full_length_draft_vs_full": {
            **mel_delta(spectrum(load(draft)[0]), spectrum(load(full)[0])),
            "wave_db": wave_delta(load(draft)[0], load(full)[0]),
        },
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
