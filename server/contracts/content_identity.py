"""Canonical JSON and content-addressed identity shared across bounded contexts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Return stable JSON used by immutable ids and audit replay."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_fingerprint(value: Any) -> str:
    """Return a SHA-256 identity for one JSON-compatible value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["canonical_json", "content_fingerprint"]
