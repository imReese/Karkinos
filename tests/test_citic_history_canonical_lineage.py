from __future__ import annotations

import json
from types import SimpleNamespace

from server.services.citic_history_canonical_lineage import (
    project_citic_history_canonical_lineage_assessment,
)


def _event(
    *,
    event_id: str,
    broker_order_id: str,
    event_type: str = "trade_buy",
    occurred_at: str = "2026-05-06T10:01:02+08:00",
    settled_at: str = "2026-05-06",
    symbol: str = "600001",
    quantity: str = "100",
    price: str = "10",
    gross_amount: str = "1000",
    net_amount: str = "-1005",
    is_row_duplicate: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        broker_order_id=broker_order_id,
        event_type=event_type,
        occurred_at=occurred_at,
        settled_at=settled_at,
        symbol=symbol,
        instrument_name="Synthetic instrument",
        asset_class="stock",
        currency="CNY",
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        net_amount=net_amount,
        is_row_duplicate=is_row_duplicate,
    )


def _scan(*events: SimpleNamespace, state: str = "ready") -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        previews=(SimpleNamespace(events=list(events)),),
        batch_assessment=SimpleNamespace(
            batch_fingerprint="sha256:" + "b" * 64,
        ),
    )


def _import() -> SimpleNamespace:
    return SimpleNamespace(
        import_run_id="import_synthetic",
        file_fingerprint="a" * 64,
    )


def test_citic_lineage_exposes_partial_semantic_match_without_event_identity() -> None:
    first = _event(event_id="source-1", broker_order_id="broker-1")
    second = _event(
        event_id="source-2",
        broker_order_id="broker-2",
        occurred_at="2026-05-07T10:01:02+08:00",
    )
    canonical = [
        _event(event_id="canonical-1", broker_order_id=""),
        _event(
            event_id="canonical-2",
            broker_order_id="",
            occurred_at="2026-05-07T10:01:02+08:00",
        ),
        _event(
            event_id="canonical-extra",
            broker_order_id="",
            occurred_at="2026-05-08T10:01:02+08:00",
        ),
    ]

    assessment = project_citic_history_canonical_lineage_assessment(
        scan=_scan(first, second),
        canonical_import=_import(),
        canonical_events=canonical,
    )

    assert assessment["status"] == "blocked"
    assert assessment["event_lineage_status"] == "partial"
    assert assessment["source_supported_event_count"] == 2
    assert assessment["canonical_supported_event_count"] == 3
    assert assessment["semantically_matched_event_count"] == 2
    assert assessment["source_unmatched_event_count"] == 0
    assert assessment["canonical_unmatched_event_count"] == 1
    assert assessment["source_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 2}
    ]
    assert assessment["canonical_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 3}
    ]
    assert assessment["semantically_matched_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 2}
    ]
    assert assessment["source_unmatched_event_type_counts"] == []
    assert assessment["canonical_unmatched_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1}
    ]
    assert assessment["source_events_with_broker_order_identity_count"] == 2
    assert assessment["canonical_events_with_broker_order_identity_count"] == 0
    assert assessment["broker_order_identity_matched_event_count"] == 0
    assert assessment["exact_event_identity_matched_event_count"] == 0
    assert "citic_canonical_lineage_broker_order_identity_not_preserved" in (
        assessment["blockers"]
    )
    assert (
        "citic_canonical_lineage_event_identity_not_preserved" in assessment["blockers"]
    )
    assert assessment["events_included"] is False
    assert assessment["transaction_details_included"] is False
    assert assessment["source_names_included"] is False
    assert assessment["paths_included"] is False
    assert assessment["assessment_persisted"] is False
    assert assessment["database_writes_performed"] is False
    assert assessment["authorizes_execution"] is False


