"""Live preview: render the whole song coarsely, or an A/B of one tag change.

The atlas approach was backwards. A preview is generated on demand against the caption you
actually have, played immediately, and never stored -- nothing goes stale, and there is no library
of ten thousand files to browse.

    python3 vocabulary/preview.py --song=songs/rap-metal-groove
    python3 vocabulary/preview.py --toggle=drums:taiko
    python3 vocabulary/preview.py --toggle=harmony:distorted_guitar --steps=1

It runs the **full song length** and cuts the sampler steps instead. A short clip is not the
opening of the full render -- the model arranges to fit whatever length it is handed -- so only a
full-length render shows what a tag does to the real arrangement. At two steps the arrangement and
the seed match the full render and the audio is coarse; that is the trade a preview wants.

Both captions go in as a single batched submission -- base first, then the variant -- so they share
one language-model pass and one sampler pass and differ only by the tag. Output lands under
previews/ (gitignored), never in ComfyUI's own output tree.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from musicmaster import prompt as prompt_build  # noqa: E402
from musicmaster import render, timeline  # noqa: E402

DEFAULT_SONG = ROOT / "songs" / "rap-metal-groove"


def load_document(song: Path) -> dict:
    """Everything prompt.build needs, read from the song directory."""
    config = json.loads((song / "song.json").read_text())
    return {
        "song_id": config["song_id"],
        "template_id": config["template_id"],
        "bpm": config["bpm"],
        "seed": config["seed"],
        "selections": json.loads((song / "selections.json").read_text())["selections"],
        "lyrics": (song / "lyrics.md").read_text(),
        "brief": (song / "brief.md").read_text(),
        "artist_references": config.get("artist_references", []),
        "vocabulary_path": ROOT / "vocabulary" / "tag-bins.json",
        "vocabulary": render.load_vocabulary(),
        "section_tags": timeline.load(timeline.SECTION_TAGS_PATH),
        "templates_doc": timeline.load(timeline.TEMPLATES_PATH),
    }


def toggled(selections: dict, toggles: list[str]) -> dict:
    """A copy of the selections with each bin:option flipped."""
    variant = json.loads(json.dumps(selections))
    for toggle in toggles:
        bin_id, _, option = toggle.partition(":")
        if not option:
            raise SystemExit(f"--toggle needs bin:option, got {toggle!r}")
        entry = variant.setdefault(bin_id, {"options": []})
        options = entry.setdefault("options", [])
        if option in options:
            options.remove(option)
        else:
            options.append(option)
    return variant


def submit(base_url: str, workflow: dict, client: str = "music-master-preview") -> str:
    request = urllib.request.Request(
        f"{base_url}/prompt", data=json.dumps({"prompt": workflow, "client_id": client}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["prompt_id"]


def wait_for(base_url: str, job: str, timeout: float = 600.0) -> dict:
    started = time.time()
    while True:
        time.sleep(0.25)
        with urllib.request.urlopen(f"{base_url}/history/{job}", timeout=60) as response:
            entry = json.loads(response.read()).get(job, {})
        status = (entry.get("status") or {}).get("status_str")
        if status in ("success", "error"):
            if status != "success":
                raise SystemExit(f"the render failed: {status}")
            messages = {m[0]: m[1].get("timestamp")
                        for m in (entry.get("status") or {}).get("messages") or []
                        if isinstance(m, list)}
            entry["_seconds"] = (messages.get("execution_success", 0)
                                 - messages.get("execution_start", 0)) / 1000
            return entry
        if time.time() - started > timeout:
            raise SystemExit("gave up waiting for the preview")


def output_entries(entry: dict) -> list[dict]:
    files: list[dict] = []
    for node in (entry.get("outputs") or {}).values():
        for value in node.values():
            if isinstance(value, list):
                files += [i for i in value if isinstance(i, dict) and "filename" in i]
    return files


def view_url(base_url: str, item: dict) -> str:
    query = urllib.parse.urlencode({"filename": item["filename"],
                                    "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output")})
    return f"{base_url}/view?{query}"


def stream(base_url: str, item: dict) -> None:
    """Fetch the clip and pipe it to the player, so nothing is written anywhere."""
    player = shutil.which("ffplay")
    with urllib.request.urlopen(view_url(base_url, item), timeout=180) as response:
        data = response.read()
    if player is None:
        print(f"  (no ffplay; {len(data)} bytes not played)")
        return
    subprocess.run([player, "-nodisp", "-autoexit", "-loglevel", "error", "-i", "pipe:0"],
                   input=data, check=False)


def fetch(base_url: str, entry: dict, target_dir: Path, names: list[str]) -> list[Path]:
    saved: list[Path] = []
    for index, item in enumerate(output_entries(entry)):
        suffix = Path(item["filename"]).suffix
        label = names[index] if index < len(names) else f"row{index}"
        target = target_dir / f"{label}{suffix}"
        with urllib.request.urlopen(view_url(base_url, item), timeout=180) as response:
            target.write_bytes(response.read())
        saved.append(target)
    return saved


def play(path: Path) -> None:
    player = shutil.which("ffplay")
    if player is None:
        print(f"  (no ffplay; play {path} yourself)")
        return
    subprocess.run([player, "-nodisp", "-autoexit", "-loglevel", "error", str(path)], check=False)


def variants_for(doc: dict, args) -> list[tuple[str, str]]:
    """Every caption to preview, as (name, caption), base first.

    The language model's cost is per pass, not per caption -- a full-length song is 940 sequential
    tokens whether two captions ride along or twelve -- so previewing several at once is nearly
    free per caption. That is what --variant and --bin exist for.
    """
    selections = doc["selections"]
    vocab = doc["vocabulary"]
    base = render.render(vocab, selections)["string"]
    out: list[tuple[str, str]] = [("base", base)]

    for flag in args.variant:
        bin_id, _, option = flag.partition(":")
        out.append((f"{bin_id}-{option}",
                    render.render(vocab, toggled(selections, [flag]))["string"]))

    if args.bin:
        meta = next((b for b in vocab["bins"] if b["id"] == args.bin), None)
        if meta is None:
            raise SystemExit(f"no bin {args.bin!r}")
        for option in (meta.get("options") or [])[: args.max]:
            flag = f"{args.bin}:{option['id']}"
            out.append((option["id"], render.render(vocab, toggled(selections, [flag]))["string"]))

    if args.toggle:
        out.append(("variant", render.render(vocab, toggled(selections, args.toggle))["string"]))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Live preview of a caption, or an A/B of a tag.")
    parser.add_argument("--song", default=str(DEFAULT_SONG))
    parser.add_argument("--toggle", action="append", default=[],
                        help="bin:option, applied cumulatively to one variant; repeatable")
    parser.add_argument("--variant", action="append", default=[],
                        help="bin:option, each its own caption in the same pass; repeatable")
    parser.add_argument("--bin", default=None,
                        help="preview one caption per option in this bin, in one pass")
    parser.add_argument("--max", type=int, default=12, help="cap --bin to this many options")
    parser.add_argument("--seconds", type=float, default=None,
                        help="override the song's own length; default is the whole song")
    parser.add_argument("--steps", type=int, default=prompt_build.PREVIEW_STEPS,
                        help="sampler steps; 1-2 for a coarse preview of the full arrangement")
    parser.add_argument("--comfy", default="http://127.0.0.1:8288")
    parser.add_argument("--out", default=str(ROOT / "previews"))
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--stream", action="store_true",
                        help="pipe the audio straight to the player and write nothing at all")
    args = parser.parse_args(argv[1:])

    song = Path(args.song)
    doc = load_document(song)
    built = prompt_build.build(doc)

    entries = variants_for(doc, args)
    captions = [text for _, text in entries]
    names = [name for name, _ in entries]
    print(f"previewing {len(captions)} caption(s): {', '.join(names[:8])}"
          f"{' ...' if len(names) > 8 else ''}")
    for name, text in entries[:3]:
        print(f"{name:>7}: {text}")
    if len(entries) > 3:
        print(f"  ... and {len(entries) - 3} more")

    target_dir = Path(args.out) / doc["song_id"]
    seconds = args.seconds if args.seconds is not None else built["prompt"]["metadata"]["duration_s"]
    print(f"preview: {seconds:g}s of audio, {args.steps} sampler step(s)")
    workflow = prompt_build.build_preview_workflow(
        built["prompt"], doc["lyrics"], captions, seconds=args.seconds, steps=args.steps)

    started = time.time()
    entry = wait_for(args.comfy, submit(args.comfy, workflow))
    per = entry["_seconds"] / max(len(captions), 1)
    print(f"rendered {len(captions)} clip(s) in {entry['_seconds']:.1f}s "
          f"({per:.1f}s each, wall {time.time() - started:.1f}s)")

    if args.stream:
        for label, item in zip(names, output_entries(entry)):
            print(f"streaming {label}")
            stream(args.comfy, item)
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    saved = fetch(args.comfy, entry, target_dir, names)
    print(f"  -> {target_dir}")
    if not args.no_play:
        for label, path in zip(names, saved):
            print(f"playing {label}")
            play(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
