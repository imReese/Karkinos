"""Canonical filesystem locations derived from the runtime environment."""

from __future__ import annotations

import os
from pathlib import Path


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _explicit_runtime_root() -> Path | None:
    workspace = os.environ.get("KARKINOS_WORKSPACE")
    legacy_home = os.environ.get("KARKINOS_HOME")
    if workspace and legacy_home:
        resolved_workspace = _resolved_path(workspace)
        resolved_home = _resolved_path(legacy_home)
        if resolved_workspace != resolved_home:
            raise RuntimeError(
                "KARKINOS_WORKSPACE and legacy KARKINOS_HOME disagree"
            )
        return resolved_workspace
    if workspace:
        return _resolved_path(workspace)
    if legacy_home:
        return _resolved_path(legacy_home)
    return None


def resolve_workspace() -> Path:
    """Return the selected workspace, or cwd for plain local execution."""

    return _explicit_runtime_root() or Path.cwd().resolve()


def resolve_runtime_home() -> Path | None:
    """Return an explicitly selected runtime root, if one exists.

    Plain ``python -m server`` execution intentionally has no implicit runtime
    home. Its config, dotenv, and data paths therefore keep their cwd-relative
    defaults. Source launchers export ``KARKINOS_WORKSPACE`` explicitly.
    """

    return _explicit_runtime_root()


def resolve_data_dir() -> str:
    """Return writable data while preserving plain and legacy defaults."""

    configured = os.environ.get("KARKINOS_DATA_DIR")
    if configured:
        return str(_resolved_path(configured))

    workspace = os.environ.get("KARKINOS_WORKSPACE")
    if workspace:
        return str(_resolved_path(workspace) / "data" / "store")

    legacy_home = os.environ.get("KARKINOS_HOME")
    if legacy_home:
        return str(_resolved_path(legacy_home) / "data")

    return "data/store"


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
