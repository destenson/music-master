"""Thin wrapper. The implementation is :mod:`musicmaster.render`.

Kept so that ``python3 vocabulary/render_tags.py ...`` and existing importers such as
``songs/*/build_and_submit.py`` keep working unchanged; it contains no logic of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from musicmaster import render as _impl

__all__ = [name for name in dir(_impl) if not name.startswith("_")]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


def __getattr__(name: str):
    return getattr(_impl, name)


if __name__ == "__main__":
    sys.exit(_impl.main(sys.argv))
