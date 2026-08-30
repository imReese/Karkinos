"""Canonical filesystem locations derived from the runtime environment."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_runtime_home() -> Path | None:
    """Return the native mutable-state root when one was explicitly selected."""
    configured = os.environ.get("KARKINOS_HOME")
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def resolve_data_dir() -> str:
    """Return the writable data directory, defaulting to ``data/store``."""
    configured = os.environ.get("KARKINOS_DATA_DIR")
    if configured:
        return configured
    home = resolve_runtime_home()
    return str(home / "data") if home is not None else "data/store"


def resolve_release_root() -> Path:
    """Return the immutable application root used by native release probes."""
    configured = os.environ.get("KARKINOS_RELEASE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd()


def resolve_static_dir() -> Path:
    """Resolve static assets without coupling native releases to repository cwd."""
    configured = os.environ.get("KARKINOS_STATIC_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return resolve_release_root() / "web" / "dist"
