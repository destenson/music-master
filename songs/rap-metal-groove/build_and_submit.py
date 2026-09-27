"""Build the prompt artifacts for this song and submit them to ComfyUI.

Everything here is a pure function of files on disk: `selections.json` renders the caption, the
template plus tempo renders the timeline, and `lyrics.md` is the words. The artifacts themselves are
built by `musicmaster.prompt`, so what is left here is the part that knows where the song lives — it
reads the files, writes `composition.json`, `prompt.json` and `workflow.json` back, and optionally
POSTs the workflow to a running ComfyUI and waits for the render.

    python3 songs/nu-metal-rap-rock/build_and_submit.py
    python3 songs/nu-metal-rap-rock/build_and_submit.py --submit --host 127.0.0.1:8288
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from musicmaster import prompt as P  # noqa: E402
from musicmaster import render as R  # noqa: E402
from musicmaster import timeline as T  # noqa: E402

SONG_ID = "nu-metal-rap-rock"
TEMPLATE_ID = "nu_metal_rap_rock"
BPM = 120
SEED = 1204  # fixed so the render is re-derivable; see the target block
# A song directory may carry song.json to set these, so one runner serves every song.
_cfg_path = HERE / "song.json"
_cfg = json.loads(_cfg_path.read_text()) if _cfg_path.exists() else {}
SONG_ID = _cfg.get("song_id", SONG_ID)
TEMPLATE_ID = _cfg.get("template_id", TEMPLATE_ID)
BPM = _cfg.get("bpm", BPM)
SEED = _cfg.get("seed", SEED)


def build():
    """Read this song's files, build the artifacts through the package, and write them back."""
    selections = json.loads((HERE / "selections.json").read_text())["selections"]
    lyrics_text = (HERE / "lyrics.md").read_text()
    brief_text = (HERE / "brief.md").read_text()

    artifacts = P.build(
        {
            "song_id": SONG_ID,
            "template_id": TEMPLATE_ID,
            "bpm": BPM,
            "seed": SEED,
            "selections": selections,
            "lyrics": lyrics_text,
            "brief": brief_text,
            "artist_references": _cfg.get("artist_references", []),
            "vocabulary_path": ROOT / "vocabulary" / "tag-bins.json",
            "vocabulary": R.load_vocabulary(),
            "section_tags": T.load(T.SECTION_TAGS_PATH),
            "templates_doc": T.load(T.TEMPLATES_PATH),
        }
    )

    # The composition is written first because the prompt pins its hash, and P.serialise is the one
    # function both the hash and the file go through, so they cannot disagree.
    (HERE / "composition.json").write_text(P.serialise(artifacts["composition"]))
    (HERE / "prompt.json").write_text(P.serialise(artifacts["prompt"]))
    (HERE / "workflow.json").write_text(P.serialise(artifacts["workflow"]))

    return (
        artifacts["prompt"],
        artifacts["rendered"],
        artifacts["plan"],
        artifacts["coherence"],
        artifacts["prompt_sha256"],
    )


def submit(host: str, workflow: dict, client_id: str, timeout_s: int) -> list[str]:
    """Queue one render and wait for it. Returns the output filenames it produced."""
    base = f"http://{host}"
    body = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{base}/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            queued = json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"ComfyUI rejected the workflow: HTTP {exc.code}\n{detail[:2000]}")
        return []

    prompt_id = queued.get("prompt_id")
    print(f"  queued: prompt_id={prompt_id}")

    started = time.time()
    while time.time() - started < timeout_s:
        time.sleep(4)
        with urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=30) as r:
            history = json.load(r)
        entry = history.get(prompt_id)
        if not entry:
            continue

        status = entry.get("status", {})
        if status.get("status_str") != "success":
            print(f"  status: {status.get('status_str')}")
            for m in status.get("messages", [])[-3:]:
                print("  log:", str(m)[:300])
            return []

        found = []
        for _node_id, out in (entry.get("outputs") or {}).items():
            for _key, value in out.items():
                for item in value if isinstance(value, list) else []:
                    if isinstance(item, dict) and item.get("filename"):
                        found.append(f"{item.get('subfolder')}/{item.get('filename')}")
                        print(f"  output: {found[-1]}  ({int(time.time() - started)}s)")
        return found

    print(f"  timed out after {timeout_s}s")
    return []


def render_takes(host: str, takes: int, base_seed: int, timeout_s: int,
                 workflow: dict, prompt: dict) -> int:
    """Render N takes with distinct seeds.

    Separate submissions rather than one batch: a batch of four multiplies peak VRAM on a card
    that may not have it, and separate runs give each take its own recorded seed, so a take that
    is chosen can be reproduced on its own.
    """
    for i in range(takes):
        seed = base_seed + i * 7919
        wf = json.loads(json.dumps(workflow))
        wf["4"]["inputs"]["seed"] = seed
        wf["8"]["inputs"]["seed"] = seed
        print(f"take {i + 1}/{takes}: seed {seed}")
        outputs = submit(host, wf, f"music-master-{SONG_ID}-{seed}", timeout_s)
        if not outputs:
            print("  no output; stopping")
            return 1
        src = Path("/home/dennis/src/comfyanonymous--ComfyUI/output") / outputs[0]
        # Name by seed, not by take index: two batches with the same index collided and the
        # first batch was overwritten. A take's seed is its identity.
        dst = HERE / f"take_s{seed}.mp3"
        if src.exists():
            dst.write_bytes(src.read_bytes())
            print(f"  saved {dst.name}")
        record = prompt.copy()
        record["target"] = {**prompt["target"], "seed": seed, "candidate_index": i}
        (HERE / f"prompt_s{seed}.json").write_text(json.dumps(record, indent=2) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--takes", type=int, default=1)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--host", default="127.0.0.1:8288")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    prompt, rendered, plan, coherence, prompt_hash = build()
    print(f"caption ({len(rendered['tags'])} tags):\n  {rendered['string']}")
    if rendered["omitted"]:
        print(f"  dropped over budget: {rendered['omitted']}")
    for problem in coherence:
        print(f"  coherence: {problem}")
    tot = plan["totals"]
    print(f"\ntimeline: {T.mmss(tot['total_s'])} total at {BPM} BPM"
          f"  |  {T.mmss(tot['vocal_s'])} sung, {T.mmss(tot['instrumental_s'])} instrumental"
          f"  |  delivery '{plan['profile_label']}'")
    print(f"prompt_sha256: {prompt_hash}")
    print("wrote: prompt.json, workflow.json, composition.json")

    if args.submit:
        return render_takes(args.host, args.takes, args.seed, args.timeout,
                            json.loads((HERE / "workflow.json").read_text()), prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
