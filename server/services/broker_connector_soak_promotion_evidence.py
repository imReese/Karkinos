"""Read-side evidence projection for broker connector soak promotion."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
    reviewed_broker_soak_sequence_is_accepted,
)
from server.services.broker_connector_soak_promotion_values import (
    blocked_account_truth,
    drill_connector_scope,
    fingerprint,
    json_object,
)
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_DRILL_TYPES,
    BROKER_CONNECTOR_SOAK_PHASES,
    BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_PHASES = tuple(sorted(BROKER_CONNECTOR_SOAK_PHASES))
_REQUIRED_DRILLS = tuple(sorted(BROKER_CONNECTOR_SOAK_DRILL_TYPES))


class BrokerConnectorSoakEvidenceProjector:
    """Project persisted soak/runbook facts and sanitized Account Truth facts."""

    def __init__(
        self,
        *,
        db: Any,
        account_truth_evidence_provider: Callable[[], dict[str, Any]] | None,
    ) -> None:
        self._db = db
        self._account_truth_evidence_provider = account_truth_evidence_provider

    def operational_evidence(
        self,
        *,
        connector_id: str,
        observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        observations = [
            item
            for item in observations
            if str(item.get("connector_id") or "") == connector_id
        ]
        observations.sort(
            key=lambda item: (
                str(item.get("recorded_at") or ""),
                int(item.get("event_id") or 0),
            )
        )
        blockers: list[str] = []
        if not observations:
            blockers.append("connector_observations_missing")
        latest = observations[-1] if observations else {}
        if observations and str(latest.get("soak_status") or "blocked") != "healthy":
            blockers.append("latest_snapshot_not_healthy")
        elif observations and not reviewed_broker_soak_sequence_is_accepted(latest):
            blockers.append("latest_source_sequence_not_accepted")

        latest_by_clear_day: dict[str, dict[str, Any]] = {}
        for item in observations:
            day = str(item.get("trading_day") or "")
            reconciliation = item.get("execution_reconciliation") or {}
            if (
                day
                and reviewed_broker_soak_sequence_is_accepted(item)
                and str(reconciliation.get("status") or "") == "clear"
                and int(reconciliation.get("open_item_count") or 0) == 0
            ):
                latest_by_clear_day[day] = item
        selected_days = sorted(latest_by_clear_day)[
            :BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS
        ]
        selected = [latest_by_clear_day[day] for day in selected_days]
        if len(selected) < BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS:
            blockers.append(
                "clear_reconciled_soak_days_incomplete:"
                f"{len(selected)}/{BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS}"
            )

        account_alias = str(latest.get("account_alias") or "")
        account_ref_hash = str(latest.get("account_ref_hash") or "")
        if not account_alias:
            blockers.append("connector_account_alias_missing")
        if not account_ref_hash:
            blockers.append("connector_account_ref_hash_missing")
        if any(
            str(item.get("account_alias") or "") != account_alias
            or str(item.get("account_ref_hash") or "") != account_ref_hash
            for item in selected
        ):
            blockers.append("connector_account_identity_changed_during_soak")

        phase_coverage, phase_refs = self._phase_coverage(
            connector_id=connector_id,
            selected_observations=selected,
        )
        for phase in _REQUIRED_PHASES:
            covered = phase_coverage.get(phase, [])
            if covered != selected_days:
                blockers.append(
                    f"runbook_phase_coverage_incomplete:{phase}:"
                    f"{len(covered)}/{len(selected_days)}"
                )
        drill_coverage, drill_refs = self._drill_coverage(connector_id=connector_id)
        for drill_type in _REQUIRED_DRILLS:
            if not drill_coverage.get(drill_type):
                blockers.append(f"recovery_drill_missing:{drill_type}")

        selected_evidence = [
            {
                "event_id": item.get("event_id"),
                "observation_id": str(item.get("observation_id") or ""),
                "snapshot_fingerprint": str(item.get("snapshot_fingerprint") or ""),
                "source_contract_fingerprint": fingerprint(
                    item.get("source_contract") or {}
                ),
                "source_sequence_fingerprint": fingerprint(
                    item.get("source_sequence") or {}
                ),
                "trading_day": str(item.get("trading_day") or ""),
                "execution_reconciliation_ref": str(
                    (item.get("execution_reconciliation") or {}).get("evidence_ref")
                    or ""
                ),
            }
            for item in selected
        ]
        source_core = {
            "connector_id": connector_id,
            "account_alias": account_alias,
            "account_ref_hash": account_ref_hash,
            "selected_observations": selected_evidence,
            "phase_coverage": phase_coverage,
            "phase_refs": phase_refs,
            "drill_coverage": drill_coverage,
            "drill_refs": drill_refs,
            "latest_observation_id": str(latest.get("observation_id") or ""),
        }
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "status": "clear" if not unique_blockers else "blocked",
            "source_fingerprint": fingerprint(source_core),
            "connector_id": connector_id,
            "account_alias": account_alias,
            "account_ref_hash": account_ref_hash,
            "selected_trading_days": selected_days,
            "selected_trading_day_count": len(selected_days),
            "target_trading_day_count": BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
            "selected_observations": selected_evidence,
            "phase_coverage": phase_coverage,
            "phase_evidence_refs": phase_refs,
            "drill_coverage": drill_coverage,
            "drill_evidence_refs": drill_refs,
            "latest_observation_id": str(latest.get("observation_id") or ""),
            "latest_soak_status": str(latest.get("soak_status") or "not_observed"),
            "karkinos_process_instance_recovery": (
                "verified_by_karkinos_restart_drill"
                if drill_coverage.get("karkinos_restart")
                else "missing"
            ),
            "broker_terminal_and_adapter_recovery": "requires_signed_owner_assertion",
            "blockers": unique_blockers,
            "limitations": [
                "Persisted restart_recovery proves new-service-instance replay only.",
                "karkinos_restart proves a changed runtime-instance token and exact persisted replay; the operator must still confirm an actual process restart.",
                "Broker-terminal and adapter restart recovery remain a signed owner assertion.",
            ],
        }

    def account_truth_evidence(self) -> dict[str, Any]:
        if self._account_truth_evidence_provider is None:
            return blocked_account_truth(["account_truth_provider_unavailable"])
        try:
            raw = self._account_truth_evidence_provider() or {}
        except Exception as exc:
            return blocked_account_truth(
                [f"account_truth_provider_failed:{type(exc).__name__}"]
            )
        allowed = {
            "schema_version",
            "status",
            "source_fingerprint",
            "import_run_id",
            "file_fingerprint",
            "source_type",
            "captured_at",
            "current_age_seconds",
            "max_age_seconds",
            "data_freshness_status",
            "reconciliation_status",
            "score",
            "gate_status",
            "cash_status",
            "position_status",
            "fee_status",
            "cost_basis_status",
            "unresolved_mismatch_count",
            "resolved_review_count",
            "blockers",
            "does_not_mutate_production_ledger",
            "does_not_issue_execution_authority",
            "broker_submission_enabled",
        }
        evidence = {key: raw.get(key) for key in allowed if key in raw}
        blockers = [str(item) for item in evidence.get("blockers") or []]
        source_fingerprint = str(evidence.get("source_fingerprint") or "")
        if evidence.get("status") != "clear":
            blockers.append("account_truth_evidence_not_clear")
        if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
            blockers.append("account_truth_source_fingerprint_invalid")
        if evidence.get("gate_status") != "pass":
            blockers.append("account_truth_gate_not_pass")
        if evidence.get("data_freshness_status") != "fresh":
            blockers.append("account_truth_not_fresh")
        if int(evidence.get("unresolved_mismatch_count") or 0) != 0:
            blockers.append("account_truth_unresolved_mismatches")
        evidence["status"] = "clear" if not blockers else "blocked"
        evidence["blockers"] = list(dict.fromkeys(blockers))
        evidence["broker_submission_enabled"] = False
        evidence["does_not_issue_execution_authority"] = True
        evidence["does_not_mutate_production_ledger"] = True
        return evidence

    def _phase_coverage(
        self,
        *,
        connector_id: str,
        selected_observations: list[dict[str, Any]],
    ) -> tuple[dict[str, list[str]], list[str]]:
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=500,
        )
        coverage: dict[str, set[str]] = {phase: set() for phase in _REQUIRED_PHASES}
        refs: list[str] = []
        selected_by_day = {
            str(item.get("trading_day") or ""): item
            for item in selected_observations
            if str(item.get("trading_day") or "")
        }
        for row in rows:
            payload = json_object(row.get("payload_json"))
            phase = str(payload.get("phase") or "")
            if payload.get("run_status") != "passed" or phase not in coverage:
                continue
            matched = False
            for observation in payload.get("observations") or []:
                if not isinstance(observation, dict):
                    continue
                day = str(observation.get("trading_day") or "")
                selected = selected_by_day.get(day)
                if (
                    str(observation.get("connector_id") or "") == connector_id
                    and selected is not None
                    and str(observation.get("soak_status") or "") == "healthy"
                    and str(observation.get("observation_id") or "")
                    == str(selected.get("observation_id") or "")
                    and str(observation.get("snapshot_fingerprint") or "")
                    == str(selected.get("snapshot_fingerprint") or "")
                ):
                    coverage[phase].add(day)
                    matched = True
            if matched:
                refs.append(f"broker_soak_run:{payload.get('run_id') or row.get('id')}")
        return {
            phase: sorted(days) for phase, days in sorted(coverage.items())
        }, sorted(set(refs))

    def _drill_coverage(
        self,
        *,
        connector_id: str,
    ) -> tuple[dict[str, bool], list[str]]:
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=500,
        )
        coverage = {drill_type: False for drill_type in _REQUIRED_DRILLS}
        resolved: set[str] = set()
        refs: list[str] = []
        for row in rows:
            payload = json_object(row.get("payload_json"))
            drill_type = str(payload.get("drill_type") or "")
            if drill_type not in coverage or drill_type in resolved:
                continue
            first_scope = drill_connector_scope(payload.get("first_observations"))
            if first_scope != {connector_id}:
                continue
            passed = payload.get("drill_status") == "passed"
            if drill_type in {
                "duplicate_evidence",
                "restart_recovery",
                "karkinos_restart",
            }:
                second_scope = drill_connector_scope(payload.get("second_observations"))
                if passed and second_scope != {connector_id}:
                    resolved.add(drill_type)
                    continue
            if drill_type == "karkinos_restart" and passed:
                checkpoint_id = str(payload.get("restart_checkpoint_id") or "")
                prepared_process = str(
                    payload.get("prepared_process_instance_fingerprint") or ""
                )
                completed_process = str(
                    payload.get("completed_process_instance_fingerprint") or ""
                )
                if (
                    not _FINGERPRINT_PATTERN.fullmatch(checkpoint_id)
                    or not _FINGERPRINT_PATTERN.fullmatch(prepared_process)
                    or not _FINGERPRINT_PATTERN.fullmatch(completed_process)
                    or prepared_process == completed_process
                    or payload.get("process_instance_changed") is not True
                ):
                    resolved.add(drill_type)
                    continue
            resolved.add(drill_type)
            if not passed:
                continue
            coverage[drill_type] = True
            refs.append(f"broker_soak_drill:{payload.get('drill_id') or row.get('id')}")
        return coverage, sorted(set(refs))
