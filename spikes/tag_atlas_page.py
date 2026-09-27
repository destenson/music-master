"""Render the atlas into a page you can listen through.

Reads index.json (and fingerprints.json, when it exists) and writes a self-contained index.html
next to the audio. Each bin gets its base clip and then every tag in that bin, so the change is one
click away. The band sparkline is the tag's per-octave change against its base: a way to see roughly
what a tag does before playing it.

    python3 spikes/tag_atlas_page.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "tag-atlas"
BAND_LABELS = ["20-125", "125-250", "250-500", "0.5-1k", "1-2.5k", "2.5-5k", "5-8k", "8-11k"]


def sparkline(bands: list[float]) -> str:
    cells = []
    for value, label in zip(bands, BAND_LABELS):
        # Clip the bar at +/- 6 dB; the sign is what matters, not the exact height.
        height = max(-6.0, min(6.0, value))
        colour = "#4a9" if height >= 0 else "#a66"
        cells.append(
            f'<span class="bar" title="{label}: {value:+.1f} dB" '
            f'style="--h:{abs(height) / 6 * 100:.0f}%;background:{colour};'
            f'{"align-self:flex-start" if height >= 0 else "align-self:flex-end"}"></span>'
        )
    return "".join(cells)


def main() -> int:
    index = json.loads((OUT / "index.json").read_text())
    prints: dict[tuple[str, str], dict] = {}
    fp_path = OUT / "fingerprints.json"
    if fp_path.exists():
        fp = json.loads(fp_path.read_text())
        prints = {(c["bin"], c["option"]): c for c in fp["clips"]}

    by_bin: dict[str, list[dict]] = {}
    for clip in index["clips"]:
        by_bin.setdefault(clip["bin"], []).append(clip)

    base_names = {name for name in index["bases"]}
    rows: list[str] = []
    for bin_id in sorted(by_bin):
        # A bin shares the full bed as its base with bins that are not in the bed; name it once.
        base_name = by_bin[bin_id][0]["base"]
        base = index["bases"].get(base_name, {})
        rows.append(f'<h2>{html.escape(bin_id)} <span class="n">{len(by_bin[bin_id])}</span></h2>')
        if base:
            rows.append(
                f'<div class="row base"><audio preload="none" controls '
                f'src="{html.escape(base["file"])}"></audio>'
                f'<span class="label">base</span>'
                f'<span class="cap">{html.escape(base.get("caption", ""))}</span></div>'
            )
        for clip in by_bin[bin_id]:
            f = prints.get((clip["bin"], clip["option"]), {})
            vs = f.get("vs_base") or {}
            spark = sparkline(vs["band_db"]) if vs.get("band_db") else ""
            metrics = (
                f'<span class="m">Δ{vs.get("mel_abs_db", 0):+.1f} dB</span>'
                f'<span class="m">corr {vs.get("mel_correlation", 0):.2f}</span>'
                f'<span class="m">{f.get("integrated_lufs", 0):.1f} LUFS</span>'
                f'<span class="m">{f.get("onset_count", 0)} onsets</span>'
                if f else ""
            )
            rows.append(
                f'<div class="row"><audio preload="none" controls '
                f'src="{html.escape(clip["file"])}"></audio>'
                f'<span class="label">{html.escape(clip["label"])}</span>'
                f'<span class="spark">{spark}</span>{metrics}'
                f'<details><summary>caption</summary><code>{html.escape(clip["caption"])}</code></details></div>'
            )

    page = f"""<!doctype html>
<meta charset="utf-8">
<title>Tag atlas</title>
<style>
  body {{ background:#15171c; color:#d7dae0; font:13px/1.5 system-ui, sans-serif; margin:0; padding:24px; }}
  h1 {{ font-size:16px; margin:0 0 4px; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:#8b93a1;
        margin:26px 0 6px; border-bottom:1px solid #2a2e37; padding-bottom:4px; }}
  .n {{ color:#5d6472; font-weight:400; }}
  .row {{ display:grid; grid-template-columns:270px 190px 90px 1fr; gap:10px; align-items:center;
          padding:3px 0; border-top:1px solid #23262e; }}
  .row.base {{ background:#1b1e25; }}
  audio {{ width:260px; height:30px; }}
  .label {{ color:#e8eaee; }}
  .base .label {{ color:#8b93a1; font-style:italic; }}
  .spark {{ display:flex; flex-direction:column; height:18px; width:84px; gap:1px; }}
  .bar {{ width:100%; display:block; }}
  .m {{ color:#8b93a1; font-variant-numeric:tabular-nums; font-size:11px; }}
  .cap {{ color:#6f7787; font-size:11px; }}
  code {{ color:#9fb4d0; font-size:11px; }}
  details {{ grid-column:1 / -1; }}
  summary {{ color:#5d6472; cursor:pointer; font-size:11px; }}
</style>
<h1>Tag atlas</h1>
<p class="cap">{len(index['clips'])} clips · {index['settings']['seconds']}s · seed {index['settings']['seed']} ·
steps {index['settings']['steps']} · every clip is the shared bed plus one tag</p>
{''.join(rows)}
"""
    (OUT / "index.html").write_text(page)
    print(f"wrote index.html with {len(index['clips'])} clips across {len(by_bin)} bins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
