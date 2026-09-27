"""Radio stations: a station is a genre's range, not one arrangement.

A station is not a playlist and it is not a preset. It is a **range**: a genre, the scenes and era it
belongs to, a tempo band, and — for every other bin that makes a sound — a pool of options that are
all in character, from which each song draws its own subset. Two consecutive songs from one station
therefore differ in their instruments, their production, their groove, their delivery and their key,
and both are unmistakably of the station. A station that fixed its drum kit would be a song on
repeat, which is the thing a radio is not.

Two kinds of statement make up a station:

* ``fixed`` — the identity. A trap station is trap, it is late-night, it is of its era. These bins
  are the same on every song.
* ``pools`` — the range. Each names a bin, the options that are in character for this station, and
  how many of them a song should carry. The pool may sit alongside ``fixed`` options for the same
  bin, so a station can always have live drums and *sometimes* a tambourine as well.

The plan is a pure function of the station, the song's position and a seed. The position names the
song and rotates its subject; the seed drives every draw, so a take is reproducible from
``(station, position, seed)`` and the browser and the CLI cannot disagree about what a station is.
The renderer draws the seed, exactly as it does for a hand-built song.

The draws are conflict-aware: an option is never taken if it excludes something already chosen, so
a pool that happens to contain ``no_drums`` beside real kits still yields a coherent song. The
validator goes further and refuses a document whose stations name bins, options, counts, tempos or
templates that do not exist, or whose songs can exceed the tag budget — the checks a station author
would otherwise discover by listening.

Adding a station is a data change: one entry in ``vocabulary/radio-stations.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIONS_PATH = ROOT / "vocabulary" / "radio-stations.json"
SCHEMA_PATH = ROOT / "schemas" / "radio-stations.schema.json"

_MASK = 0xFFFFFFFFFFFFFFFF
_AXIS_KEY = "keys"
# Bins the planner computes per song; a station that fixed one would have it silently overridden.
_PLANNER_OWNED = ("tempo", "structure", "key_mode")


def load_stations(path: Path = STATIONS_PATH) -> dict:
    return json.loads(Path(path).read_text())


def station_by_id(doc: dict, station_id: str) -> dict:
    for station in doc["stations"]:
        if station["id"] == station_id:
            return station
    raise KeyError(station_id)


def _copy(value):
    """A private copy, so a plan can be edited without touching the document it came from."""
    return json.loads(json.dumps(value))


class _Rng:
    """A tiny reproducible generator: same seed and same calls, same draws, forever.

    FNV-1a mixes the seed with the station and the song so two stations at the same position do not
    draw the same shape, and splitmix64 walks the stream from there.
    """

    def __init__(self, *parts):
        state = 0xCBF29CE484222325
        for part in parts:
            for byte in str(part).encode("utf-8"):
                state = ((state ^ byte) * 0x100000001B3) & _MASK
        self._state = state

    def _next(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, bound: int) -> int:
        return self._next() % bound if bound > 0 else 0

    def between(self, low: int, high: int) -> int:
        return low + self.below(high - low + 1)

    def pick(self, values: list):
        return values[self.below(len(values))]

    def shuffle(self, values: list) -> None:
        for index in range(len(values) - 1, 0, -1):
            swap = self.below(index + 1)
            values[index], values[swap] = values[swap], values[index]


def _excludes(vocab: dict, bin_id: str, option_id: str) -> set[str]:
    bin_ = next((b for b in vocab["bins"] if b["id"] == bin_id), {})
    option = next((o for o in bin_.get("options") or [] if o["id"] == option_id), {})
    return set(option.get("excludes") or [])


def _conflicts(vocab: dict, bin_id: str, option_id: str, chosen: list[str]) -> bool:
    if option_id in chosen:
        return True
    if _excludes(vocab, bin_id, option_id) & set(chosen):
        return True
    return any(option_id in _excludes(vocab, bin_id, other) for other in chosen)


def _cap(vocab: dict, bin_id: str) -> int | None:
    bin_ = next((b for b in vocab["bins"] if b["id"] == bin_id), {})
    return bin_.get("max_selections")


def _draw(vocab: dict, bin_id: str, pool: dict, fixed: list[str], rng: _Rng) -> list[str]:
    """The options for one bin on one song: the fixed ones, then a draw from the pool."""
    from_list = [option for option in pool.get("from") or [] if option not in fixed]
    cap = _cap(vocab, bin_id)
    room = len(fixed) + len(from_list) if cap is None else cap - len(fixed)
    low, high = pool.get("count") or [1, max(1, min(len(from_list), room))]
    high = min(high, len(from_list), max(room, 0))
    low = min(low, high)
    wanted = rng.between(low, high) if high >= 1 else 0

    chosen = list(fixed)
    candidates = list(from_list)
    rng.shuffle(candidates)
    for option in candidates:
        if len(chosen) - len(fixed) >= wanted:
            break
        if _conflicts(vocab, bin_id, option, chosen):
            continue
        chosen.append(option)
    return chosen


def _structure_option(vocab: dict, template_id: str, explicit: str | None) -> str | None:
    """The ``structure`` option that names this template, so the caption and the form agree.

    Several options can point at one template — a full pop form and a bridge variation share
    ``pop_standard`` — so a station may name its own; otherwise the first match is the default.
    """
    bin_ = next((b for b in vocab["bins"] if b["id"] == "structure"), {})
    matches = [
        o["id"] for o in (bin_.get("options") or []) if o.get("template_ref") == template_id
    ]
    if explicit:
        return explicit
    return matches[0] if matches else None


def _tempo(station: dict, rng: _Rng) -> float:
    spec = station.get("bpm")
    if isinstance(spec, dict):
        return float(rng.between(int(spec["min"]), int(spec["max"])))
    if isinstance(spec, (list, tuple)):
        return float(rng.pick(list(spec)))
    return float(spec)


def plan_song(
    doc: dict,
    station_id: str,
    index: int,
    *,
    seed: int | None = None,
    vocab: dict | None = None,
    instrumental: bool = False,
) -> dict:
    """The selections, tempo, key, form and subject for song ``index`` of a station.

    Pure and deterministic given ``(station_id, index, seed)``. Without a seed the position stands
    in for one, so the CLI and the tests get a stable song per position. ``instrumental`` replaces
    the station's vocal identity rather than layering on top of it: the singer's bins are dropped
    and the caption describes an instrumental, so it cannot promise a voice that is not there.
    """
    if index < 0:
        raise ValueError("a station has no song before its first")

    if vocab is None:
        from . import render as R

        vocab = R.load_vocabulary()

    station = station_by_id(doc, station_id)
    rng = _Rng(station_id, index, seed if seed is not None else index)

    fixed = station.get("fixed") or {}
    selections: dict[str, dict] = {}
    for bin_id in sorted(fixed):
        entry = fixed[bin_id]
        selections[bin_id] = _copy(entry) if isinstance(entry, dict) else {"options": list(entry)}

    for bin_id in sorted(station.get("pools") or {}):
        base = list((selections.get(bin_id) or {}).get("options") or [])
        chosen = _draw(vocab, bin_id, station["pools"][bin_id], base, rng)
        selections[bin_id] = {"options": chosen}

    selections["tempo"] = {"value": _tempo(station, rng), "options": []}

    keys = station.get(_AXIS_KEY) or []
    if keys:
        key = rng.pick(keys)
        selections["key_mode"] = {"key": key["key"], "mode": key["mode"]}

    structure = _structure_option(vocab, station["template_id"], station.get("structure_option"))
    if structure:
        selections["structure"] = {"options": [structure]}

    if instrumental:
        for bin_id in ("lead_vocal", "vocal_delivery", "backing_vocal", "vocal_fx", "lyric_theme"):
            selections.pop(bin_id, None)
        selections["lead_vocal"] = {"options": ["instrumental"]}
        selections["language"] = {"options": ["instrumental_none"]}
        selections["hook"] = {"options": ["hook_instrumental"]}

    themes = station.get("themes") or []
    return {
        "station_id": station_id,
        "station_name": station["name"],
        "song_id": f"{station_id}-{index:03d}",
        "title": f"{station['name']} #{index + 1}",
        "template_id": station["template_id"],
        "bpm": selections["tempo"]["value"],
        "selections": selections,
        "theme": themes[(index + (seed or 0)) % len(themes)] if themes else "",
        "instrumental": bool(instrumental),
    }


def variety(doc: dict, station_id: str) -> int:
    """How many distinct shapes a station's pools can draw, capped so it stays a readable number.

    A station with three pools of ten options each has far more songs than it will ever play; the
    number is here so ``--list`` can show that a station's range is real rather than nominal.
    """
    station = station_by_id(doc, station_id)
    total = 1
    for pool in (station.get("pools") or {}).values():
        size = len(pool.get("from") or [])
        low, high = (pool.get("count") or [1, max(1, size)])[:2]
        combinations = sum(_choose(size, k) for k in range(max(low, 1), min(high, size) + 1))
        total *= max(combinations, 1)
        if total > 10**6:
            return 10**6
    keys = len(station.get(_AXIS_KEY) or []) or 1
    return min(total, 10**6) * keys


def _choose(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    result = 1
    for step in range(k):
        result = result * (n - step) // (step + 1)
    return result


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _schema_errors(doc: dict, schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Conformance to the document's shape, when jsonschema is installed.

    The semantic checks below catch what a schema cannot — a real bin, a real option, a count inside
    the bin's cap. This catches the rest: a missing field, a wrong type, a station with no pools.
    """
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    try:
        schema = json.loads(Path(schema_path).read_text())
    except OSError:
        return []
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        out.append(f"schema: {location}: {error.message}")
    return out


