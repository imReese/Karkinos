"""Resolve the local root that holds research Dataset objects."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def strategy_dataset_store_root(db: Any) -> Path | None:
    configured = str(os.environ.get("KARKINOS_DATA_DIR") or "").strip()
    if configured:
        return Path(configured)
    database_path = getattr(db, "_path", None)
    if database_path is None:
        return None
    return Path(database_path).parent


__all__ = ["strategy_dataset_store_root"]
