"""Reasoning-mode ROI guard for strategy research.

Formula DSL proposal and critique do not benefit from a model reasoning chain:
the reasoning content is billed but never persisted or consumed downstream.
This module makes that cost decision explicit and provides deterministic,
provider-free evidence for the reasoning policy of the research path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from server.ai_runtime.contracts import JsonObject

REASONING_ROI_SCHEMA_VERSION = "karkinos.reasoning_roi.v1"


def strategy_research_reasoning_policy() -> JsonObject:
    """Canonical reasoning policy for formula research: reasoning disabled."""

    return {"thinking": {"type": "disabled"}}


def build_reasoning_roi_evidence(
    *,
    reasoning_mode_requested: bool,
    reasoning_content_present: bool,
    reasoning_content_persisted: bool,
) -> dict[str, Any]:
    """Deterministic evidence that no reasoning cost was billed and discarded.

    A pass requires that reasoning was neither requested nor returned and that
    no raw reasoning was persisted.  Any reasoning content is a billed cost that
    this path discards, so it fails closed.
    """

    cost_incurred = bool(reasoning_mode_requested) or bool(reasoning_content_present)
    status = (
        "pass" if not cost_incurred and not reasoning_content_persisted else "blocked"
    )
    core = {
        "schema_version": REASONING_ROI_SCHEMA_VERSION,
        "reasoning_mode_requested": bool(reasoning_mode_requested),
        "reasoning_content_present": bool(reasoning_content_present),
        "reasoning_content_persisted": bool(reasoning_content_persisted),
        "reasoning_cost_incurred": cost_incurred,
        "status": status,
        "blocker": "reasoning_content_billed_but_discarded" if cost_incurred else None,
        "limitations": [
            "Reasoning-ROI evidence reflects the research-path reasoning policy, not provider billing accuracy.",
        ],
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "REASONING_ROI_SCHEMA_VERSION",
    "strategy_research_reasoning_policy",
    "build_reasoning_roi_evidence",
]