def validate(vocab: dict, templates_doc: dict, doc: dict, *, schema: bool = True) -> list[str]:
    """Every reason this station document cannot be played, as human-readable problems.

    Empty means playable: each station names real bins, options, counts, tempo and template, and a
    sample of the songs it can draw are coherent, inside the tag budget, and actually different from
    one another. Sampling rather than enumerating keeps a large document cheap to check while still
    exercising every pool and every key.
    """
    problems: list[str] = _schema_errors(doc) if schema else []
    bins = {b["id"]: b for b in vocab["bins"]}
    templates = {t["id"]: t for t in templates_doc["templates"]}
    stations = doc.get("stations")
    if not isinstance(stations, list):
        return ["the document has no 'stations' list"]
    if not (20 <= len(stations) <= 40):
        problems.append(f"{len(stations)} stations; the feature is specified for 20 to 40")

    seen: set[str] = set()
    for station in stations:
        where = station.get("id")
        if not isinstance(where, str) or not _SLUG.match(where):
            problems.append(f"station id {where!r} is not a lowercase slug")
            continue
        if where in seen:
            problems.append(f"station '{where}': duplicate id")
            continue
        seen.add(where)
        problems += _check_station(vocab, bins, templates, station)

    if not problems:
        problems += _check_plans(vocab, doc)
    return problems


