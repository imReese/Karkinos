"""Canonical filesystem locations derived from the runtime environment."""

from __future__ import annotations

import os


def resolve_data_dir() -> str:
    """Return the runtime data directory, defaulting to ``data/store``."""
    return os.environ.get("KARKINOS_DATA_DIR") or "data/store"
