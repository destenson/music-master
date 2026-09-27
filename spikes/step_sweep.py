"""Sweep sampler steps on the full-length song: where does the render stop changing?

ACE-Step 1.5 XL Turbo is distilled for few steps and runs cfg 1.0, so 8 may be far more than the
model needs. Same seed, same conditioning, same 187.8s length; only `KSampler.steps` moves.

    python3 spikes/step_sweep.py 1 4
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("prefix_probe", HERE / "prefix_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main(argv: list[str]) -> int:
    probe.OUT.mkdir(parents=True, exist_ok=True)
    for steps in [int(a) for a in argv[1:]]:
        probe.render(f"song-{steps}step", lambda w, s=steps: w["8"]["inputs"].update({"steps": s}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
