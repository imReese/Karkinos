"""Read-only explanation of persisted fund duplicate corrections."""

from dataclasses import asdict

from server.contracts.ledger_mutations import ledger_entry_state_fingerprint
from server.ledger.models import LedgerEntry
from server.projections.legacy_fund_trade_duplicate_correction import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    resolve_legacy_fund_trade_duplicate_exclusions,
)


def is_fund_duplicate_correction(entry: LedgerEntry) -> bool:
    return (
        entry.entry_type == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
        or entry.source == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    )


def correction_read_evidence(entries: list[LedgerEntry], rows: list[dict]) -> dict:
    """Bind explanations to the same rows checked by the canonical resolver."""
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    by_id = {row["id"]: LedgerEntry.from_row(row) for row in rows}
    result = {}
    for entry in entries:
        if not is_fund_duplicate_correction(entry):
            continue
        fingerprint = ledger_entry_state_fingerprint(asdict(entry))
        current = by_id.get(entry.id)
        blockers = list(resolution.blockers)
        if (
            current is None
            or ledger_entry_state_fingerprint(asdict(current)) != fingerprint
        ):
            blockers.append("correction_read_snapshot_changed")
        if entry.id not in resolution.correction_entry_ids:
            blockers.append("correction_evidence_unverified")
        related = []
        if not blockers:
            payload = entry.correction_payload or {}
            for role, key in (
                ("original", "original_ledger_entry_ids"),
                ("retained", "canonical_ledger_entry_ids"),
            ):
                for entry_id in payload[key]:
                    row = by_id[entry_id]
                    related.append(
                        {
                            "role": role,
                            "id": row.id,
                            "entry_type": row.entry_type,
                            "timestamp": row.timestamp,
                            "symbol": row.symbol,
                            "amount": row.amount,
                            "quantity": row.quantity,
                            "price": row.price,
                            "source": row.source,
                            "entry_fingerprint": ledger_entry_state_fingerprint(
                                asdict(row)
                            ),
                        }
                    )
        result[entry.id] = {
            "status": "unverified" if blockers else "verified",
            "entry_fingerprint": fingerprint,
            "blockers": sorted(set(blockers)),
            "related_entries": related,
        }
    return result
