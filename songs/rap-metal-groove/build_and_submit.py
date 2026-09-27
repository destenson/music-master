"""Build the prompt artifacts for this song and submit them to ComfyUI.

Everything here is a pure function of files on disk: `selections.json` renders the caption,
the template plus tempo renders the timeline, and `lyrics.md` is the words. The script writes
`prompt.json` (the canonical artifact of record) and `workflow.json` (the target-specific
rendering for ACE-Step 1.5), then optionally POSTs the workflow to a running ComfyUI and waits
for the render.

    python3 songs/nu-metal-rap-rock/build_and_submit.py
    python3 songs/nu-metal-rap-rock/build_and_submit.py --submit --host 127.0.0.1:8288
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "vocabulary"))

import render_tags as RT  # noqa: E402
import timeline as T  # noqa: E402

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

GRAPH = {
    "unet": "acestep_v1.5_xl_turbo_bf16.safetensors",
    "clip_small": "qwen_0.6b_ace15.safetensors",
    "clip_large": "qwen_4b_ace15.safetensors",
    "vae": "ace_1.5_vae.safetensors",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build():
    selections = json.loads((HERE / "selections.json").read_text())["selections"]
    lyrics_text = (HERE / "lyrics.md").read_text()
    lyrics_sha = sha256_bytes(lyrics_text.encode())

    vocab = RT.load_vocabulary()
    rendered = RT.render(vocab, selections)
    coherence = RT.coherence_check(vocab, selections)

    templates_doc = T.load(T.TEMPLATES_PATH)
    template = next(t for t in templates_doc["templates"] if t["id"] == TEMPLATE_ID)
    rates = T.load_delivery_rates()
    profile = T.profile_for_vocals(selections, rates)
    section_tags = T.load(T.SECTION_TAGS_PATH)
    plan = T.build_timeline(template, BPM, section_tags, profile, templates_doc)

    duration_s = round(plan["totals"]["total_s"], 1)
    key = selections.get("key_mode", {})
    metadata = {
        "bpm": BPM,
        "key": key.get("key"),
        "mode": key.get("mode"),
        "timesignature": "4",
        "duration_s": duration_s,
        "language": "en",
    }

    prompt = {
        "prompt_version": "1",
        "song_id": SONG_ID,
        "seed": SEED,
        "style": {
            "vocabulary_ref": {
                "path": "vocabulary/tag-bins.json",
                "version": vocab["vocabulary_version"],
                "sha256": sha256_file(ROOT / "vocabulary" / "tag-bins.json"),
            },
            "selections": selections,
            "rendered_tags": rendered["tags"],
            "rendered_string": rendered["string"],
            "omitted_tags": rendered["omitted"],
            "free_text": "",
        },
        "metadata": metadata,
        "form": {
            "composition_ref": f"songs/{SONG_ID}/composition.json",
            "composition_sha256": "",
            "sections": [
                {"name": r["role"], "bars": r["bars"], "label": r["label"]}
                for r in plan["rows"]
            ],
        },
        "lyrics": {"ref": f"songs/{SONG_ID}/lyrics.md", "sha256": lyrics_sha,
                   "section_tags": True},
        "negative": {
            # Negative-polarity bins never become tags; they land here. On a target with no
            # negative-caption input this is a record of intent rather than an instruction, which
            # is why the corresponding positives are simply never selected.
            "style": rendered.get("negatives", []),
            "artist_references": _cfg.get("artist_references", ["Linkin Park"]),
        },
        "target": {
            "generator_id": "ace_step_1_5_xl_turbo",
            "runner": "comfyui",
            "graph_ref": "songs/%s/workflow.json" % SONG_ID,
            "sampler": {"steps": 8, "cfg": 1.0, "sampler_name": "euler",
                        "scheduler": "simple", "denoise": 1.0,
                        "model_sampling_shift": 3.0},
            "lm": {"generate_audio_codes": True, "cfg_scale": 2.0,
                   "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0},
            "seed": SEED,
            "batch_size": 1,
            "candidate_index": 0,
        },
        "notes": [
            {"field": "style.selections", "why":
             "Influence expressed as descriptive characteristics rather than a band name. "
             "Genre fusion, instrumentation and vocal split do the work a name cannot."},
            {"field": "metadata.bpm", "why":
             "120 BPM, mid-tempo for the genre; carried in metadata, never in the caption."},
            {"field": "target.seed", "why":
             "Fixed so the render is re-derivable. With lm.temperature > 0 the LM's audio-code "
             "sampling adds randomness, so this is re-derivable and diffable rather than "
             "bit-identical."},
            {"field": "negative.artist_references", "why":
             "Recorded so the compliance report can prove what was excluded, and so the policy "
             "check has something to verify against."},
        ],
        "provenance": {
            "spec_sha256": sha256_file(HERE / "brief.md"),
            "builder": "songs/%s/build_and_submit.py" % SONG_ID,
        },
    }

    # composition.json is the instantiated plan; the prompt references its hash.
    composition = {
        "song_id": SONG_ID,
        "template_id": TEMPLATE_ID,
        "bpm": BPM,
        "profile": profile["id"],
        "band": list(profile["band"]),
        "totals": plan["totals"],
        "sections": plan["rows"],
    }
    composition_path = HERE / "composition.json"
    composition_path.write_text(json.dumps(composition, indent=2) + "\n")
    prompt["form"]["composition_sha256"] = sha256_file(composition_path)

    workflow = build_workflow(prompt, lyrics_text, duration_s)
    (HERE / "prompt.json").write_text(json.dumps(prompt, indent=2) + "\n")
    (HERE / "workflow.json").write_text(json.dumps(workflow, indent=2) + "\n")

    prompt_hash = sha256_bytes(canonical(prompt).encode())
    return prompt, rendered, plan, coherence, prompt_hash


def build_workflow(prompt: dict, lyrics_text: str, duration_s: float) -> dict:
    """Render the canonical prompt into an ACE-Step 1.5 graph in ComfyUI API format."""
    md, style, target = prompt["metadata"], prompt["style"], prompt["target"]
    keyscale = f"{md['key']} {md['mode']}" if md.get("key") else "D minor"
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": GRAPH["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": GRAPH["clip_small"],
                         "clip_name2": GRAPH["clip_large"], "type": "ace"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": GRAPH["vae"]}},
        "4": {"class_type": "TextEncodeAceStepAudio1.5",
              "inputs": {
                  "clip": ["2", 0],
                  "tags": style["rendered_string"],
                  "lyrics": lyrics_text,
                  "seed": target["seed"],
                  "bpm": md["bpm"],
                  "duration": duration_s,
                  "timesignature": md["timesignature"],
                  "language": md["language"],
                  "keyscale": keyscale,
                  "generate_audio_codes": target["lm"]["generate_audio_codes"],
                  "cfg_scale": target["lm"]["cfg_scale"],
                  "temperature": target["lm"]["temperature"],
                  "top_p": target["lm"]["top_p"],
                  "top_k": target["lm"]["top_k"],
                  "min_p": target["lm"]["min_p"],
              }},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyAceStep1.5LatentAudio",
              "inputs": {"seconds": duration_s, "batch_size": target["batch_size"]}},
        "7": {"class_type": "ModelSamplingAuraFlow",
              "inputs": {"model": ["1", 0], "shift": target["sampler"]["model_sampling_shift"]}},
        "8": {"class_type": "KSampler",
              "inputs": {
                  "model": ["7", 0], "seed": target["seed"],
                  "steps": target["sampler"]["steps"], "cfg": target["sampler"]["cfg"],
                  "sampler_name": target["sampler"]["sampler_name"],
                  "scheduler": target["sampler"]["scheduler"],
                  "positive": ["4", 0], "negative": ["5", 0],
                  "latent_image": ["6", 0], "denoise": target["sampler"]["denoise"],
              }},
        "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveAudioMP3",
               "inputs": {"audio": ["9", 0],
                          "filename_prefix": f"audio/{SONG_ID}", "quality": "V0"}},
    }


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
