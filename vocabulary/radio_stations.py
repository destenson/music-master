"""Thin wrapper. The implementation is :mod:`musicmaster.radio`.

Kept so that ``python3 vocabulary/radio_stations.py`` and existing importers keep working unchanged;
it contains no logic of its own.

    python3 vocabulary/radio_stations.py                 # check every station is playable
    python3 vocabulary/radio_stations.py --list          # the stations and how much they vary
    python3 vocabulary/radio_stations.py --plan=neon-drive --index=3 --seed=42
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from musicmaster import radio as _impl

__all__ = [name for name in dir(_impl) if not name.startswith("_")]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


def __getattr__(name: str):
    return getattr(_impl, name)


if __name__ == "__main__":
    sys.exit(_impl.main(sys.argv[1:]))
