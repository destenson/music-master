"""Measure the 8-second preview spike: is a short clip coherent, and did the tag move the audio?

Run with the ComfyUI venv, which has librosa:

    /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/preview_8s_measure.py
"""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

HERE = Path(__file__).resolve().parent / "preview-8s"
SR = 22050


def measure(path: Path) -> dict:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    y = librosa.resample(mono, orig_sr=sr, target_sr=SR)
    meter = pyln.Meter(sr)
    return {
        "duration_s": round(len(mono) / sr, 3),
        "sample_rate": sr,
        "channels": audio.shape[1],
        "integrated_lufs": round(float(meter.integrated_loudness(audio)), 2),
        "true_peak_dbfs": round(float(20 * np.log10(max(np.max(np.abs(audio)), 1e-9))), 2),
        "clipped_samples": int(np.sum(np.abs(audio) >= 0.999)),
        "spectral_centroid_hz": round(float(librosa.feature.spectral_centroid(y=y, sr=SR).mean()), 1),
        "spectral_bandwidth_hz": round(float(librosa.feature.spectral_bandwidth(y=y, sr=SR).mean()), 1),
        "onset_count": int(len(librosa.onset.onset_detect(y=y, sr=SR))),
        "rms": round(float(np.sqrt(np.mean(mono**2))), 5),
    }


def mel(path: Path) -> np.ndarray:
    """Log-mel over the first 8 seconds, so two clips of different length still compare."""
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sr, target_sr=SR)
    mono = mono[: int(8.0 * SR)]
    return librosa.power_to_db(
        librosa.feature.melspectrogram(y=mono, sr=SR, n_mels=64, hop_length=512), ref=np.max
    )


def delta(a: np.ndarray, b: np.ndarray) -> dict:
    frames = min(a.shape[1], b.shape[1])
    a, b = a[:, :frames], b[:, :frames]
    return {
        "mean_abs_db": round(float(np.mean(np.abs(a - b))), 2),
        "correlation": round(float(np.corrcoef(a.ravel(), b.ravel())[0, 1]), 3),
    }


def main() -> int:
    clips = {path.stem: path for path in sorted(HERE.glob("*.mp3"))}
    measured = {name: measure(path) for name, path in clips.items()}
    spectra = {name: mel(path) for name, path in clips.items()}

    # Everything is compared against the plain 8-second render. The repeat of that exact graph is
    # the noise floor: a tag delta has to beat it to mean anything.
    comparisons = {
        f"{name}_vs_full": delta(spectrum, spectra["full-8s"])
        for name, spectrum in spectra.items()
        if name != "full-8s"
    }
    print(json.dumps({"measured": measured, "comparisons": comparisons}, indent=2))
    (HERE / "measure.json").write_text(
        json.dumps({"measured": measured, "comparisons": comparisons}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
