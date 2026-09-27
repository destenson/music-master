"""Build the tag atlas: one short clip per caption tag, on a pinned bed and seed.

The vocabulary has 700-odd options and not one of them carries a description, so the audio is the
documentation. Every clip here shares the same bed, seed, length and sampler settings, so the tags
are comparable by ear and by measurement.

The bed is a plain, mid-tempo song: a genre, a straight groove, live drums, fingerstyle bass, a
clean electric guitar, a male lead, polished production and a dry mix. When a bin is under test its
own bed tag is dropped, so the tag under test is the only instruction on that axis. The bed keeps a
vocal on purpose -- most of the vocabulary is vocal, and a silent bed would make it inaudible.

    python3 spikes/tag_atlas.py --limit 12   # bases plus a sample, for a sanity listen
    python3 spikes/tag_atlas.py              # the whole vocabulary, resumable

Clips land in spikes/tag-atlas/, with index.json recording the exact caption each one was rendered
from. Re-running skips what is already there and renders only what is missing.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8288"
CLIENT = "music-master-atlas"
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "tag-atlas"
AUDIO = OUT / "audio"
BASES = OUT / "base"

SECONDS = 8.0
STEPS = 8
SEED = 12345
LYRICS = "Hold the line, we're moving through the night"

# bin id -> option label. Resolved to ids against the vocabulary so a label rename cannot silently
# point at nothing.
BED = {
    "genre": "Rock",
    "groove": "Straight",
    "drums": "Live Drums",
    "bass": "Fingerstyle Bass",
    "harmony": "Clean Electric Guitar",
    "lead_vocal": "Male Vocals",
    "production": "Polished Production",
    "space": "Dry Mix",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def load_vocabulary() -> tuple[dict, list[str], dict[str, dict], dict[tuple[str, str], dict]]:
    vocab = load(ROOT / "vocabulary" / "tag-bins.json")
    bins = {b["id"]: b for b in vocab["bins"]}
    order = [b for b in vocab["render_order"] if bins.get(b, {}).get("emits_tag", True) and bins.get(b, {}).get("options")]
    by_label = {(bid, o["label"]): o for bid in bins for o in (bins[bid].get("options") or [])}
    return vocab, order, bins, by_label


def resolve_bed(bins: dict) -> dict[str, dict]:
    bed: dict[str, dict] = {}
    for bin_id, label in BED.items():
        option = next((o for o in (bins[bin_id].get("options") or []) if o["label"] == label), None)
        if option is None:
            raise SystemExit(f"bed option {label!r} is not in bin {bin_id!r}")
        bed[bin_id] = option
    return bed


def bed_labels(bed: dict[str, dict], exclude_bin: str, test: dict | None) -> list[str]:
    """The bed, minus the bin under test and minus anything the test tag excludes."""
    out: list[str] = []
    for bin_id, option in bed.items():
        if bin_id == exclude_bin:
            continue
        if test is not None:
            if option["id"] in (test.get("excludes") or []) or test["id"] in (option.get("excludes") or []):
                continue
        out.append(option["label"])
    return out


def caption_for(bed: dict[str, dict], bin_id: str, test: dict | None) -> str:
    tags = bed_labels(bed, bin_id, test)
    if test is not None:
        tags = [*tags, test["label"]]
    return ", ".join(tags)


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=60) as response:
        return json.loads(response.read())


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def graph(caption: str, prefix: str) -> dict:
    workflow = load(ROOT / "songs/rap-metal-groove/workflow.json")
    workflow["4"]["inputs"].update({"tags": caption, "lyrics": LYRICS, "duration": SECONDS, "seed": SEED})
    workflow["6"]["inputs"]["seconds"] = SECONDS
    workflow["8"]["inputs"].update({"steps": STEPS, "seed": SEED})
    workflow["10"]["inputs"]["filename_prefix"] = prefix
    return workflow


def output_files(entry: dict) -> list[dict]:
    files: list[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for value in node.values():
            if isinstance(value, list):
                files += [i for i in value if isinstance(i, dict) and "filename" in i]
    return files


def fetch_audio(entry: dict, target: Path) -> str:
    for item in output_files(entry):
        query = urllib.parse.urlencode({
            "filename": item["filename"], "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        data = get_bytes(f"{BASE_URL}/view?{query}")
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    raise RuntimeError("the render reported no output file")


def run(caption: str, target: Path) -> str:
    """Render one caption to `target`; return the status string."""
    job = post("/prompt", {"prompt": graph(caption, f"mm-atlas-tags/{target.stem}"), "client_id": CLIENT})["prompt_id"]
    started = time.time()
    while True:
        time.sleep(0.5)
        entry = get_json(f"/history/{job}").get(job, {})
        status = (entry.get("status") or {}).get("status_str")
        if status in ("success", "error"):
            break
        if time.time() - started > 300:
            return "timeout"
    if status != "success":
        return status
    fetch_audio(entry, target)
    return "success"


def main(argv: list[str]) -> int:
    limit = None
    for arg in argv[1:]:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
    _vocab, order, bins, _by_label = load_vocabulary()
    bed = resolve_bed(bins)
    AUDIO.mkdir(parents=True, exist_ok=True)
    BASES.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    index = load(index_path) if index_path.exists() else {"bases": {}, "clips": [], "settings": {
        "seconds": SECONDS, "steps": STEPS, "seed": SEED, "lyrics": LYRICS, "bed": BED,
    }}

    # Bases first: the bed with the bin's own tag removed, so the tag under test is the only
    # instruction on that axis. Bins not in the bed share the full bed as their base.
    base_files: dict[str, str] = {}
    distinct: dict[str, str] = {}
    for bin_id in order:
        caption = caption_for(bed, bin_id, None)
        distinct.setdefault(caption, f"{bin_id}")
    total_bases = len(distinct)
    for n, (caption, name) in enumerate(distinct.items(), start=1):
        target = BASES / f"{name}.mp3"
        if not target.exists():
            status = run(caption, target)
            print(f"base {n}/{total_bases} {name}: {status}", flush=True)
        index["bases"][name] = {"caption": caption, "file": f"base/{name}.mp3"}
    for bin_id in order:
        base_files[bin_id] = next(name for caption, name in distinct.items() if caption == caption_for(bed, bin_id, None))
    index_path.write_text(json.dumps(index, indent=2) + "\n")

    done = {c["file"] for c in index["clips"]}
    pending = [(bid, o) for bid in order for o in (bins[bid].get("options") or [])]
    print(f"{len(pending)} tag clips pending; {len(done)} already rendered", flush=True)

    for n, (bin_id, option) in enumerate(pending, start=1):
        rel = f"audio/{bin_id}__{option['id']}.mp3"
        if rel in done or (AUDIO / f"{bin_id}__{option['id']}.mp3").exists():
            continue
        if limit is not None and n > limit:
            print(f"stopping at --limit={limit}", flush=True)
            break
        caption = caption_for(bed, bin_id, option)
        target = AUDIO / f"{bin_id}__{option['id']}.mp3"
        started = time.time()
        try:
            status = run(caption, target)
        except Exception as cause:  # one bad caption must not end a 730-clip batch
            status = f"failed: {cause}"
        sha = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        index["clips"].append({
            "bin": bin_id, "option": option["id"], "label": option["label"],
            "caption": caption, "file": rel, "base": base_files[bin_id], "sha256": sha, "status": status,
        })
        index_path.write_text(json.dumps(index, indent=2) + "\n")
        print(f"{n}/{len(pending)} {bin_id}/{option['id']}: {status} {time.time()-started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
