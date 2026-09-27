"""Does the batched-caption node render each caption as if it had been rendered alone?

Four captions from one trap bed, rendered two ways at the same seed and settings:

  singles   the stock TextEncodeAceStepAudio1.5, one prompt each
  batch     MyToolbox_AceStepBatchTextEncode, all four in one prompt and one KSampler

If per-item conditioning works, batch item i matches single i and does not match its neighbours.
The failure mode to catch is a blend: every batch item correlating with every single.

    python3 spikes/batch_node_validation.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8288"
CLIENT = "music-master-batch-validation"
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "batch-validation"
NODE = "MyToolbox_AceStepBatchTextEncode"
SECONDS = 8.0
STEPS = 8
# A seed neither side has been rendered at, so no node-4 output is served from cache and the
# singles pay the LM the batch also pays.
SEED = 5555
LM = {"cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}

spec = importlib.util.spec_from_file_location("g", ROOT / "spikes/genre_atlas.py")
genre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(genre)


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(f"{BASE}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as response:
        return json.loads(response.read())


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def outputs(entry: dict) -> list[dict]:
    files: list[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for value in node.values():
            if isinstance(value, list):
                files += [i for i in value if isinstance(i, dict) and "filename" in i]
    return files


def submit(workflow: dict, prefix: str) -> tuple[str, float, list[Path]]:
    workflow["10"]["inputs"]["filename_prefix"] = prefix
    started = time.time()
    job = post("/prompt", {"prompt": workflow, "client_id": CLIENT})["prompt_id"]
    while True:
        time.sleep(0.2)
        entry = get_json(f"/history/{job}").get(job, {})
        status = (entry.get("status") or {}).get("status_str")
        if status in ("success", "error"):
            break
        if time.time() - started > 600:
            raise RuntimeError("timed out")
    if status != "success":
        for message in (entry.get("status") or {}).get("messages") or []:
            print("   ", message)
        raise RuntimeError(f"render failed: {status}")
    messages = {m[0]: m[1].get("timestamp")
                for m in (entry.get("status") or {}).get("messages") or [] if isinstance(m, list)}
    exec_s = (messages["execution_success"] - messages["execution_start"]) / 1000
    saved = []
    for index, item in enumerate(outputs(entry), start=1):
        query = urllib.parse.urlencode({"filename": item["filename"],
                                        "subfolder": item.get("subfolder", ""),
                                        "type": item.get("type", "output")})
        target = OUT / f"{prefix.split('/')[-1]}_{index:02d}.mp3"
        target.write_bytes(get_bytes(f"{BASE}/view?{query}"))
        saved.append(target)
    return status, exec_s, saved


def stock(caption: str) -> dict:
    workflow = genre.load(ROOT / "songs/rap-metal-groove/workflow.json")
    workflow["4"]["inputs"].update({"tags": caption, "lyrics": genre.LYRICS, "duration": SECONDS,
                                    "seed": SEED, **LM})
    workflow["6"]["inputs"]["seconds"] = SECONDS
    workflow["8"]["inputs"].update({"steps": STEPS, "seed": SEED})
    # Never inherit the song's own prefix: without this, any test that skips submit() writes into
    # the song's output namespace under the song's own filenames.
    workflow["10"]["inputs"]["filename_prefix"] = "mm-validation/stock"
    return workflow


def batched(captions: list[str], lyrics: str) -> dict:
    workflow = genre.load(ROOT / "songs/rap-metal-groove/workflow.json")
    workflow["11"] = {"class_type": NODE, "inputs": {
        "clip": ["2", 0], "captions": "\n".join(captions), "lyrics": lyrics, "bpm": 92,
        "duration": SECONDS, "timesignature": "4", "language": "en", "keyscale": "E minor",
        "seed": SEED, **LM,
    }}
    # The node emits one conditioning carrying every caption, so the stock latent node takes the
    # matching batch size and a single KSampler renders the whole batch in one pass.
    workflow["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["11", 0]}}
    workflow["6"]["inputs"].update({"seconds": SECONDS, "batch_size": len(captions)})
    workflow["8"]["inputs"].update({"steps": STEPS, "seed": SEED, "positive": ["11", 0],
                                    "negative": ["5", 0], "latent_image": ["6", 0]})
    # Never inherit the song's own prefix; see stock().
    workflow["10"]["inputs"]["filename_prefix"] = "mm-validation/batch"
    return workflow


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    order, bins = genre.vocabulary()
    bed = genre.resolve(bins, "trap", genre.PRESETS["trap"])
    # Four drum choices that should sound clearly different, on a bed whose own drum tag is
    # dropped. Similar-sounding tags cannot resolve a per-item check: their singles are already
    # nearly indistinguishable, so the diagonal would sit inside the off-diagonal noise.
    by_id = {option["id"]: option for option in bins["drums"]["options"]}
    # "No Drums" is the strong signal: if per-item conditioning is right, that batch row should be
    # dramatically unlike the other three, and each row should match its own single best.
    chosen = ["live_drums", "no_drums", "taiko", "handclaps"]
    captions = [genre.caption(bed, "drums", by_id[option]) for option in chosen]
    for i, caption in enumerate(captions, start=1):
        print(f"caption {i}: {caption}")

    singles: list[Path] = []
    single_time = 0.0
    for i, caption in enumerate(captions, start=1):
        _, exec_s, saved = submit(stock(caption), f"mm-validation/single-{i}")
        single_time += exec_s
        singles += saved
        print(f"single {i}: {exec_s:.2f}s -> {saved[0].name if saved else 'no file'}", flush=True)

    _, batch_exec, batch = submit(batched(captions, genre.LYRICS), "mm-validation/batch")
    print(f"batch of {len(captions)}: {batch_exec:.2f}s -> {len(batch)} file(s)", flush=True)
    print(f"singles total exec {single_time:.2f}s vs batch {batch_exec:.2f}s "
          f"({single_time / batch_exec:.1f}x)" if batch_exec else "batch produced nothing")

    if len(batch) != len(captions):
        print(f"MISMATCH: batch returned {len(batch)} files for {len(captions)} captions")
        return 1
    print("files:", [p.name for p in batch])
    for p in singles + batch:
        print("  ", p.name, hashlib.sha256(p.read_bytes()).hexdigest()[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
