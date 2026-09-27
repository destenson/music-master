"""Feasibility probe for Music Master's deterministic measurement layer.

The design claims that mechanical requirements (tempo, key, duration, loudness,
clipping) are measured in code and never sent to a Jev-like model. This probe
checks that the tooling already on disk can actually make those measurements, so
the claim rests on a run rather than an assumption.

It synthesises a known signal -- a 92 BPM click track plus an F# minor triad --
measures it back, and reports the error. Run with the ComfyUI venv, which already
has librosa, soundfile and pyloudnorm installed:

    /home/dennis/src/comfyanonymous--ComfyUI/.venv/bin/python \
        spikes/measurement_probe.py

No GPU is required and nothing is downloaded.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import librosa
import librosa.feature.rhythm  # lazy_loader does not expose this submodule as an attribute
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

SR = 22050
BPM = 92.0
DURATION_S = 12.0
# F# minor triad, F#3 / A3 / C#4, as a crude but unambiguous harmonic signal.
F_SHARP_MINOR = [185.00, 220.00, 277.18]


def synth_probe() -> np.ndarray:
    n = int(SR * DURATION_S)
    t = np.arange(n) / SR
    # Sustained triad with slow amplitude movement, so chroma has something to read.
    chord = sum(np.sin(2 * math.pi * f * t) for f in F_SHARP_MINOR) / len(F_SHARP_MINOR)
    # Detune the chord's own periodicity well away from the beat rate, so the
    # tempo tracker cannot lock onto the pad instead of the pulse.
    chord *= 0.5 + 0.5 * np.sin(2 * math.pi * 3.0 * t)
    # Clicks on every beat at the target tempo.
    beat_period = 60.0 / BPM
    click = np.zeros(n)
    for k in range(int(DURATION_S / beat_period)):
        i = int(k * beat_period * SR)
        seg = min(220, n - i)
        click[i : i + seg] += np.hanning(seg)
    audio = 0.35 * chord + click
    return audio.astype(np.float32)


def measure(audio: np.ndarray) -> dict:
    out: dict = {}

    # Duration: trivial, from sample count.
    out["duration_s"] = round(len(audio) / SR, 3)

    # Tempo: librosa onset-envelope autocorrelation. This is the number the design
    # refuses to ask a language model to compare. Note the first version of this
    # probe used beat_track on a pad whose own amplitude modulation dominated the
    # envelope and returned 0.0 BPM, which is why the design requires every
    # measurement to be validated against known-tempo audio.
    hop = 256
    onset_env = librosa.onset.onset_strength(y=audio, sr=SR, hop_length=hop)
    tempo_est = librosa.feature.rhythm.tempo(
        onset_envelope=onset_env, sr=SR, hop_length=hop, start_bpm=120.0, std_bpm=4.0
    )
    out["tempo_bpm"] = round(float(np.atleast_1d(tempo_est)[0]), 2)
    _, beats = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=SR, hop_length=hop, start_bpm=float(out["tempo_bpm"] or 120.0)
    )
    out["n_beats"] = int(len(beats))

    # Key: chroma energy compared against Krumhansl-Schmuckler style profiles.
    chroma = librosa.feature.chroma_cqt(y=audio, sr=SR).mean(axis=1)
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 3.66, 2.29, 2.88, 5.19, 2.29, 3.66, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    best = None
    for i, name in enumerate(names):
        for mode, profile in (("major", major), ("minor", minor)):
            rotated = np.roll(profile, i)
            r = float(np.corrcoef(chroma, rotated)[0, 1])
            if best is None or r > best[0]:
                best = (r, f"{name} {mode}")
    out["key"] = best[1]
    out["key_correlation"] = round(best[0], 3)

    # Loudness and peak, for the loudness/clipping requirements.
    meter = pyln.Meter(SR)
    out["integrated_lufs"] = round(float(meter.integrated_loudness(audio)), 2)
    out["true_peak_dbfs"] = round(float(20 * np.log10(max(np.max(np.abs(audio)), 1e-9))), 2)
    out["clipped_samples"] = int(np.sum(np.abs(audio) >= 0.999))

    # Spectral facts available for the era/production surrogate.
    centroid = librosa.feature.spectral_centroid(y=audio, sr=SR)
    out["spectral_centroid_hz"] = round(float(centroid.mean()), 1)
    out["onset_count"] = int(len(librosa.onset.onset_detect(y=audio, sr=SR)))
    return out


def main() -> None:
    audio = synth_probe()
    measured = measure(audio)

    expected_bpm = BPM
    expected_key = "F# minor"
    tempo_error = abs(measured["tempo_bpm"] - expected_bpm)
    # librosa reports tempo in one tempo octave; 46 and 184 are the same pulse
    # relationship as 92, so the design must compare with octave tolerance.
    octave_error = min(
        abs(measured["tempo_bpm"] - expected_bpm * m) for m in (0.5, 1.0, 2.0)
    )

    print(json.dumps(measured, indent=2))
    print()
    print(f"expected tempo      : {expected_bpm} BPM")
    print(f"measured tempo      : {measured['tempo_bpm']} BPM (error {tempo_error:.2f})")
    print(f"best octave error   : {octave_error:.2f} BPM")
    print(f"expected key        : {expected_key}")
    print(f"measured key        : {measured['key']}")
    print(f"key match           : {measured['key'] == expected_key}")
    # The synthesised click + pad deliberately rides above full scale so the
    # clipping detector has something to find. A non-zero count here is the
    # detector working, not a rendering bug; true_peak_dbfs above 0 is the
    # float signal exceeding 0 dBFS.
    print(
        f"clipped samples     : {measured['clipped_samples']} "
        f"(expected > 0: the probe signal deliberately exceeds full scale)"
    )

    out_dir = Path(__file__).resolve().parent
    (out_dir / "measurement_probe.result.json").write_text(
        json.dumps(
            {
                "measured": measured,
                "expected": {"tempo_bpm": expected_bpm, "key": expected_key},
                "tempo_absolute_error": round(tempo_error, 3),
                "tempo_octave_tolerant_error": round(octave_error, 3),
                "key_match": measured["key"] == expected_key,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {out_dir / 'measurement_probe.result.json'}")


if __name__ == "__main__":
    main()
