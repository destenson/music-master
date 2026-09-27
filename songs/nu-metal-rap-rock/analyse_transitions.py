"""Measure what actually happened at each section boundary.

A transition is the one part of this design's arrangement vocabulary that leaves a physical trace.
A stop is a gap in the audio. A riser is energy climbing into the downbeat. A fill is a spike in
onset density in the outgoing section's last bar. A level step is exactly that. So a declared
transition can be checked against the render instead of merely hoped for -- which is the difference
between this and per-section arrangement, where nothing is measurable and nothing can be verified.

    NUMBA_CACHE_DIR=... python analyse_transitions.py --audio take1.mp3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 22050

# What each declared signature is willing to accept as "it happened".
ACCEPTS = {
    "gap": {"gap"},
    "fill": {"fill"},
    "riser": {"riser", "sweep_up"},
    "downlifter": {"downlifter", "step_down", "sweep_down"},
    "build": {"riser", "fill", "sweep_up"},
    "step_up": {"step_up"},
    "step_down": {"step_down"},
    "sweep_up": {"sweep_up", "riser"},
    "sweep_down": {"sweep_down", "downlifter"},
    "smooth": {"smooth"},
    "step_any": {"step_up", "step_down", "fill", "gap", "riser", "sweep_up"},
    # Not reliably separable from a hard entry by these measures; reported as weak.
    "anticipation": {"step_up", "fill", "smooth"},
}
WEAK = {"anticipation", "step_any"}


def db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def rms(y: np.ndarray) -> float:
    return float(np.sqrt(np.mean(y ** 2))) if len(y) else 1e-9


def silence_run_ms(y: np.ndarray, sr: int, rel_db: float = -38.0) -> float:
    """Longest run below a threshold relative to the local peak, in milliseconds."""
    if not len(y):
        return 0.0
    env = np.abs(y)
    peak = float(np.max(env)) or 1e-9
    quiet = env < peak * (10 ** (rel_db / 20))
    best = run = 0
    for q in quiet:
        run = run + 1 if q else 0
        best = max(best, run)
    return best / sr * 1000.0


def classify(y: np.ndarray, sr: int, boundary: float, pre_start: float, post_end: float) -> dict:
    """boundary is where the outgoing section ends; post_end is where the next one ends."""
    b = int(boundary * sr)
    pre = y[max(int(pre_start * sr), b - 2 * sr):b]
    post = y[b:min(int(post_end * sr), b + 2 * sr)]
    if len(pre) < sr // 2 or len(post) < sr // 2:
        return {}

    rms_step = db(rms(post[:sr])) - db(rms(pre[-sr:]))
    # Compare the last half-second before the boundary with the first half-second of the window:
    # a riser is energy climbing into the downbeat, not a difference across the whole section.
    pre_slope = db(rms(pre[-sr // 2:])) - db(rms(pre[: sr // 2])) if len(pre) >= sr else 0.0
    post_slope = db(rms(post[-sr // 2:])) - db(rms(post[: sr // 2])) if len(post) >= sr else 0.0

    c_pre = float(librosa.feature.spectral_centroid(y=pre, sr=sr).mean())
    c_post = float(librosa.feature.spectral_centroid(y=post, sr=sr).mean())
    centroid_delta = c_post - c_pre

    gap = silence_run_ms(y[max(0, b - sr // 2):b + sr // 2], sr)

    # Fill: onset density in the outgoing section's last bar against the rest of the section.
    section = y[int(pre_start * sr):b]
    section_len = boundary - pre_start
    onsets = librosa.onset.onset_detect(y=section, sr=sr)
    onsets_s = onsets / sr
    last_bar_start = max(0.0, section_len - (4 * 60.0 / 120.0))
    in_last = sum(1 for t in onsets_s if t >= last_bar_start)
    bar_s = 4 * 60.0 / 120.0
    last_density = in_last / max(bar_s, 0.1)
    rest = max(0.0, last_bar_start)
    rest_density = (len(onsets) - in_last) / rest if rest > 0.5 else last_density
    fill_ratio = last_density / max(rest_density, 1e-6) if len(onsets) else 0.0

    if gap >= 150:
        kind = "gap"
    elif pre_slope >= 2.5 and centroid_delta > 0:
        kind = "riser"
    elif fill_ratio >= 1.4 and in_last >= 3:
        kind = "fill"
    elif rms_step >= 2.5:
        kind = "step_up"
    elif rms_step <= -2.5:
        kind = "step_down"
    elif centroid_delta >= 400:
        kind = "sweep_up"
    elif centroid_delta <= -400:
        kind = "sweep_down"
    elif pre_slope <= -2.5:
        kind = "downlifter"
    else:
        kind = "smooth"

    return {
        "detected": kind,
        "rms_step_db": round(rms_step, 2),
        "pre_slope_db": round(pre_slope, 2),
        "post_slope_db": round(post_slope, 2),
        "centroid_delta_hz": round(centroid_delta),
        "gap_ms": round(gap),
        "fill_ratio": round(fill_ratio, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=str(HERE / "take1.mp3"))
    ap.add_argument("--composition", default=str(HERE / "composition.json"))
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    comp = json.loads(Path(args.composition).read_text())
    tags = json.loads((Path(__file__).resolve().parent.parent.parent /
                       "vocabulary" / "section-tags.json").read_text())
    labels = {t["id"]: t for t in tags["transition_tags"]}

    audio, a_sr = sf.read(Path(args.audio), always_2d=True, dtype="float32")
    y = librosa.resample(audio.mean(axis=1), orig_sr=a_sr, target_sr=SR)

    rows = comp["sections"]
    name = args.label or Path(args.audio).name
    print(f"{name}: boundaries (declared vs measured)")
    print(f"  {'from -> to':<34}{'declared':<16}{'detected':<14}{'step dB':>9}"
          f"{'pre dB':>8}{'cent Hz':>9}{'gap ms':>7}{'fill':>6}  verdict")

    results = []
    for i in range(len(rows) - 1):
        cur, nxt = rows[i], rows[i + 1]
        boundary = cur["start_s"] + cur["dur_s"]
        declared_id = cur.get("transition_out")
        if not declared_id:
            continue
        declared = labels.get(declared_id)
        m = classify(y, SR, boundary, cur["start_s"], nxt["start_s"] + nxt["dur_s"])
        if not m:
            continue
        sig = declared.get("signature") if declared else None
        ok = m["detected"] in ACCEPTS.get(sig, set())
        verdict = "met" if ok else "UNMET"
        if sig in WEAK:
            verdict += " (weak)"
        label = f"{cur['label'][:14]} -> {nxt['label'][:14]}"
        print(f"  {label:<34}{(declared['label'] if declared else declared_id):<16}"
              f"{m['detected']:<14}{m['rms_step_db']:>9.2f}{m['pre_slope_db']:>8.2f}"
              f"{m['centroid_delta_hz']:>9}{m['gap_ms']:>7}{m['fill_ratio']:>6.2f}  {verdict}")
        results.append({"from": cur["label"], "to": nxt["label"],
                        "declared": declared_id,
                        "declared_label": declared["label"] if declared else None,
                        "signature": sig, **m, "met": ok})

    met = sum(1 for r in results if r["met"])
    print(f"\n  transitions met: {met} of {len(results)}")
    out = HERE / (f"transition_analysis_{args.label}.json" if args.label
                  else "transition_analysis.json")
    out.write_text(json.dumps({"audio": name, "boundaries": results,
                               "met": met, "total": len(results)}, indent=2) + "\n")
    print(f"  wrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
