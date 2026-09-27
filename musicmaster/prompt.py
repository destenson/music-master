"""The canonical prompt, and the graph it renders to.

`prompt.json` is the artifact of record: the audio is a build product derived from it, so this is
where a song's intent becomes a request a generator can be handed. It is a pure function of the
selections, the lyrics, the brief and the target — no filesystem beyond the vocabulary it hashes, no
network, no clock — which is what lets the CLI write it and the browser build it from the same code.

Three hashes come out, and they are not the same thing:

* `lyrics.sha256` and `provenance.spec_sha256` are over the *files* the prompt references;
* `form.composition_sha256` is over the serialised composition, so the prompt pins the arrangement;
* `prompt_sha256` is over the canonical form of the prompt itself — keys sorted, no insignificant
  whitespace — which is what a manifest records so a render can be traced back to its inputs.

`build_workflow` is deliberately separate from `build_prompt`: the prompt is model-agnostic and the
graph is one target's rendering of it, which is the split that lets a second generator be added
without touching the artifact of record.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# The weights this graph loads. A target swap is a change here, not in the prompt.
GRAPH = {
    "unet": "acestep_v1.5_xl_turbo_bf16.safetensors",
    "clip_small": "qwen_0.6b_ace15.safetensors",
    "clip_large": "qwen_4b_ace15.safetensors",
    "vae": "ace_1.5_vae.safetensors",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical(obj) -> str:
    """The canonical form the prompt hash is taken over: sorted keys, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def serialise(obj) -> str:
    """The on-disk form of an artifact. One function, so a hash and a file cannot disagree."""
    return json.dumps(obj, indent=2) + "\n"


def prompt_sha256(prompt: dict) -> str:
    return sha256_bytes(canonical(prompt).encode())


def build_composition(
    *,
    song_id: str,
    template_id: str,
    bpm: float,
    profile: dict,
    plan: dict,
) -> dict:
    """The instantiated plan. The prompt references its hash, so it is built first."""
    return {
        "song_id": song_id,
        "template_id": template_id,
        "bpm": bpm,
        "profile": profile["id"],
        "band": list(profile["band"]),
        "totals": plan["totals"],
        "sections": plan["rows"],
    }


def build_prompt(
    *,
    song_id: str,
    bpm: float,
    seed: int,
    selections: dict,
    lyrics: str,
    brief: str,
    artist_references: list,
    vocabulary: dict,
    vocabulary_path,
    composition_sha256: str,
    rendered: dict,
    plan: dict,
    timesignature: str = "4",
    language: str = "en",
) -> dict:
    """The canonical, model-agnostic request."""
    key = selections.get("key_mode") or {}
    metadata = {
        "bpm": bpm,
        "key": key.get("key"),
        "mode": key.get("mode"),
        "timesignature": timesignature,
        "duration_s": round(plan["totals"]["total_s"], 1),
        "language": language,
    }

    return {
        "prompt_version": "1",
        "song_id": song_id,
        "seed": seed,
        "style": {
            "vocabulary_ref": {
                "path": "vocabulary/tag-bins.json",
                "version": vocabulary["vocabulary_version"],
                "sha256": sha256_file(vocabulary_path),
            },
            "selections": selections,
            "rendered_tags": rendered["tags"],
            "rendered_string": rendered["string"],
            "omitted_tags": rendered["omitted"],
            "free_text": "",
        },
        "metadata": metadata,
        "form": {
            "composition_ref": f"songs/{song_id}/composition.json",
            "composition_sha256": composition_sha256,
            "sections": [
                {"name": row["role"], "bars": row["bars"], "label": row["label"]}
                for row in plan["rows"]
            ],
        },
        "lyrics": {
            "ref": f"songs/{song_id}/lyrics.md",
            "sha256": sha256_bytes(lyrics.encode()),
            "section_tags": True,
        },
        "negative": {
            # Negative-polarity bins never become tags; they land here. On a target with no
            # negative-caption input this is a record of intent rather than an instruction, which is
            # why the corresponding positives are simply never selected.
            "style": rendered.get("negatives", []),
            "artist_references": list(artist_references),
        },
        "target": {
            "generator_id": "ace_step_1_5_xl_turbo",
            "runner": "comfyui",
            "graph_ref": f"songs/{song_id}/workflow.json",
            "sampler": {
                "steps": 8,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model_sampling_shift": 3.0,
            },
            "lm": {
                "generate_audio_codes": True,
                "cfg_scale": 2.0,
                "temperature": 0.85,
                "top_p": 0.9,
                "top_k": 0,
                "min_p": 0.0,
            },
            "seed": seed,
            "batch_size": 1,
            "candidate_index": 0,
        },
        "notes": [
            {
                "field": "style.selections",
                "why": "Influence expressed as descriptive characteristics rather than a band "
                       "name. Genre fusion, instrumentation and vocal split do the work a name "
                       "cannot.",
            },
            {
                "field": "metadata.bpm",
                "why": f"{bpm:g} BPM, mid-tempo for the genre; carried in metadata, never in the "
                       "caption.",
            },
            {
                "field": "target.seed",
                "why": "Fixed so the render is re-derivable. With lm.temperature > 0 the LM's "
                       "audio-code sampling adds randomness, so this is re-derivable and diffable "
                       "rather than bit-identical.",
            },
            {
                "field": "negative.artist_references",
                "why": "Recorded so the compliance report can prove what was excluded, and so the "
                       "policy check has something to verify against.",
            },
        ],
        "provenance": {
            "spec_sha256": sha256_bytes(brief.encode()),
            "builder": f"songs/{song_id}/build_and_submit.py",
        },
    }


