"""Measure the step sweep, and write the residual so it can be heard rather than trusted.

Run with the ComfyUI venv:

    NUMBA_CACHE_DIR=songs/rap-metal-groove/.numba \
      /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/step_sweep_measure.py
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
STEPS = [1, 2, 3, 4, 8]
BANDS = [(20, 125), (125, 250), (250, 500), (500, 1000), (1000, 2500),
         (2500, 5000), (5000, 8000), (8000, 11000)]


def load(path: Path):
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    return audio, sr


def mono_resampled(audio: np.ndarray, sr: int) -> np.ndarray:
    return librosa.resample(audio.mean(axis=1), orig_sr=sr, target_sr=SR)


def band_energy(y: np.ndarray) -> np.ndarray:
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    return np.array([spec[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in BANDS])


def main() -> int:
    clips: dict[int, tuple[np.ndarray, int]] = {}
    for steps in STEPS:
        path = HERE / f"song-{steps}step.mp3"
        if not path.exists():
            print(f"missing {path.name}")
            return 1
        clips[steps] = load(path)

    ref_audio, ref_sr = clips[8]
    ref = mono_resampled(ref_audio, ref_sr)
    ref_bands = band_energy(ref)

    report: dict = {"bands_hz": [f"{lo}-{hi}" for lo, hi in BANDS], "steps": {}}
    for steps in STEPS:
        audio, sr = clips[steps]
        y = mono_resampled(audio, sr)
        n = min(len(y), len(ref))
        a, b = y[:n], ref[:n]
        wave_db = 20 * np.log10(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(b**2)) + 1e-12) + 1e-12)
        mel_a = librosa.power_to_db(librosa.feature.melspectrogram(y=a, sr=SR, n_mels=64, hop_length=512), ref=np.max)
        mel_b = librosa.power_to_db(librosa.feature.melspectrogram(y=b, sr=SR, n_mels=64, hop_length=512), ref=np.max)
        bands = band_energy(y)
        report["steps"][steps] = {
            "duration_s": round(len(audio) / sr, 2),
            "integrated_lufs": round(float(pyln.Meter(sr).integrated_loudness(audio)), 2),
            "spectral_centroid_hz": round(float(librosa.feature.spectral_centroid(y=y, sr=SR).mean()), 1),
            "rolloff85_hz": round(float(librosa.feature.spectral_rolloff(y=y, sr=SR, roll_percent=0.85).mean()), 1),
            "vs_8step_wave_db": round(float(wave_db), 1),
            "vs_8step_mel_mean_abs_db": round(float(np.mean(np.abs(mel_a - mel_b))), 2),
            "vs_8step_mel_correlation": round(float(np.corrcoef(mel_a.ravel(), mel_b.ravel())[0, 1]), 3),
            "vs_8step_band_db": [round(float(10 * np.log10((band + 1e-12) / (r + 1e-12))), 1)
                                 for band, r in zip(bands, ref_bands)],
        }
        if steps != 8:
            residual = (a - b).astype("float32")
            sf.write(HERE / f"residual-{steps}vs8.wav", residual, SR)
            print(f"wrote residual-{steps}vs8.wav (peak {np.max(np.abs(residual)):.4f})")

    print(json.dumps(report, indent=2))
    (HERE / "step_sweep.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
