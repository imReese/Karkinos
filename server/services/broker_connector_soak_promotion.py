"""Signed Stage 1 promotion dossiers for read-only broker connector soak."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
    BrokerConnectorSoakService,
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
from server.services.operator_approval import resolve_operator_approval

BROKER_SOAK_PROMOTION_DOSSIER_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_promotion_dossier.v1"
)
BROKER_SOAK_PROMOTION_ACCEPTANCE_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_promotion_acceptance.v1"
)
BROKER_SOAK_PROMOTION_STATUS_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_promotion_status.v1"
)
BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE = "broker_connector.soak_promotion_accepted"
BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE = (
    "broker_connector_soak_promotion_acceptance"
)
BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE = "broker_connector_soak_promotion"
BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT = (
    "accept_exact_readonly_soak_and_account_truth_promotion_without_execution_authority"
)

_CONNECTOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_PHASES = tuple(sorted(BROKER_CONNECTOR_SOAK_PHASES))
_REQUIRED_DRILLS = tuple(sorted(BROKER_CONNECTOR_SOAK_DRILL_TYPES))


class BrokerConnectorSoakPromotionRejected(ValueError):
    """Raised after a rejected signed promotion attempt has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class BrokerConnectorSoakPromotionService:
    """Bind operational and Account Truth evidence without execution authority."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...] = (),
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        account_truth_evidence_provider: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._trusted_operator_identities = list(trusted_operator_identities or [])
        self._account_truth_evidence_provider = account_truth_evidence_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        connector_ids = sorted(
            {
                *(
                    _connector_id(connector)
                    for connector in self._connectors
                    if _connector_id(connector)
                ),
                *(
                    str(item.get("connector_id") or "")
                    for item in self._soak_service().list_observations(limit=500)
                    if str(item.get("connector_id") or "")
                ),
            }
        )
        connectors = [
            self.preview_dossier(connector_id) for connector_id in connector_ids
        ]
        promotion_ready = bool(connectors) and all(
            bool(item.get("promotion_ready")) for item in connectors
        )
        blockers = list(
            dict.fromkeys(
                blocker
                for item in connectors
                for blocker in item.get("promotion_blockers") or []
            )
        )
        if not connector_ids:
            blockers.append("no_readonly_connector_observations")
        return {
            "schema_version": BROKER_SOAK_PROMOTION_STATUS_SCHEMA_VERSION,
            "contract_status": "signed_promotion_evidence_only",
            "connector_count": len(connectors),
            "connectors": connectors,
            "promotion_ready": promotion_ready,
            "promotion_blockers": list(dict.fromkeys(blockers)),
            "owner_acceptance_recorded": promotion_ready,
            "account_truth_reconciliation_linked": promotion_ready,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "automatic_promotion_enabled": False,
            "safety": _safety_flags(),
        }

    def preview_dossier(self, connector_id: str) -> dict[str, Any]:
        normalized_connector_id = str(connector_id or "").strip()
        request_blockers: list[str] = []
        if not _CONNECTOR_ID_PATTERN.fullmatch(normalized_connector_id):
            request_blockers.append("connector_id_invalid")
        operational = self._operational_evidence(normalized_connector_id)
        account_truth = self._account_truth_evidence()
        review_blockers = [
            *request_blockers,
            *[str(item) for item in operational.get("blockers") or []],
            *[f"account_truth:{item}" for item in account_truth.get("blockers") or []],
        ]
        if account_truth.get("status") != "clear" and not account_truth.get("blockers"):
            review_blockers.append("account_truth:not_clear")
        review_blockers = list(dict.fromkeys(review_blockers))
        dossier_core = {
            "schema_version": BROKER_SOAK_PROMOTION_DOSSIER_SCHEMA_VERSION,
            "connector_id": normalized_connector_id,
            "account_alias": str(operational.get("account_alias") or ""),
            "account_ref_hash": str(operational.get("account_ref_hash") or ""),
            "operational_evidence": operational,
            "account_truth_evidence": _without_volatile_age(account_truth),
            "required_owner_assertions": [
                "the Account Truth import belongs to the same reviewed broker account alias",
                "full process and broker-terminal restart recovery was performed outside this service",
                "this acceptance is promotion evidence only and grants no execution authority",
            ],
            "review_blockers": review_blockers,
        }
        dossier_fingerprint = _fingerprint(dossier_core)
        acceptance = self._latest_matching_acceptance(
            normalized_connector_id,
            dossier_fingerprint=dossier_fingerprint,
        )
        review_ready = not review_blockers
        promotion_ready = review_ready and acceptance["status"] == (
            "recorded_verified_owner_acceptance"
        )
        promotion_blockers = list(review_blockers)
        if review_ready and not promotion_ready:
            promotion_blockers.append("signed_owner_acceptance_missing")
        return {
            **dossier_core,
            "account_truth_evidence": account_truth,
            "dossier_fingerprint": dossier_fingerprint,
            "generated_at": _aware_utc(self._clock()).isoformat(),
            "review_status": (
                "ready_for_signed_owner_acceptance"
                if review_ready
                else "blocked_review"
            ),
            "review_ready": review_ready,
            "acceptance": acceptance,
            "promotion_ready": promotion_ready,
            "promotion_blockers": list(dict.fromkeys(promotion_blockers)),
            "owner_acceptance_recorded": promotion_ready,
            "account_truth_reconciliation_linked": promotion_ready,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }

    def record_acceptance(
        self,
        *,
        connector_id: str,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        dossier = self.preview_dossier(connector_id)
        rejection_reasons: list[str] = []
        normalized_label = str(operator_label or "").strip()
        if not normalized_label:
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if dossier_fingerprint != dossier["dossier_fingerprint"]:
            rejection_reasons.append("dossier_fingerprint_mismatch")
        if dossier["review_blockers"]:
            rejection_reasons.append("promotion_dossier_review_blocked")
        operator_approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="accept_broker_connector_soak_promotion",
            expected_artifact_type="broker_connector_soak_promotion_dossier",
            expected_artifact_fingerprint=dossier["dossier_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("operator_approval_blocked")
        elif normalized_label != operator_approval["operator_id"]:
            rejection_reasons.append("operator_label_approval_mismatch")

        status = (
            "rejected" if rejection_reasons else "recorded_verified_owner_acceptance"
        )
        attempt = self._record_attempt(
            dossier=dossier,
            submitted_dossier_fingerprint=dossier_fingerprint,
            operator_label=normalized_label,
            operator_approval=operator_approval,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise BrokerConnectorSoakPromotionRejected(
                "broker connector soak promotion acceptance rejected: "
                + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def list_acceptances(
        self,
        *,
        connector_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
            entity_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE,
            source=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        results = [_event_response(row, reused=False) for row in rows]
        normalized = str(connector_id or "").strip()
        if normalized:
            results = [
                item
                for item in results
                if str(item.get("connector_id") or "") == normalized
            ]
        return results

    def _operational_evidence(self, connector_id: str) -> dict[str, Any]:
        observations = [
            item
            for item in self._soak_service().list_observations(limit=500)
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

        latest_by_clear_day: dict[str, dict[str, Any]] = {}
        for item in observations:
            day = str(item.get("trading_day") or "")
            reconciliation = item.get("execution_reconciliation") or {}
            if (
                day
                and item.get("qualifies_for_healthy_soak_day") is True
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
            selected_days=selected_days,
        )
        for phase in _REQUIRED_PHASES:
            covered = phase_coverage.get(phase, [])
            if covered != selected_days:
                blockers.append(
                    f"runbook_phase_coverage_incomplete:{phase}:"
                    f"{len(covered)}/{len(selected_days)}"
                )
        drill_coverage, drill_refs = self._drill_coverage()
        for drill_type in _REQUIRED_DRILLS:
            if not drill_coverage.get(drill_type):
                blockers.append(f"recovery_drill_missing:{drill_type}")

        selected_evidence = [
            {
                "event_id": item.get("event_id"),
                "observation_id": str(item.get("observation_id") or ""),
                "snapshot_fingerprint": str(item.get("snapshot_fingerprint") or ""),
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
            "source_fingerprint": _fingerprint(source_core),
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
            "external_process_and_broker_terminal_recovery": (
                "requires_signed_owner_assertion"
            ),
            "blockers": unique_blockers,
            "limitations": [
                "Persisted restart_recovery proves new-service-instance replay only.",
                "Full process and broker-terminal recovery remains a signed owner assertion.",
            ],
        }

    def _phase_coverage(
        self,
        *,
        connector_id: str,
        selected_days: list[str],
    ) -> tuple[dict[str, list[str]], list[str]]:
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=500,
        )
        coverage: dict[str, set[str]] = {phase: set() for phase in _REQUIRED_PHASES}
        refs: list[str] = []
        selected_set = set(selected_days)
        for row in rows:
            payload = _json_object(row.get("payload_json"))
            phase = str(payload.get("phase") or "")
            if payload.get("run_status") != "passed" or phase not in coverage:
                continue
            matched = False
            for observation in payload.get("observations") or []:
                if not isinstance(observation, dict):
                    continue
                day = str(observation.get("trading_day") or "")
                if (
                    str(observation.get("connector_id") or "") == connector_id
                    and day in selected_set
                    and str(observation.get("soak_status") or "") == "healthy"
                ):
                    coverage[phase].add(day)
                    matched = True
            if matched:
                refs.append(f"broker_soak_run:{payload.get('run_id') or row.get('id')}")
        return {
            phase: sorted(days) for phase, days in sorted(coverage.items())
        }, sorted(set(refs))

    def _drill_coverage(self) -> tuple[dict[str, bool], list[str]]:
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=500,
        )
        coverage = {drill_type: False for drill_type in _REQUIRED_DRILLS}
        refs: list[str] = []
        for row in rows:
            payload = _json_object(row.get("payload_json"))
            drill_type = str(payload.get("drill_type") or "")
            if drill_type in coverage and payload.get("drill_status") == "passed":
                coverage[drill_type] = True
                refs.append(
                    f"broker_soak_drill:{payload.get('drill_id') or row.get('id')}"
                )
        return coverage, sorted(set(refs))

    def _account_truth_evidence(self) -> dict[str, Any]:
        if self._account_truth_evidence_provider is None:
            return _blocked_account_truth(["account_truth_provider_unavailable"])
        try:
            raw = self._account_truth_evidence_provider() or {}
        except Exception as exc:
            return _blocked_account_truth(
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

    def _record_attempt(
        self,
        *,
        dossier: dict[str, Any],
        submitted_dossier_fingerprint: str,
        operator_label: str,
        operator_approval: dict[str, Any],
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "connector_id": dossier["connector_id"],
            "dossier_fingerprint": dossier["dossier_fingerprint"],
            "submitted_dossier_fingerprint": submitted_dossier_fingerprint,
            "operational_evidence_fingerprint": dossier["operational_evidence"][
                "source_fingerprint"
            ],
            "account_truth_source_fingerprint": dossier["account_truth_evidence"].get(
                "source_fingerprint"
            ),
            "operator_label": operator_label,
            "operator_approval_id": operator_approval.get("approval_id"),
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": list(rejection_reasons),
        }
        acceptance_id = _fingerprint(identity)
        payload = {
            "schema_version": BROKER_SOAK_PROMOTION_ACCEPTANCE_SCHEMA_VERSION,
            "acceptance_id": acceptance_id,
            **identity,
            "account_alias": dossier["account_alias"],
            "account_ref_hash": dossier["account_ref_hash"],
            "selected_trading_days": list(
                dossier["operational_evidence"]["selected_trading_days"]
            ),
            "operator_approval": operator_approval,
            "operator_identity_verified": bool(
                operator_approval.get("operator_identity_verified")
            ),
            "owner_assertions": {
                "account_truth_import_matches_reviewed_account_alias": (
                    status == "recorded_verified_owner_acceptance"
                ),
                "full_process_and_broker_terminal_restart_performed": (
                    status == "recorded_verified_owner_acceptance"
                ),
                "promotion_evidence_only_without_execution_authority": True,
            },
            "promotion_evidence_complete": (
                status == "recorded_verified_owner_acceptance"
            ),
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
            entity_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE,
            entity_id=acceptance_id,
            source=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        now = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE,
            entity_id=acceptance_id,
            source=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE,
            source_ref=dossier["dossier_fingerprint"],
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
            entity_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE,
            entity_id=acceptance_id,
            source=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("broker soak promotion acceptance was not recorded")
        return _event_response(saved[0], reused=False)

    def _latest_matching_acceptance(
        self,
        connector_id: str,
        *,
        dossier_fingerprint: str,
    ) -> dict[str, Any]:
        for item in self.list_acceptances(connector_id=connector_id, limit=500):
            if (
                item.get("status") == "recorded_verified_owner_acceptance"
                and item.get("dossier_fingerprint") == dossier_fingerprint
                and item.get("operator_identity_verified") is True
            ):
                return {
                    "status": "recorded_verified_owner_acceptance",
                    "acceptance_id": item.get("acceptance_id"),
                    "recorded_at": item.get("recorded_at"),
                    "operator_label": item.get("operator_label"),
                    "operator_identity_verified": True,
                    "authorizes_execution": False,
                }
        return {
            "status": "missing",
            "acceptance_id": "",
            "recorded_at": "",
            "operator_label": "",
            "operator_identity_verified": False,
            "authorizes_execution": False,
        }

    def _soak_service(self) -> BrokerConnectorSoakService:
        return BrokerConnectorSoakService(
            db=self._db,
            connectors=self._connectors,
            clock=self._clock,
        )


def _connector_id(connector: Any) -> str:
    return str(
        getattr(connector, "connector_id", "")
        or getattr(getattr(connector, "snapshot", None), "connector_id", "")
        or ""
    ).strip()


def _blocked_account_truth(blockers: list[str]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "source_fingerprint": "",
        "gate_status": "blocked",
        "data_freshness_status": "missing",
        "unresolved_mismatch_count": 0,
        "blockers": list(dict.fromkeys(blockers)),
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def _without_volatile_age(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "current_age_seconds"}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safety_flags() -> dict[str, bool]:
    return {
        "stores_broker_credentials": False,
        "does_not_grant_capital_authority": True,
        "does_not_issue_or_resume_runtime_authority": True,
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_reserve_or_consume_budget": True,
        "automatic_promotion_enabled": False,
    }