def build_workflow(prompt: dict, lyrics: str, duration_s: float, graph: dict | None = None) -> dict:
    """Render the canonical prompt into an ACE-Step 1.5 graph in ComfyUI API format."""
    weights = graph or GRAPH
    md, style, target = prompt["metadata"], prompt["style"], prompt["target"]
    keyscale = f"{md['key']} {md['mode']}" if md.get("key") else "D minor"
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": weights["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": weights["clip_small"],
                         "clip_name2": weights["clip_large"], "type": "ace"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": weights["vae"]}},
        "4": {"class_type": "TextEncodeAceStepAudio1.5",
              "inputs": {
                  "clip": ["2", 0],
                  "tags": style["rendered_string"],
                  "lyrics": lyrics,
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
                          "filename_prefix": f"audio/{prompt['song_id']}", "quality": "V0"}},
    }


def build(doc: dict) -> dict:
    """Everything the render path needs, from one input document.

    `doc` carries the song's own inputs — `song_id`, `template_id`, `bpm`, `seed`, `selections`,
    `lyrics`, `brief`, `artist_references`, `vocabulary_path` — and the loaded vocabulary, section
    tags, templates and rates. Nothing here reads a song file: the caller decides where the song
    lives, which is what lets the CLI use a directory and the browser use what it already fetched.
    """
    from . import render as R
    from . import timeline as T

    vocabulary = doc["vocabulary"]
    section_tags = doc["section_tags"]
    templates_doc = doc["templates_doc"]
    rates = doc.get("rates") or T.load_delivery_rates()
    selections = doc["selections"]
    # Left exactly as given: a song declares 92, and 92.0 is not the same artifact byte-for-byte.
    bpm = doc["bpm"]
    template_id = doc["template_id"]

    rendered = R.render(vocabulary, selections)
    coherence = R.coherence_check(vocabulary, selections)

    template = next(t for t in templates_doc["templates"] if t["id"] == template_id)
    profile = T.profile_for_vocals(selections, rates)
    plan = T.build_timeline(template, bpm, section_tags, profile, templates_doc)

    composition = build_composition(
        song_id=doc["song_id"], template_id=template_id, bpm=bpm, profile=profile, plan=plan
    )
    prompt = build_prompt(
        song_id=doc["song_id"],
        bpm=bpm,
        seed=int(doc["seed"]),
        selections=selections,
        lyrics=doc["lyrics"],
        brief=doc["brief"],
        artist_references=doc.get("artist_references") or [],
        vocabulary=vocabulary,
        vocabulary_path=doc["vocabulary_path"],
        composition_sha256=sha256_bytes(serialise(composition).encode()),
        rendered=rendered,
        plan=plan,
        timesignature=doc.get("timesignature", "4"),
        language=doc.get("language", "en"),
    )
    workflow = build_workflow(
        prompt, doc["lyrics"], prompt["metadata"]["duration_s"], graph=doc.get("graph")
    )

    return {
        "prompt": prompt,
        "composition": composition,
        "workflow": workflow,
        "plan": plan,
        "rendered": rendered,
        "coherence": coherence,
        "prompt_sha256": prompt_sha256(prompt),
    }