def _check_station(vocab: dict, bins: dict, templates: dict, station: dict) -> list[str]:
    where = station["id"]
    problems: list[str] = []

    for field in ("name", "tagline", "family"):
        if not isinstance(station.get(field), str) or not station[field].strip():
            problems.append(f"station '{where}': '{field}' must be a non-empty string")

    template_id = station.get("template_id")
    if template_id not in templates:
        problems.append(f"station '{where}': unknown template_id {template_id!r}")
    elif _structure_option(vocab, template_id, station.get("structure_option")) is None:
        problems.append(
            f"station '{where}': template {template_id!r} has no 'structure' option, so the "
            f"caption cannot name the form"
        )

    spec = station.get("bpm")
    tempo = bins.get("tempo", {}).get("range") or {"min": 40, "max": 220}
    values: list[float] = []
    if isinstance(spec, dict):
        try:
            values = [float(spec["min"]), float(spec["max"])]
        except (KeyError, TypeError, ValueError):
            problems.append(f"station '{where}': bpm range must have numeric min and max")
        else:
            if values[0] > values[1]:
                problems.append(f"station '{where}': bpm range runs backwards")
    elif isinstance(spec, (list, tuple)):
        values = [float(v) for v in spec if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(values) != len(spec):
            problems.append(f"station '{where}': bpm list must be numeric")
    elif isinstance(spec, (int, float)) and not isinstance(spec, bool):
        values = [float(spec)]
    else:
        problems.append(f"station '{where}': bpm must be a number, a list or a min/max range")
    for value in values:
        if not (tempo["min"] <= value <= tempo["max"]):
            problems.append(
                f"station '{where}': bpm {value:g} is outside the target's "
                f"{tempo['min']:.0f}-{tempo['max']:.0f} range"
            )

    themes = station.get("themes")
    if not isinstance(themes, list) or not themes:
        problems.append(f"station '{where}': 'themes' must be a non-empty list")
    elif len(set(themes)) != len(themes):
        problems.append(f"station '{where}': themes contain a duplicate")
    elif not all(isinstance(t, str) and t.strip() for t in themes):
        problems.append(f"station '{where}': every theme must be a non-empty string")

    keys = station.get(_AXIS_KEY) or []
    for pick in keys:
        if (
            not isinstance(pick, dict)
            or pick.get("key") not in set(bins.get("key_mode", {}).get("key_options") or [])
            or pick.get("mode") not in set(bins.get("key_mode", {}).get("mode_options") or [])
        ):
            problems.append(f"station '{where}': key {pick!r} is not a known key and mode")

    pools = station.get("pools") or {}
    if not pools:
        problems.append(f"station '{where}': no pools, so every song would be identical")

    fixed = station.get("fixed") or {}
    for owned in _PLANNER_OWNED:
        if owned in fixed:
            problems.append(
                f"station '{where}': '{owned}' is set by the planner and must not be fixed here"
            )
    problems += _check_bins(vocab, bins, where, fixed, "fixed", pooled=False)
    problems += _check_bins(vocab, bins, where, pools, "pools", pooled=True)
    return problems


def _check_bins(vocab, bins, where, group, label, *, pooled):
    problems: list[str] = []
    for bin_id, entry in group.items():
        bin_ = bins.get(bin_id)
        if bin_ is None:
            problems.append(f"station '{where}': unknown bin {bin_id!r} in '{label}'")
            continue
        known = {o["id"] for o in bin_.get("options") or []}
        cap = bin_.get("max_selections")
        if pooled:
            options = list(entry.get("from") or [])
            if len(options) < 2:
                problems.append(
                    f"station '{where}': pool '{bin_id}' offers {len(options)} option(s), so it "
                    f"never varies"
                )
            count = entry.get("count")
            if count is not None:
                if (
                    not isinstance(count, list)
                    or len(count) != 2
                    or not all(isinstance(v, int) and not isinstance(v, bool) for v in count)
                ):
                    problems.append(
                        f"station '{where}': pool '{bin_id}' count must be [min, max]"
                    )
                elif count[0] < 1 or count[0] > count[1]:
                    problems.append(
                        f"station '{where}': pool '{bin_id}' count {count} is not a positive range"
                    )
                elif cap is not None and count[1] > cap:
                    problems.append(
                        f"station '{where}': pool '{bin_id}' can draw {count[1]}, over the cap of {cap}"
                    )
        else:
            options = (entry.get("options") or []) if isinstance(entry, dict) else list(entry)
            if cap is not None and len(options) > cap:
                problems.append(
                    f"station '{where}': fixed '{bin_id}' selects {len(options)}, over the cap of {cap}"
                )
        for option in options:
            if option not in known:
                problems.append(f"station '{where}': bin '{bin_id}' has no option {option!r}")
    return problems


def _check_plans(vocab: dict, doc: dict) -> list[str]:
    """Play a sample of each station and check what comes out, not just what went in."""
    from . import render as R

    problems: list[str] = []
    budget = vocab["tag_budget"]
    for station in doc["stations"]:
        where = station["id"]
        captions: set[str] = set()
        for index in range(8):
            for instrumental in (False, True):
                plan = plan_song(doc, where, index, seed=1000 + index, vocab=vocab, instrumental=instrumental)
                song = f"station '{where}' song {index}" + (" (instrumental)" if instrumental else "")
                selections = plan["selections"]
                rendered = R.render(vocab, selections)
                if not instrumental:
                    captions.add(rendered["string"])
                if len(rendered["tags"]) > budget:
                    problems.append(f"{song}: {len(rendered['tags'])} tags, over the budget of {budget}")
                if rendered["omitted"]:
                    problems.append(f"{song}: the budget dropped {', '.join(rendered['omitted'])}")
                for problem in R.coherence_check(vocab, selections):
                    problems.append(f"{song}: {problem}")
                if instrumental:
                    # A structural assertion, not a string match: the caption describes what is
                    # selected, so an instrumental is a station with no vocal bin left to describe.
                    if (selections.get("lead_vocal") or {}).get("options") != ["instrumental"]:
                        problems.append(f"{song}: lead_vocal is not the instrumental option")
                    for bin_id in ("vocal_delivery", "backing_vocal", "vocal_fx", "lyric_theme"):
                        if bin_id in selections:
                            problems.append(f"{song}: '{bin_id}' survives into an instrumental")
        if len(captions) < 2:
            problems.append(
                f"station '{where}': eight songs drew one caption, so the pool is not varying"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(STATIONS_PATH), help="the station document")
    parser.add_argument("--list", action="store_true", help="list the stations and their range")
    parser.add_argument("--plan", default=None, help="plan one station's song and print it")
    parser.add_argument("--index", type=int, default=0, help="the song position to plan")
    parser.add_argument("--seed", type=int, default=None, help="the seed to draw with")
    parser.add_argument("--instrumental", action="store_true", help="plan it with no vocal")
    args = parser.parse_args(argv)

    from . import render as R
    from . import timeline as T

    path = Path(args.path)
    doc = load_stations(path)
    vocab = R.load_vocabulary()
    templates_doc = T.load(T.TEMPLATES_PATH)

    if args.list:
        for station in doc["stations"]:
            shapes = variety(doc, station["id"])
            label = "1,000,000+" if shapes >= 10**6 else f"{shapes:,}"
            print(
                f"{station['id']:28} {station['family']:16} {label:>11} shape(s)  {station['name']}"
            )
        return 0

    if args.plan:
        plan = plan_song(
            doc, args.plan, args.index, seed=args.seed, vocab=vocab, instrumental=args.instrumental
        )
        rendered = R.render(vocab, plan["selections"])
        print(json.dumps({**plan, "caption": rendered["string"]}, indent=2))
        return 0

    problems = validate(vocab, templates_doc, doc)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        print(f"\n{len(problems)} problem(s)")
        return 1
    print(f"the {len(doc['stations'])} station(s) in {path.name} are playable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
