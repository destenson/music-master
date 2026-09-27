"""Probe: is a short render a prefix of a long one, and is a low-step long render a usable draft?

Three graphs off the rap-metal-groove workflow, same seed:

  song-8step  the song as recorded (187.8s, 8 sampler steps)
  song-2step  the same length, 2 sampler steps -- a structural draft, not the final
  (full-8s from the earlier spike is the short render, read back for comparison)

If generation were temporal, song-8step's first 8 seconds would resemble full-8s. If it is
whole-clip diffusion, they are unrelated pieces, and song-2step's first 8 seconds should track
song-8step's first 8 seconds (same conditioning, coarser denoise) without matching it.

    python3 spikes/prefix_probe.py
"""

from __future__ import annotations

import importlib.util
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "preview-8s"

spec = importlib.util.spec_from_file_location("preview_8s", HERE / "preview_8s.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def render(name: str, mutator) -> None:
    workflow = json.loads((preview.ROOT / "songs/rap-metal-groove/workflow.json").read_text())
    workflow["10"]["inputs"]["filename_prefix"] = f"mm-spike/{name}"
    mutator(workflow)
    started = time.time()
    job = preview.post("/prompt", {"prompt": workflow, "client_id": preview.CLIENT})["prompt_id"]
    print(f"{name}: queued {job}", flush=True)
    entry: dict = {}
    while True:
        time.sleep(2)
        entry = preview.get_json(f"/history/{job}").get(job, {})
        if (entry.get("status") or {}).get("status_str") in ("success", "error"):
            break
        if time.time() - started > 900:
            print(f"{name}: gave up", flush=True)
            return
    status = (entry.get("status") or {}).get("status_str")
    print(f"{name}: {status} in {time.time() - started:.1f}s", flush=True)
    if status != "success":
        for message in (entry.get("status") or {}).get("messages") or []:
            print("   ", message, flush=True)
        return
    for item in preview.output_files(entry):
        query = urllib.parse.urlencode({
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        data = preview.get_bytes(f"{preview.BASE}/view?{query}")
        (OUT / f"{name}.mp3").write_bytes(data)
        print(f"    wrote {name}.mp3 ({len(data)} bytes)", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    render("song-8step", lambda w: None)
    render("song-2step", lambda w: w["8"]["inputs"].update({"steps": 2}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