def test_citic_lineage_exposes_only_sanitized_event_type_diagnostics() -> None:
    source_buy = _event(event_id="source-buy", broker_order_id="broker-buy")
    source_dividend = _event(
        event_id="source-dividend",
        broker_order_id="broker-dividend",
        event_type="dividend",
        occurred_at="2026-07-01T09:00:00+08:00",
        settled_at="2026-07-01",
    )
    canonical_buy = _event(
        event_id="canonical-buy",
        broker_order_id="canonical-buy-order",
    )
    canonical_sell = _event(
        event_id="canonical-sell",
        broker_order_id="canonical-sell-order",
        event_type="trade_sell",
        occurred_at="2026-07-02T10:00:00+08:00",
        settled_at="2026-07-02",
    )

    assessment = project_citic_history_canonical_lineage_assessment(
        scan=_scan(source_buy, source_dividend),
        canonical_import=_import(),
        canonical_events=[canonical_buy, canonical_sell],
    )

    assert assessment["event_lineage_status"] == "partial"
    assert assessment["source_event_type_counts"] == [
        {"event_type": "dividend", "count": 1},
        {"event_type": "trade_buy", "count": 1},
    ]
    assert assessment["canonical_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1},
        {"event_type": "trade_sell", "count": 1},
    ]
    assert assessment["semantically_matched_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1}
    ]
    assert assessment["source_unmatched_event_type_counts"] == [
        {"event_type": "dividend", "count": 1}
    ]
    assert assessment["canonical_unmatched_event_type_counts"] == [
        {"event_type": "trade_sell", "count": 1}
    ]
    assert assessment["canonical_events_with_broker_order_identity_count"] == 2

    serialized = json.dumps(assessment, sort_keys=True)
    for private_value in (
        "Synthetic instrument",
        "600001",
        "source-buy",
        "source-dividend",
        "broker-buy",
        "broker-dividend",
        "canonical-buy-order",
        "canonical-sell-order",
    ):
        assert private_value not in serialized


def test_citic_lineage_ignores_event_types_outside_the_match_contract() -> None:
    supported = _event(event_id="source-buy", broker_order_id="broker-buy")
    unsupported = _event(
        event_id="source-position",
        broker_order_id="broker-position",
        event_type="position_snapshot",
    )

    assessment = project_citic_history_canonical_lineage_assessment(
        scan=_scan(supported, unsupported),
        canonical_import=None,
        canonical_events=(),
    )

    assert assessment["source_supported_event_count"] == 1
    assert assessment["source_event_type_counts"] == [
        {"event_type": "trade_buy", "count": 1}
    ]
    assert all(
        item["event_type"] != "position_snapshot"
        for item in assessment["source_event_type_counts"]
    )


def test_citic_lineage_can_prove_exact_event_identity_but_not_account_coverage() -> (
    None
):
    event = _event(event_id="shared-event", broker_order_id="shared-order")

    first = project_citic_history_canonical_lineage_assessment(
        scan=_scan(event),
        canonical_import=_import(),
        canonical_events=[event],
    )
    second = project_citic_history_canonical_lineage_assessment(
        scan=_scan(event),
        canonical_import=_import(),
        canonical_events=[event],
    )

    assert first["event_lineage_status"] == "exact"
    assert first["semantically_matched_event_count"] == 1
    assert first["broker_order_identity_matched_event_count"] == 1
    assert first["exact_event_identity_matched_event_count"] == 1
    assert first["complete_account_coverage_proven"] is False
    assert first["eligible_for_account_truth"] is False
    assert first["eligible_for_reconciliation"] is False
    assert (
        "citic_canonical_lineage_complete_account_coverage_unproven"
        in first["blockers"]
    )
    assert first["assessment_fingerprint"] == second["assessment_fingerprint"]


def test_citic_lineage_fails_closed_when_canonical_evidence_is_missing() -> None:
    assessment = project_citic_history_canonical_lineage_assessment(
        scan=_scan(_event(event_id="source-1", broker_order_id="broker-1")),
        canonical_import=None,
        canonical_events=(),
        read_blocker="citic_canonical_lineage_canonical_evidence_unreadable",
    )

    assert assessment["event_lineage_status"] == "not_available"
    assert assessment["canonical_import_reference"] is None
    assert (
        "citic_canonical_lineage_canonical_evidence_unreadable"
        in assessment["blockers"]
    )
    assert "citic_canonical_lineage_canonical_import_missing" in assessment["blockers"]
    assert assessment["provider_contacted"] is False
    assert assessment["changes_capital_authority"] is False
