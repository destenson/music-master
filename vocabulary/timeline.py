"""Thin wrapper. The implementation is :mod:`musicmaster.timeline`.

Kept so that ``import timeline`` after putting ``vocabulary/`` on the path — the arrangement
``songs/*/build_and_submit.py`` and ``spikes/pyodide_text_core/latency_probe.py`` use — keeps
working unchanged. It contains no logic of its own, and like the module it wraps it has no
command-line entry point.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from musicmaster import timeline as _impl

__all__ = [name for name in dir(_impl) if not name.startswith("_")]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


def __getattr__(name: str):
    return getattr(_impl, name)
