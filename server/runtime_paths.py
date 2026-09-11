"""Canonical filesystem locations derived from the runtime environment."""

from __future__ import annotations

import os
from pathlib import Path


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def resolve_workspace() -> Path:
    """Return the local Karkinos workspace.

    ``KARKINOS_WORKSPACE`` is canonical. ``KARKINOS_HOME`` remains a temporary
    compatibility alias for existing managed installations. Without either
    override, the current working directory is the workspace.
    """

    configured = os.environ.get("KARKINOS_WORKSPACE")
    legacy = os.environ.get("KARKINOS_HOME")
    if configured and legacy and _resolved_path(configured) != _resolved_path(legacy):
        raise RuntimeError("KARKINOS_WORKSPACE and legacy KARKINOS_HOME disagree")
    return _resolved_path(configured or legacy) if configured or legacy else Path.cwd().resolve()


def resolve_runtime_home() -> Path:
    """Compatibility alias for callers not yet renamed to workspace terminology."""

    return resolve_workspace()


def resolve_data_dir() -> str:
    """Return the writable data directory, defaulting to ``<workspace>/data``."""

    configured = os.environ.get("KARKINOS_DATA_DIR")
    if configured:
        return str(_resolved_path(configured))
    return str(resolve_workspace() / "data")


def resolve_release_root() -> Path:
    """Return the immutable application root used by native release probes."""

    configured = os.environ.get("KARKINOS_RELEASE_ROOT")
    if configured:
        return _resolved_path(configured)
    return Path.cwd().resolve()


def resolve_static_dir() -> Path:
    """Resolve static assets without coupling native releases to repository cwd."""

    configured = os.environ.get("KARKINOS_STATIC_DIR")
    if configured:
        return _resolved_path(configured)
    return resolve_release_root() / "web" / "dist"
