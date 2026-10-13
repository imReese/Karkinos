"""Human commands resolving reviewed legacy CITIC sources to canonical evidence.

Backward-compatible facade for server.services.controlled_execution.citic.canonical_resolution.
"""

from __future__ import annotations

from server.services.controlled_execution.citic.canonical_resolution import (
    current_citic_source_set_fingerprint,
    record_citic_source_canonical_resolution,
    revoke_citic_source_canonical_resolution,
)

__all__ = [
    "current_citic_source_set_fingerprint",
    "record_citic_source_canonical_resolution",
    "revoke_citic_source_canonical_resolution",
]
