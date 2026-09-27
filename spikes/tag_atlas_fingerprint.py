"""Turn the atlas into something navigable: a fingerprint per tag.

Each clip already has a pinned base, so the useful signal is twofold: what the clip sounds like on
its own (a mean log-mel envelope, for similarity) and what the tag changed against its base (per
octave-band dB). The first lets a listener find tags that sound alike without hearing all 730; the
second is a sparkline of the change.

    NUMBA_CACHE_DIR=songs/rap-metal-groove/.numba \
      /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python spikes/tag_atlas_fingerprint.py
"""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

OUT = Path(__file__).resolve().parent / "tag-atlas"
SR = 22050
BANDS = [(20, 125), (125, 250), (250, 500), (500, 1000), (1000, 2500),
         (2500, 5000), (5000, 8000), (8000, 11000)]


def load(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    return audio, sr


def resample(audio: np.ndarray, sr: int) -> np.ndarray:
    return librosa.resample(audio.mean(axis=1), orig_sr=sr, target_sr=SR)


def mel(y: np.ndarray) -> np.ndarray:
    return librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=SR, n_mels=64, hop_length=512), ref=np.max)


def band_energy(y: np.ndarray) -> np.ndarray:
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    return np.array([spec[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in BANDS])


def features(path: Path, base: np.ndarray | None) -> dict:
    audio, sr = load(path)
    y = resample(audio, sr)
    out = {
        "duration_s": round(len(audio) / sr, 2),
        "integrated_lufs": round(float(pyln.Meter(sr).integrated_loudness(audio)), 2),
        "spectral_centroid_hz": round(float(librosa.feature.spectral_centroid(y=y, sr=SR).mean()), 1),
        "rolloff85_hz": round(float(librosa.feature.spectral_rolloff(y=y, sr=SR, roll_percent=0.85).mean()), 1),
        "onset_count": int(len(librosa.onset.onset_detect(y=y, sr=SR))),
        "mel_mean": [round(float(v), 2) for v in mel(y).mean(axis=1)],
    }
    if base is not None:
        n = min(len(y), len(base))
        a, b = y[:n], base[:n]
        out["vs_base"] = {
            "wave_db": round(float(20 * np.log10(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(b**2)) + 1e-12) + 1e-12)), 1),
            "mel_abs_db": round(float(np.mean(np.abs(mel(a) - mel(b)))), 2),
            "mel_correlation": round(float(np.corrcoef(mel(a).ravel(), mel(b).ravel())[0, 1]), 3),
            "band_db": [round(float(10 * np.log10((x + 1e-12) / (y_ + 1e-12))), 1)
                        for x, y_ in zip(band_energy(a), band_energy(b))],
        }
    return out


def main() -> int:
    index = json.loads((OUT / "index.json").read_text())
    bases: dict[str, np.ndarray] = {}
    fingerprint: dict = {"bands_hz": [f"{lo}-{hi}" for lo, hi in BANDS], "bases": {}, "clips": []}

    for name, entry in index["bases"].items():
        path = OUT / entry["file"]
        if not path.exists():
            continue
        bases[name] = resample(*load(path))
        fingerprint["bases"][name] = {"caption": entry["caption"], **features(path, None)}

    for clip in index["clips"]:
        path = OUT / clip["file"]
        if not path.exists():
            continue
        row = {"bin": clip["bin"], "option": clip["option"], "label": clip["label"],
               "base": clip["base"], **features(path, bases.get(clip["base"]))}
        fingerprint["clips"].append(row)
        if len(fingerprint["clips"]) % 50 == 0:
            print(f"fingerprinted {len(fingerprint['clips'])}", flush=True)

    (OUT / "fingerprints.json").write_text(json.dumps(fingerprint, indent=2) + "\n")
    print(f"wrote fingerprints for {len(fingerprint['clips'])} clips and {len(fingerprint['bases'])} bases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
