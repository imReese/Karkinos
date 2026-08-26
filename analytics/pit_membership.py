"""Point-in-time universe membership evidence for strategy research.

Survivorship bias arises when a research universe is taken from the current
stock directory instead of the historical member set.  This module validates an
operator-frozen universe against persisted, content-addressed market-universe
snapshots at the window boundaries, and fails closed when evidence is missing
or a symbol was not yet listed / already delisted.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

PIT_MEMBERSHIP_SCHEMA_VERSION = "karkinos.pit_membership.v1"


def _member_symbols(members: Any) -> set[str]:
    if not isinstance(members, list):
        return set()
    return {
        str(member["symbol"]).strip()
        for member in members
        if isinstance(member, Mapping) and str(member.get("symbol") or "").strip()
    }


def _snapshot_members_by_date(
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    return {
        str(snapshot["trade_date"]).strip(): _member_symbols(snapshot.get("members"))
        for snapshot in snapshots
        if isinstance(snapshot, Mapping)
        and str(snapshot.get("trade_date") or "").strip()
    }


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_pit_membership_evidence(
    *,
    universe: Sequence[str],
    snapshots: Sequence[Mapping[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Validate that every universe symbol was a member at both window edges.

    ``snapshots`` are persisted market-universe snapshot payloads, each with a
    ``trade_date`` and a ``members`` list of ``{"symbol": ...}`` records.  The
    check requires an exact snapshot for both ``start_date`` and ``end_date``
    and flags symbols missing at either edge as survivorship-biased.
    """

    universe_symbols = {
        str(symbol).strip() for symbol in universe if str(symbol).strip()
    }
    if not universe_symbols:
        raise ValueError("universe must be non-empty")
    members_by_date = _snapshot_members_by_date(snapshots)
    start_members = members_by_date.get(str(start_date))
    end_members = members_by_date.get(str(end_date))
    if start_members is None or end_members is None:
        missing = [
            edge
            for edge, members in (
                ("start_date", start_members),
                ("end_date", end_members),
            )
            if members is None
        ]
        core = {
            "schema_version": PIT_MEMBERSHIP_SCHEMA_VERSION,
            "status": "blocked",
            "blocker": "missing_universe_snapshot",
            "missing_edges": missing,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "universe_size": len(universe_symbols),
            "listed_after_start": [],
            "delisted_before_end": [],
            "survivorship_bias_detected": False,
            "limitations": [
                "Point-in-time membership requires persisted universe snapshots at both window edges.",
            ],
        }
        return {**core, "evidence_fingerprint": _fingerprint(core)}

    listed_after_start = sorted(universe_symbols - start_members)
    delisted_before_end = sorted(universe_symbols - end_members)
    survivorship = bool(listed_after_start or delisted_before_end)
    core = {
        "schema_version": PIT_MEMBERSHIP_SCHEMA_VERSION,
        "status": "blocked" if survivorship else "pass",
        "blocker": "survivorship_bias_detected" if survivorship else None,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "universe_size": len(universe_symbols),
        "start_member_count": len(start_members),
        "end_member_count": len(end_members),
        "listed_after_start": listed_after_start,
        "delisted_before_end": delisted_before_end,
        "survivorship_bias_detected": survivorship,
        "limitations": [
            "Point-in-time membership is validated at the window edges; intra-window ST, suspension, and corporate-action changes require the security master.",
        ],
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


__all__ = [
    "PIT_MEMBERSHIP_SCHEMA_VERSION",
    "build_pit_membership_evidence",
]
