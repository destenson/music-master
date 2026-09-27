"""Spike: does an 8-second ACE-Step render work, and what should a preview feed it?

Three variants of the rap-metal-groove graph, all at the same seed so the sampler holds the
arrangement and only the intended surface changes:

  full-8s    the whole lyric against the whole caption, 8 seconds
  verse1-8s  the lyric truncated to one section, 8 seconds
  notag-8s   the whole lyric, caption minus one tag, 8 seconds

The point is to learn whether a short clip is coherent at all, whether the model can do anything
with 188 seconds of words squeezed into 8, and whether dropping one tag moves the audio. Renders
land in spikes/preview-8s/ so they can be auditioned.

    python3 spikes/preview_8s.py
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8288"
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "preview-8s"
CLIENT = "music-master-preview-spike"
SECONDS = 8.0
SEED = 4409


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as response:
        return json.loads(response.read())


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def truncate(full: list[str], header: str) -> str:
    """The lyric from one section header to the next, so the model is asked for one section."""
    start = next(i for i, line in enumerate(full) if line.strip() == header)
    rest = full[start:]
    end = next(
        (i for i, line in enumerate(rest[1:], start=1)
         if line.startswith("[") and line.split(" - ")[0].strip("[]") in SECTION_HEADS),
        len(rest),
    )
    return "\n".join(rest[:end]).strip() + "\n"


SECTION_HEADS = {
    "Intro", "Verse", "Pre-Chorus", "Chorus", "Post-Chorus", "Bridge", "Breakdown", "Build",
    "Drop", "Outro", "Instrumental", "Solo", "Interlude", "Fade Out", "Silence",
}


def variants() -> dict[str, dict]:
    workflow = json.loads((ROOT / "songs/rap-metal-groove/workflow.json").read_text())
    full_lyrics = (ROOT / "songs/rap-metal-groove/lyrics.md").read_text()
    lines = full_lyrics.splitlines()
    tags = workflow["4"]["inputs"]["tags"]

    def graph(lyrics: str, caption: str, seconds: float, prefix: str) -> dict:
        built = json.loads(json.dumps(workflow))
        built["4"]["inputs"]["lyrics"] = lyrics
        built["4"]["inputs"]["tags"] = caption
        built["4"]["inputs"]["duration"] = seconds
        built["4"]["inputs"]["seed"] = SEED
        built["6"]["inputs"]["seconds"] = seconds
        built["8"]["inputs"]["seed"] = SEED
        built["10"]["inputs"]["filename_prefix"] = prefix
        return built

    without = ", ".join(t for t in tags.split(", ") if t != "Distorted Guitar")
    return {
        "full-8s": graph(full_lyrics, tags, SECONDS, "mm-spike/full-8s"),
        "verse1-8s": graph(truncate(lines, "[Verse 1]"), tags, SECONDS, "mm-spike/verse1-8s"),
        "notag-8s": graph(full_lyrics, without, SECONDS, "mm-spike/notag-8s"),
    }


def output_files(entry: dict) -> list[dict]:
    files: list[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for value in node.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and "filename" in item:
                    files.append(item)
    return files


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, workflow in variants().items():
        started = time.time()
        queued = post("/prompt", {"prompt": workflow, "client_id": CLIENT})
        job = queued.get("prompt_id")
        print(f"{name}: queued {job}", flush=True)

        entry: dict = {}
        while True:
            time.sleep(2)
            history = get_json(f"/history/{job}")
            entry = history.get(job, {})
            status = (entry.get("status") or {}).get("status_str")
            if status in ("success", "error"):
                break
            if time.time() - started > 900:
                print(f"{name}: gave up after 15 minutes", flush=True)
                break

        elapsed = time.time() - started
        status = (entry.get("status") or {}).get("status_str")
        print(f"{name}: {status} in {elapsed:.1f}s", flush=True)
        if status != "success":
            for message in (entry.get("status") or {}).get("messages") or []:
                print("   ", message, flush=True)
            continue

        for item in output_files(entry):
            query = urllib.parse.urlencode({
                "filename": item["filename"],
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            })
            data = get_bytes(f"{BASE}/view?{query}")
            target = OUT / f"{name}.mp3"
            target.write_bytes(data)
            print(f"    wrote {target.relative_to(ROOT)} ({len(data)} bytes, {elapsed:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
