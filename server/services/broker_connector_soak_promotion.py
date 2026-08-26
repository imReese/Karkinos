"""Signed Stage 1 promotion dossiers for read-only broker connector soak."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.broker_connector_soak import BrokerConnectorSoakService
from server.services.broker_connector_soak_promotion_evidence import (
    BrokerConnectorSoakEvidenceProjector,
)
from server.services.broker_connector_soak_promotion_values import (
    aware_utc,
)
from server.services.broker_connector_soak_promotion_values import (
    connector_id as connector_identity,
)
from server.services.broker_connector_soak_promotion_values import (
    event_response,
    fingerprint,
    safety_flags,
    without_volatile_age,
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
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._evidence = BrokerConnectorSoakEvidenceProjector(
            db=db,
            account_truth_evidence_provider=account_truth_evidence_provider,
        )

    def get_status(self) -> dict[str, Any]:
        connector_ids = sorted(
            {
                *(
                    connector_identity(connector)
                    for connector in self._connectors
                    if connector_identity(connector)
                ),
                *(
                    str(item.get("connector_id") or "")
                    for item in self._soak_service().list_observations(limit=500)
                    if str(item.get("connector_id") or "")
                ),
            }
        )
        connectors = [self.preview_dossier(item) for item in connector_ids]
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
            "safety": safety_flags(),
        }

    def preview_dossier(self, connector_id: str) -> dict[str, Any]:
        normalized_connector_id = str(connector_id or "").strip()
        request_blockers: list[str] = []
        if not _CONNECTOR_ID_PATTERN.fullmatch(normalized_connector_id):
            request_blockers.append("connector_id_invalid")
        operational = self._evidence.operational_evidence(
            connector_id=normalized_connector_id,
            observations=self._soak_service().list_observations(limit=500),
        )
        account_truth = self._evidence.account_truth_evidence()
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
            "account_truth_evidence": without_volatile_age(account_truth),
            "required_owner_assertions": [
                "the Account Truth import belongs to the same reviewed broker account alias",
                "full process and broker-terminal restart recovery was performed outside this service",
                "this acceptance is promotion evidence only and grants no execution authority",
            ],
            "review_blockers": review_blockers,
        }
        dossier_fingerprint = fingerprint(dossier_core)
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
            "generated_at": aware_utc(self._clock()).isoformat(),
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
            "safety": safety_flags(),
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
        results = [event_response(row, reused=False) for row in rows]
        normalized = str(connector_id or "").strip()
        if normalized:
            results = [
                item
                for item in results
                if str(item.get("connector_id") or "") == normalized
            ]
        return results

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
        acceptance_id = fingerprint(identity)
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
            "safety": safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
            entity_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_ENTITY_TYPE,
            entity_id=acceptance_id,
            source=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return event_response(existing[0], reused=True)
        now = aware_utc(self._clock())
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
        return event_response(saved[0], reused=False)

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
