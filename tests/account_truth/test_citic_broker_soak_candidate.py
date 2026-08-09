from __future__ import annotations

import json
from dataclasses import replace

from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.citic_broker_soak_candidate import (
    CITIC_BROKER_SOAK_CANDIDATE_SCHEMA_VERSION,
    build_citic_broker_soak_candidate,
)
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
)

_PRIVATE_PREVIEW_CSV = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
synthetic-buy,trade_buy,2026-05-05T09:35:00+08:00,2026-05-06,SENSITIVE-SYMBOL,SENSITIVE-NAME,stock,CNY,100,10,1000,0,0,-1005,,,,SENSITIVE-NOTE,0,,ORDER-SYN-001,
"""


def _preview():
    preview = parse_broker_statement_csv(_PRIVATE_PREVIEW_CSV)
    return replace(
        preview,
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        normalized_columns=CITIC_HISTORY_XLS_COLUMNS,
        validation_status="blocked",
    )


def test_citic_history_preview_is_never_a_broker_soak_snapshot() -> None:
    candidate = build_citic_broker_soak_candidate(_preview())

    assert candidate["schema_version"] == (CITIC_BROKER_SOAK_CANDIDATE_SCHEMA_VERSION)
    assert candidate["status"] == "blocked"
    assert candidate["source_contract_valid"] is True
    assert candidate["recognized_event_count"] == 1
    assert candidate["blockers"] == ["citic_history_xls_not_broker_connector_snapshot"]
    assert candidate["required_source_evidence"] == [
        "versioned_readonly_connector_snapshot",
        "reviewed_account_alias_binding",
        "provider_source_captured_at",
        "connector_deployment_identity",
        "connector_health_evidence",
        "current_cash_snapshot",
        "current_position_snapshot",
        "current_order_snapshot",
        "itemized_fill_fees_and_taxes",
    ]
    assert candidate["operational_prerequisites"] == [
        "explicit_adapter_release_review",
        "provider_trading_calendar_evidence",
        "clear_execution_reconciliation",
    ]
    assert candidate["eligible_for_broker_soak"] is False
    assert candidate["connector_registered"] is False
    assert candidate["provider_contacted"] is False
    assert candidate["database_writes_performed"] is False
    assert candidate["does_not_record_soak_evidence"] is True
    assert candidate["authorizes_execution"] is False
    assert candidate["changes_capital_authority"] is False

    rendered = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    for private_value in (
        "SENSITIVE-SYMBOL",
        "SENSITIVE-NAME",
        "SENSITIVE-NOTE",
        "ORDER-SYN-001",
    ):
        assert private_value not in rendered


def test_citic_broker_soak_assessment_is_deterministic_and_fails_closed() -> None:
    preview = _preview()
    first = build_citic_broker_soak_candidate(preview)
    replay = build_citic_broker_soak_candidate(
        replace(preview, generated_at="2099-01-01T00:00:00+00:00")
    )
    invalid = build_citic_broker_soak_candidate(replace(preview, invalid_row_count=1))
    inconsistent = build_citic_broker_soak_candidate(replace(preview, row_count=0))

    assert replay["assessment_fingerprint"] == first["assessment_fingerprint"]
    assert invalid["assessment_fingerprint"] != first["assessment_fingerprint"]
    assert "citic_history_xls_invalid_rows_present" in invalid["blockers"]
    assert invalid["eligible_for_broker_soak"] is False
    assert inconsistent["source_contract_valid"] is False
    assert "citic_history_xls_source_contract_invalid" in inconsistent["blockers"]
