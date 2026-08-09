"""Fail-closed broker-soak assessment for CITIC history-trade previews.

History-trade XLS files are useful incomplete Account Truth inputs, but they are
not versioned broker-connector snapshots.  This module owns the deterministic
projection that keeps that distinction explicit without contacting a provider,
registering a connector, persisting soak evidence, or granting authority.
"""

from __future__ import annotations

import hashlib
import json
import re

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_SOURCE_TYPE,
)

CITIC_BROKER_SOAK_CANDIDATE_SCHEMA_VERSION = (
    "karkinos.account_truth.citic_broker_soak_candidate.v1"
)

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_SOURCE_EVIDENCE = (
    "versioned_readonly_connector_snapshot",
    "reviewed_account_alias_binding",
    "provider_source_captured_at",
    "connector_deployment_identity",
    "connector_health_evidence",
    "current_cash_snapshot",
    "current_position_snapshot",
    "current_order_snapshot",
    "itemized_fill_fees_and_taxes",
)

_OPERATIONAL_PREREQUISITES = (
    "explicit_adapter_release_review",
    "provider_trading_calendar_evidence",
    "clear_execution_reconciliation",
)


def build_citic_broker_soak_candidate(
    preview: BrokerStatementPreview,
) -> dict[str, object]:
    """Explain why one history-trade preview cannot count toward broker soak."""

    columns = tuple(preview.normalized_columns)
    source_contract_valid = (
        preview.source_type == CITIC_HISTORY_XLS_SOURCE_TYPE
        and preview.validation_status == "blocked"
        and bool(_FINGERPRINT_PATTERN.fullmatch(preview.file_fingerprint))
        and len(columns) == len(CITIC_HISTORY_XLS_COLUMNS)
        and set(columns) == set(CITIC_HISTORY_XLS_COLUMNS)
        and preview.row_count >= 0
        and preview.valid_row_count >= 0
        and preview.invalid_row_count >= 0
        and preview.valid_row_count == len(preview.events)
        and preview.row_count >= preview.valid_row_count + preview.invalid_row_count
    )
    blockers = ["citic_history_xls_not_broker_connector_snapshot"]
    if not source_contract_valid:
        blockers.append("citic_history_xls_source_contract_invalid")
    if preview.invalid_row_count > 0:
        blockers.append("citic_history_xls_invalid_rows_present")

    fingerprint_payload = {
        "schema_version": CITIC_BROKER_SOAK_CANDIDATE_SCHEMA_VERSION,
        "source_type": preview.source_type,
        "file_fingerprint": preview.file_fingerprint,
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "recognized_event_count": len(preview.events),
        "source_contract_valid": source_contract_valid,
        "blockers": blockers,
        "required_source_evidence": _REQUIRED_SOURCE_EVIDENCE,
        "operational_prerequisites": _OPERATIONAL_PREREQUISITES,
    }
    assessment_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": CITIC_BROKER_SOAK_CANDIDATE_SCHEMA_VERSION,
        "status": "blocked",
        "assessment_fingerprint": assessment_fingerprint,
        "source_contract_valid": source_contract_valid,
        "recognized_event_count": len(preview.events),
        "blockers": blockers,
        "required_source_evidence": list(_REQUIRED_SOURCE_EVIDENCE),
        "operational_prerequisites": list(_OPERATIONAL_PREREQUISITES),
        "eligible_for_broker_soak": False,
        "connector_registered": False,
        "provider_contacted": False,
        "database_writes_performed": False,
        "does_not_register_connector": True,
        "does_not_record_soak_evidence": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
