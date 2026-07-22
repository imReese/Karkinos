"""Non-submitting, evidence-fingerprinted per-order confirmation dossiers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from server.services.broker_adapter_readiness import (
    BROKER_ADAPTER_READINESS_SCHEMA_VERSION,
    build_broker_adapter_readiness,
)
from server.services.broker_connector_soak import BrokerConnectorSoakService
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
    CAPITAL_AUTHORIZATION_EVENT_SOURCE,
    CAPITAL_AUTHORIZATION_EVENT_TYPE,
)
from server.services.execution_batch_reconciliation import (
    resolve_prior_batch_reconciliation,
)
from server.services.execution_gateway_binding import build_execution_gateway_binding
from server.services.execution_gateway_verification_binding import (
    build_execution_gateway_order_contract,
    resolve_execution_gateway_verification_binding,
)
from server.services.operator_approval import resolve_operator_approval
from server.services.per_order_gateway_evidence import (
    resolve_per_order_gateway_evidence,
)

PER_ORDER_DOSSIER_SCHEMA_VERSION = "karkinos.per_order_confirmation_dossier.v5"
PER_ORDER_CONFIRMATION_SCHEMA_VERSION = "karkinos.per_order_confirmation.v4"
PER_ORDER_CONFIRMATION_EVENT_TYPE = "controlled_bridge.per_order_confirmed"
PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE = "per_order_confirmation"
PER_ORDER_CONFIRMATION_EVENT_SOURCE = "controlled_bridge_confirmation"
PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT = (
    "confirm_exact_non_submitting_dossier_for_review"
)
PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS = 900
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class PerOrderConfirmationRejected(ValueError):
    """Raised after a rejected confirmation attempt has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class PerOrderConfirmationService:
    """Build and attest exact order dossiers without execution authority."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...] = (),
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        broker_soak_promotion_evidence_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        execution_gateway_verification_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        account_truth_evidence_provider: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._trusted_operator_identities = list(trusted_operator_identities or [])
        self._trading_controls = trading_controls
        self._broker_soak_promotion_evidence_provider = (
            broker_soak_promotion_evidence_provider
        )
        self._execution_gateway_verification_provider = (
            execution_gateway_verification_provider
        )
        self._account_truth_evidence_provider = account_truth_evidence_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.per_order_confirmation_status.v4",
            "contract_status": "evidence_only_non_submitting",
            "runtime_execution_authority": "disabled",
            "operator_identity_verified": False,
            "signature_verification_configured": bool(
                self._trusted_operator_identities
            ),
            "broker_submission_enabled": False,
            "live_gateway_implemented": False,
            "controlled_bridge_promotion_ready": False,
            "broker_adapter_release_binding": "required_per_dossier",
            "broker_soak_promotion_binding": "required_per_dossier",
            "execution_gateway_verification_binding": "required_per_dossier",
            "gateway_evidence_source_binding": "required_per_dossier",
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
            "safety": _safety_flags(),
            "limitations": [
                "A recorded confirmation requires a verified, artifact-bound operator signature.",
                "It does not change OMS status or grant broker execution authority.",
                "An exact recorded clear prior-batch reconciliation fingerprint is required.",
                "Each dossier resolves the current reviewed read-only broker adapter release.",
                "Each dossier resolves current signed broker-soak promotion evidence.",
                "Each dossier resolves an exact, current, non-submitting gateway verification.",
                "Every gateway gate reference must resolve to matching persisted Account Truth, Decision, risk, and paper/shadow facts.",
                "A reviewed submit-capable runtime remains required and unimplemented.",
            ],
        }

    def preview_dossier(
        self,
        order_id: str,
        *,
        capital_evaluation_input_fingerprint: str = "",
        prior_batch_reconciliation_fingerprint: str = "",
        execution_gateway_verification_fingerprint: str = "",
    ) -> dict[str, Any]:
        order = self._require_order(order_id)
        now = _aware_utc(self._clock())
        order_contract = _order_contract(order)
        order_fingerprint = _fingerprint(order_contract)
        capital, capital_blockers = self._capital_evaluation_summary(
            capital_evaluation_input_fingerprint,
            order=order,
            order_fingerprint=order_fingerprint,
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprint=(
                execution_gateway_verification_fingerprint
            ),
            now=now,
        )
        scope = capital.get("scope") or {}
        gateway, gateway_blockers = resolve_per_order_gateway_evidence(
            db=self._db,
            order=order,
            capital_scope=scope,
            capital_evidence_refs=capital.get("evidence_refs") or [],
            account_truth_provider=self._account_truth_evidence_provider,
        )
        connector_id = str(scope.get("evidence_connector_id") or "")
        broker_adapter_release, broker_adapter_release_blockers = (
            _resolve_broker_adapter_release_binding(
                _read_broker_adapter_readiness(self._db),
                expected_collector_id=connector_id,
                expected_gateway_id=str(scope.get("execution_gateway_id") or ""),
                expected_account_alias=str(scope.get("account_alias") or ""),
            )
        )
        soak, soak_review_blockers, soak_hard_blockers = self._soak_summary(
            connector_id,
            now=now,
        )
        execution_gateway, execution_gateway_hard_blockers = (
            build_execution_gateway_binding(
                gateway_id=(capital.get("scope") or {}).get("execution_gateway_id"),
                health_status=capital.get("execution_gateway_health_status"),
                can_submit_orders=capital.get("execution_gateway_can_submit"),
                account_binding_status=capital.get("connector_account_binding_status"),
            )
        )
        execution_gateway_verification, verification_blockers = (
            resolve_execution_gateway_verification_binding(
                self._execution_gateway_verification_provider,
                fingerprint=execution_gateway_verification_fingerprint,
                expected_gateway_id=str(
                    (capital.get("scope") or {}).get("execution_gateway_id") or ""
                ),
                expected_evidence_connector_id=str(
                    (capital.get("scope") or {}).get("evidence_connector_id") or ""
                ),
                expected_account_alias=str(
                    (capital.get("scope") or {}).get("account_alias") or ""
                ),
                expected_order_id=str(order.get("order_id") or ""),
                expected_order_fingerprint=order_fingerprint,
                expected_order_contract=build_execution_gateway_order_contract(order),
            )
        )
        execution_gateway = {
            **execution_gateway,
            "runtime_verification_status": execution_gateway_verification[
                "runtime_verification_status"
            ],
            "runtime_gateway_verified": execution_gateway_verification[
                "runtime_gateway_verified"
            ],
            "verification_id": execution_gateway_verification["verification_id"],
            "verification_fingerprint": execution_gateway_verification[
                "verification_fingerprint"
            ],
            "verification_recorded_at": execution_gateway_verification["recorded_at"],
        }
        if execution_gateway_verification["runtime_gateway_verified"]:
            execution_gateway_hard_blockers = [
                blocker
                for blocker in execution_gateway_hard_blockers
                if blocker != "execution_gateway_runtime_not_verified"
            ]
        reconciliation, reconciliation_blockers = self._reconciliation_summary(
            prior_batch_reconciliation_fingerprint
        )
        kill_switch, kill_switch_blockers = self._kill_switch_summary()

        review_blockers: list[str] = []
        if str(order.get("status") or "") != "manually_confirmed":
            review_blockers.append("oms_order_not_manually_confirmed")
        review_blockers.extend(capital_blockers)
        review_blockers.extend(gateway_blockers)
        review_blockers.extend(broker_adapter_release_blockers)
        review_blockers.extend(soak_review_blockers)
        review_blockers.extend(verification_blockers)
        review_blockers.extend(reconciliation_blockers)
        review_blockers.extend(kill_switch_blockers)
        review_blockers = list(dict.fromkeys(review_blockers))

        hard_submission_blockers = list(
            dict.fromkeys(
                [
                    *broker_adapter_release_blockers,
                    *gateway_blockers,
                    *soak_hard_blockers,
                    *execution_gateway_hard_blockers,
                    *(
                        []
                        if reconciliation.get("status") == "pass"
                        else ["prior_batch_reconciliation_not_bound_or_clear"]
                    ),
                    "operator_identity_unverified",
                    "runtime_execution_authority_disabled",
                    "live_gateway_not_implemented",
                    "broker_submission_disabled",
                ]
            )
        )
        dossier_core = {
            "schema_version": PER_ORDER_DOSSIER_SCHEMA_VERSION,
            "order": order_contract,
            "order_fingerprint": order_fingerprint,
            "capital_evaluation": capital,
            "gateway_gates": gateway,
            "broker_adapter_release": broker_adapter_release,
            "connector_soak": soak,
            "execution_gateway": execution_gateway,
            "execution_gateway_verification": execution_gateway_verification,
            "prior_execution_reconciliation": reconciliation,
            "kill_switch": kill_switch,
            "review_blockers": review_blockers,
            "hard_submission_blockers": hard_submission_blockers,
        }
        fingerprint_core = {
            **dossier_core,
            "connector_soak": {
                key: value
                for key, value in soak.items()
                if key != "current_age_seconds"
            },
        }
        dossier_fingerprint = _fingerprint(fingerprint_core)
        latest_confirmation = self._latest_matching_confirmation(
            order_id,
            dossier_fingerprint=dossier_fingerprint,
        )
        return {
            **dossier_core,
            "dossier_fingerprint": dossier_fingerprint,
            "generated_at": now.isoformat(),
            "review_status": (
                "review_ready_non_submitting"
                if not review_blockers
                else "blocked_review"
            ),
            "review_ready": not review_blockers,
            "submission_status": "blocked",
            "confirmation": latest_confirmation,
            "operator_identity_verified": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }

    def record_confirmation(
        self,
        order_id: str,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprint: str,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        dossier = self.preview_dossier(
            order_id,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprint=(
                execution_gateway_verification_fingerprint
            ),
        )
        rejection_reasons: list[str] = []
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if dossier_fingerprint != dossier["dossier_fingerprint"]:
            rejection_reasons.append("dossier_fingerprint_mismatch")
        if dossier["review_blockers"]:
            rejection_reasons.append("dossier_review_blocked")
        operator_approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="attest_per_order_dossier",
            expected_artifact_type="per_order_dossier",
            expected_artifact_fingerprint=dossier["dossier_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("operator_approval_blocked")
        elif str(operator_label or "").strip() != operator_approval["operator_id"]:
            rejection_reasons.append("operator_label_approval_mismatch")

        status = "rejected" if rejection_reasons else "recorded_verified_identity"
        attempt = self._record_attempt(
            order_id=order_id,
            dossier=dossier,
            submitted_dossier_fingerprint=dossier_fingerprint,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprint=(
                execution_gateway_verification_fingerprint
            ),
            operator_label=str(operator_label or "").strip(),
            operator_approval=operator_approval,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise PerOrderConfirmationRejected(
                "per-order confirmation rejected: " + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def resolve_confirmation(self, confirmation_id: str) -> dict[str, Any]:
        """Re-resolve one recorded confirmation against current gate evidence."""
        normalized = str(confirmation_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_confirmation_resolution(
                normalized,
                ["per_order_confirmation_id_invalid"],
            )
        rows = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=normalized,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return _blocked_confirmation_resolution(
                normalized,
                ["per_order_confirmation_not_found"],
            )
        recorded = _event_response(rows[0], reused=False)
        blockers: list[str] = []
        if recorded.get("status") != "recorded_verified_identity":
            blockers.append("per_order_confirmation_not_verified")
        order_id = str(recorded.get("order_id") or "")
        capital_fingerprint = str(
            recorded.get("capital_evaluation_input_fingerprint") or ""
        )
        prior_batch_fingerprint = str(
            recorded.get("prior_batch_reconciliation_fingerprint") or ""
        )
        gateway_fingerprint = str(
            recorded.get("execution_gateway_verification_fingerprint") or ""
        )
        if not _FINGERPRINT_PATTERN.fullmatch(prior_batch_fingerprint):
            blockers.append("per_order_confirmation_prior_batch_evidence_missing")
        try:
            dossier = self.preview_dossier(
                order_id,
                capital_evaluation_input_fingerprint=capital_fingerprint,
                prior_batch_reconciliation_fingerprint=prior_batch_fingerprint,
                execution_gateway_verification_fingerprint=gateway_fingerprint,
            )
        except (KeyError, ValueError):
            dossier = {}
            blockers.append("per_order_confirmation_current_dossier_unavailable")
        if str(dossier.get("dossier_fingerprint") or "") != str(
            recorded.get("dossier_fingerprint") or ""
        ):
            blockers.append("per_order_confirmation_dossier_changed")
        if dossier.get("review_blockers"):
            blockers.append("per_order_confirmation_current_review_blocked")
        current_confirmation = _mapping(dossier.get("confirmation"))
        if str(current_confirmation.get("confirmation_id") or "") != normalized:
            blockers.append("per_order_confirmation_not_current")
        approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(recorded.get("operator_approval_id") or ""),
            expected_action="attest_per_order_dossier",
            expected_artifact_type="per_order_dossier",
            expected_artifact_fingerprint=str(
                recorded.get("dossier_fingerprint") or ""
            ),
            clock=self._clock,
        )
        if approval_blockers:
            blockers.append("per_order_confirmation_operator_approval_not_current")
        elif str(approval.get("operator_id") or "") != str(
            recorded.get("operator_label") or ""
        ):
            blockers.append("per_order_confirmation_operator_mismatch")
        hard_blockers = [
            str(item) for item in dossier.get("hard_submission_blockers") or []
        ]
        expected_foundation_blockers = {
            "operator_identity_unverified",
            "runtime_execution_authority_disabled",
            "live_gateway_not_implemented",
            "broker_submission_disabled",
        }
        unexpected_hard_blockers = [
            item for item in hard_blockers if item not in expected_foundation_blockers
        ]
        if unexpected_hard_blockers:
            blockers.append("per_order_confirmation_unexpected_hard_blockers")
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
            "status": (
                "current_verified_non_authorizing_confirmation"
                if not unique_blockers
                else "blocked"
            ),
            "confirmation_id": normalized,
            "order_id": order_id,
            "dossier_fingerprint": str(recorded.get("dossier_fingerprint") or ""),
            "capital_evaluation_input_fingerprint": capital_fingerprint,
            "prior_batch_reconciliation_fingerprint": prior_batch_fingerprint,
            "execution_gateway_verification_fingerprint": gateway_fingerprint,
            "operator_id": str(recorded.get("operator_label") or ""),
            "operator_approval_id": str(recorded.get("operator_approval_id") or ""),
            "current_dossier": dossier,
            "expected_foundation_blockers": sorted(expected_foundation_blockers),
            "unexpected_hard_blockers": unexpected_hard_blockers,
            "blockers": unique_blockers,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def list_confirmations(
        self,
        order_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            response = _event_response(row, reused=False)
            if str(response.get("order_id") or "") == str(order_id):
                results.append(response)
        return results

    def _require_order(self, order_id: str) -> dict[str, Any]:
        order = self._db.get_oms_order_sync(order_id)
        if order is None:
            raise KeyError(f"OMS order not found: {order_id}")
        return dict(order)

    def _capital_evaluation_summary(
        self,
        input_fingerprint: str,
        *,
        order: dict[str, Any],
        order_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprint: str,
        now: datetime,
    ) -> tuple[dict[str, Any], list[str]]:
        if not input_fingerprint:
            return _missing_capital_summary(), ["capital_evaluation_missing"]
        rows = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            entity_id=input_fingerprint,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return _missing_capital_summary(input_fingerprint), [
                "capital_evaluation_not_found"
            ]
        payload = _json_object(rows[0].get("payload_json"))
        policy = (
            payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        )
        context = (
            payload.get("context") if isinstance(payload.get("context"), dict) else {}
        )
        decision = (
            payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        )
        blockers: list[str] = []
        if not bool(decision.get("allowed")):
            blockers.append("capital_evaluation_not_allowed")
        if str(policy.get("mode") or "") != "manual_each_order":
            blockers.append("capital_mode_not_manual_each_order")
        if str(context.get("order_fingerprint") or "") != order_fingerprint:
            blockers.append("capital_order_fingerprint_mismatch")
        if (
            str(context.get("manual_confirmation_fingerprint") or "")
            != order_fingerprint
        ):
            blockers.append("capital_manual_confirmation_fingerprint_mismatch")
        if str(context.get("symbol") or "") != str(order.get("symbol") or ""):
            blockers.append("capital_symbol_mismatch")
        effective_at = _parse_timestamp(policy.get("effective_at"))
        expires_at = _parse_timestamp(policy.get("expires_at"))
        if effective_at is None or expires_at is None:
            blockers.append("capital_authorization_window_invalid")
        else:
            if now < effective_at:
                blockers.append("capital_authorization_not_yet_effective")
            if now >= expires_at:
                blockers.append("capital_authorization_expired")
        if str(decision.get("input_fingerprint") or "") != input_fingerprint:
            blockers.append("capital_evaluation_fingerprint_mismatch")
        expected_batch_ref = (
            "execution_batch_reconciliation:"
            f"{prior_batch_reconciliation_fingerprint}"
        )
        capital_refs = {
            str(item)
            for item in [
                *(context.get("evidence_refs") or []),
                *(decision.get("evidence_refs") or []),
            ]
        }
        if (
            not prior_batch_reconciliation_fingerprint
            or expected_batch_ref not in capital_refs
        ):
            blockers.append("capital_prior_batch_reconciliation_ref_mismatch")
        expected_gateway_ref = (
            "execution_gateway_verification:"
            f"{execution_gateway_verification_fingerprint}"
        )
        if (
            not execution_gateway_verification_fingerprint
            or expected_gateway_ref not in capital_refs
        ):
            blockers.append("capital_execution_gateway_verification_ref_mismatch")
        summary = {
            "status": "pass" if not blockers else "blocked",
            "input_fingerprint": input_fingerprint,
            "evaluation_id": int(rows[0]["id"]),
            "recorded_at": rows[0]["timestamp"],
            "authorization_id": str(policy.get("authorization_id") or ""),
            "policy_version": str(policy.get("policy_version") or ""),
            "mode": str(policy.get("mode") or ""),
            "calculation_allowed": bool(decision.get("allowed")),
            "effective_at": str(policy.get("effective_at") or ""),
            "expires_at": str(policy.get("expires_at") or ""),
            "scope": {
                "connector_id": str(context.get("connector_id") or ""),
                "evidence_connector_id": str(
                    context.get("evidence_connector_id") or ""
                ),
                "execution_gateway_id": str(context.get("execution_gateway_id") or ""),
                "account_alias": str(context.get("account_alias") or ""),
                "strategy_id": str(context.get("strategy_id") or ""),
                "symbol": str(context.get("symbol") or ""),
            },
            "connector_account_binding_status": str(
                context.get("connector_account_binding_status") or ""
            ),
            "evidence_connector_health_status": str(
                context.get("evidence_connector_health_status") or ""
            ),
            "evidence_connector_can_submit": bool(
                context.get("evidence_connector_can_submit")
            ),
            "execution_gateway_health_status": str(
                context.get("execution_gateway_health_status") or ""
            ),
            "execution_gateway_can_submit": bool(
                context.get("execution_gateway_can_submit")
            ),
            "effective_limits": _json_object(decision.get("effective_limits")),
            "remaining_budget": _json_object(decision.get("remaining_budget")),
            "evidence_refs": [
                str(item) for item in decision.get("evidence_refs") or []
            ],
            "blockers": blockers,
            "operator_identity_verified": False,
            "runtime_authority_status": "disabled",
            "does_not_enable_execution": True,
        }
        return summary, blockers

    def _soak_summary(
        self,
        connector_id: str,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        status = BrokerConnectorSoakService(
            db=self._db,
            connectors=self._connectors,
            clock=self._clock,
        ).get_status()
        signed_promotion = _resolve_signed_soak_promotion(
            self._broker_soak_promotion_evidence_provider,
            connector_id=connector_id,
        )
        summary = next(
            (
                item
                for item in status.get("connectors") or []
                if str(item.get("connector_id") or "") == connector_id
            ),
            None,
        )
        connector = next(
            (item for item in self._connectors if _connector_id(item) == connector_id),
            None,
        )
        capabilities = getattr(connector, "capabilities", None)
        can_submit = bool(getattr(capabilities, "can_submit_orders", False))
        latest_observation = (
            summary.get("latest_observation")
            if summary and isinstance(summary.get("latest_observation"), dict)
            else {}
        )
        source_captured_at = _parse_timestamp(
            latest_observation.get("source_captured_at")
        )
        current_age_seconds: int | None = None
        freshness_status = "missing"
        if source_captured_at is not None:
            age = (now - source_captured_at).total_seconds()
            current_age_seconds = int(max(0, age))
            if age < -300:
                freshness_status = "future"
            elif age > PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS:
                freshness_status = "stale"
            else:
                freshness_status = "fresh"
        result = {
            "connector_id": connector_id,
            "configured": connector is not None,
            "latest_soak_status": (
                str(summary.get("latest_soak_status") or "not_observed")
                if summary
                else "not_observed"
            ),
            "healthy_trading_day_count": (
                int(summary.get("healthy_trading_day_count") or 0) if summary else 0
            ),
            "operational_soak_complete": bool(
                summary and summary.get("operational_soak_complete")
            ),
            "account_truth_reconciliation_linked": bool(
                signed_promotion.get("account_truth_reconciliation_linked")
            ),
            "owner_acceptance_recorded": bool(
                signed_promotion.get("owner_acceptance_recorded")
            ),
            "promotion_ready": bool(signed_promotion.get("promotion_ready")),
            "signed_promotion": signed_promotion,
            "connector_can_submit": can_submit,
            "evidence_connector_can_submit": can_submit,
            "source_captured_at": (
                source_captured_at.isoformat() if source_captured_at else ""
            ),
            "current_age_seconds": current_age_seconds,
            "max_age_seconds": PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS,
            "freshness_status": freshness_status,
            "broker_contacted": False,
        }
        review_blockers: list[str] = []
        if not connector_id:
            review_blockers.append("capital_connector_id_missing")
        if connector is None:
            review_blockers.append("connector_not_configured")
        if summary is None:
            review_blockers.append("connector_soak_evidence_missing")
        elif result["latest_soak_status"] != "healthy":
            review_blockers.append("connector_latest_soak_not_healthy")
        if freshness_status != "fresh":
            review_blockers.append("connector_soak_evidence_not_fresh")
        hard_blockers: list[str] = []
        if not result["operational_soak_complete"]:
            hard_blockers.append("broker_soak_operational_evidence_incomplete")
        if not result["account_truth_reconciliation_linked"]:
            hard_blockers.append("broker_soak_account_truth_reconciliation_not_linked")
        if not result["owner_acceptance_recorded"]:
            hard_blockers.append("broker_soak_owner_acceptance_missing")
        if not result["promotion_ready"]:
            hard_blockers.append("broker_soak_promotion_not_ready")
        if can_submit:
            hard_blockers.append("evidence_connector_exposes_submit_capability")
        return result, review_blockers, hard_blockers

    def _reconciliation_summary(
        self,
        fingerprint: str,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_prior_batch_reconciliation(
            db=self._db,
            fingerprint=fingerprint,
        )

    def _kill_switch_summary(self) -> tuple[dict[str, Any], list[str]]:
        getter = getattr(self._trading_controls, "snapshot", None)
        if not callable(getter):
            return {
                "status": "unavailable",
                "enabled": None,
                "reason": "",
                "evidence_ref": "",
            }, ["kill_switch_status_unavailable"]
        snapshot = getter()
        enabled = bool(getattr(snapshot, "kill_switch_enabled", False))
        reason = str(getattr(snapshot, "reason", "") or "").strip()
        return {
            "status": "blocked" if enabled else "pass",
            "enabled": enabled,
            "reason": reason,
            "evidence_ref": (
                "trading_controls:kill_switch_enabled"
                if enabled
                else "trading_controls:kill_switch_clear"
            ),
        }, (["kill_switch_enabled"] if enabled else [])

    def _latest_matching_confirmation(
        self,
        order_id: str,
        *,
        dossier_fingerprint: str,
    ) -> dict[str, Any]:
        for item in self.list_confirmations(order_id, limit=100):
            if (
                item.get("status") == "recorded_verified_identity"
                and item.get("dossier_fingerprint") == dossier_fingerprint
            ):
                return {
                    "status": "recorded_verified_identity",
                    "confirmation_id": item.get("confirmation_id"),
                    "recorded_at": item.get("recorded_at"),
                    "operator_label": item.get("operator_label"),
                    "operator_identity_verified": True,
                    "authorizes_execution": False,
                }
        return {
            "status": "missing",
            "confirmation_id": "",
            "recorded_at": "",
            "operator_label": "",
            "operator_identity_verified": False,
            "authorizes_execution": False,
        }

    def _record_attempt(
        self,
        *,
        order_id: str,
        dossier: dict[str, Any],
        submitted_dossier_fingerprint: str,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprint: str,
        operator_label: str,
        operator_approval: dict[str, Any],
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        recorded_at = _aware_utc(self._clock())
        identity = {
            "order_id": order_id,
            "dossier_fingerprint": dossier["dossier_fingerprint"],
            "submitted_dossier_fingerprint": submitted_dossier_fingerprint,
            "capital_evaluation_input_fingerprint": (
                capital_evaluation_input_fingerprint
            ),
            "prior_batch_reconciliation_fingerprint": (
                prior_batch_reconciliation_fingerprint
            ),
            "execution_gateway_verification_fingerprint": (
                execution_gateway_verification_fingerprint
            ),
            "operator_label": operator_label,
            "operator_approval_id": operator_approval.get("approval_id"),
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": rejection_reasons,
        }
        confirmation_id = _fingerprint(identity)
        payload = {
            "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
            "confirmation_id": confirmation_id,
            **identity,
            "order_fingerprint": dossier["order_fingerprint"],
            "review_status": dossier["review_status"],
            "review_blockers": list(dossier["review_blockers"]),
            "hard_submission_blockers": [
                blocker
                for blocker in dossier["hard_submission_blockers"]
                if blocker != "operator_identity_unverified"
                or not operator_approval.get("operator_identity_verified")
            ],
            "operator_approval": operator_approval,
            "operator_identity_verified": bool(
                operator_approval.get("operator_identity_verified")
            ),
            "authorizes_execution": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        self._db.append_event_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            timestamp=recorded_at.isoformat(),
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            source_ref=order_id,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE,
            entity_type=PER_ORDER_CONFIRMATION_EVENT_ENTITY_TYPE,
            entity_id=confirmation_id,
            source=PER_ORDER_CONFIRMATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("per-order confirmation evidence was not recorded")
        return _event_response(saved[0], reused=False)


def _read_broker_adapter_readiness(db: Any) -> dict[str, Any]:
    """Read the canonical persisted-only projection and fail closed on defects."""

    try:
        readiness = build_broker_adapter_readiness(db)
    except Exception:  # Defensive boundary: an unreadable gate must never pass.
        return {}
    return readiness if isinstance(readiness, dict) else {}


def _resolve_broker_adapter_release_binding(
    readiness: dict[str, Any],
    *,
    expected_collector_id: str,
    expected_gateway_id: str,
    expected_account_alias: str,
) -> tuple[dict[str, Any], list[str]]:
    """Bind the newest exact-scope release that remains safe for observation."""

    blockers: list[str] = []
    expected_scope = {
        "collector_id": str(expected_collector_id or ""),
        "gateway_id": str(expected_gateway_id or ""),
        "account_alias": str(expected_account_alias or ""),
    }
    for field, value in expected_scope.items():
        if not value:
            blockers.append(f"broker_adapter_release_expected_{field}_missing")

    if (
        str(readiness.get("schema_version") or "")
        != BROKER_ADAPTER_READINESS_SCHEMA_VERSION
    ):
        blockers.append("broker_adapter_readiness_schema_invalid")
    if str(readiness.get("evidence_store_status") or "") != "available":
        blockers.append("broker_adapter_readiness_evidence_store_unavailable")

    required_safety = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_submission_enabled": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }
    source_safety = {field: readiness.get(field) for field in required_safety}
    for field, expected in required_safety.items():
        if readiness.get(field) is not expected:
            blockers.append(f"broker_adapter_readiness_boundary_invalid:{field}")

    releases_value = readiness.get("releases")
    releases = releases_value if isinstance(releases_value, list) else []
    if not isinstance(releases_value, list):
        blockers.append("broker_adapter_readiness_releases_invalid")
    if any(not isinstance(item, dict) for item in releases):
        blockers.append("broker_adapter_readiness_release_item_invalid")
    exact_matches = [
        item
        for item in releases
        if isinstance(item, dict)
        and str(item.get("collector_id") or "") == expected_scope["collector_id"]
        and str(item.get("gateway_id") or "") == expected_scope["gateway_id"]
        and str(item.get("account_alias") or "") == expected_scope["account_alias"]
    ]
    selected = exact_matches[0] if exact_matches else None
    if selected is None:
        blockers.append("broker_adapter_release_scope_not_found")

    release: dict[str, Any] | None = None
    if selected is not None:
        release_blockers_value = selected.get("blockers")
        release_blockers = (
            [str(item) for item in release_blockers_value]
            if isinstance(release_blockers_value, list)
            else []
        )
        if not isinstance(release_blockers_value, list):
            blockers.append("broker_adapter_release_blockers_invalid")
        elif release_blockers:
            blockers.append("broker_adapter_release_has_blockers")
        if not str(selected.get("release_evidence_ref") or ""):
            blockers.append("broker_adapter_release_evidence_ref_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(
            str(selected.get("manifest_fingerprint") or "")
        ):
            blockers.append("broker_adapter_release_manifest_fingerprint_invalid")
        if str(selected.get("manifest_status") or "") != "clear":
            blockers.append("broker_adapter_release_manifest_not_clear")
        if not str(selected.get("provider") or ""):
            blockers.append("broker_adapter_release_provider_missing")
        if str(selected.get("review_status") or "") != "accepted":
            blockers.append("broker_adapter_release_review_not_accepted")
        if not str(selected.get("review_id") or ""):
            blockers.append("broker_adapter_release_review_id_missing")
        if str(selected.get("conformance_status") or "") != "clear":
            blockers.append("broker_adapter_release_conformance_not_clear")
        if not str(selected.get("conformance_run_id") or ""):
            blockers.append("broker_adapter_release_conformance_run_id_missing")
        if not _FINGERPRINT_PATTERN.fullmatch(
            str(selected.get("conformance_report_fingerprint") or "")
        ):
            blockers.append("broker_adapter_release_conformance_fingerprint_invalid")
        if str(selected.get("collector_status") or "") not in {
            "recorded",
            "duplicate",
        }:
            blockers.append("broker_adapter_release_collector_not_recorded")
        if not str(selected.get("collector_run_id") or ""):
            blockers.append("broker_adapter_release_collector_run_id_missing")
        if not str(selected.get("collector_updated_at") or ""):
            blockers.append("broker_adapter_release_collector_updated_at_missing")
        if str(selected.get("status") or "") != "observing_readonly":
            blockers.append("broker_adapter_release_not_observing_readonly")
        if selected.get("does_not_authorize_provider_activation") is not True:
            blockers.append("broker_adapter_release_activation_boundary_invalid")
        release = {
            "release_evidence_ref": str(selected.get("release_evidence_ref") or ""),
            "manifest_fingerprint": str(selected.get("manifest_fingerprint") or ""),
            "manifest_status": str(selected.get("manifest_status") or ""),
            "provider": str(selected.get("provider") or ""),
            "gateway_id": str(selected.get("gateway_id") or ""),
            "account_alias": str(selected.get("account_alias") or ""),
            "collector_id": str(selected.get("collector_id") or ""),
            "collection_modes": [
                str(item) for item in selected.get("collection_modes") or []
            ],
            "review_status": str(selected.get("review_status") or ""),
            "review_id": str(selected.get("review_id") or ""),
            "reviewed_at": selected.get("reviewed_at"),
            "conformance_status": str(selected.get("conformance_status") or ""),
            "conformance_run_id": str(selected.get("conformance_run_id") or ""),
            "conformance_report_fingerprint": str(
                selected.get("conformance_report_fingerprint") or ""
            ),
            "collector_status": str(selected.get("collector_status") or ""),
            "collector_run_id": str(selected.get("collector_run_id") or ""),
            "collector_updated_at": selected.get("collector_updated_at"),
            "status": str(selected.get("status") or ""),
            "release_blockers": release_blockers,
            "does_not_authorize_provider_activation": bool(
                selected.get("does_not_authorize_provider_activation")
            ),
        }

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": "karkinos.per_order_broker_adapter_release_binding.v1",
        "status": "pass" if not blockers else "blocked",
        "source_schema_version": str(readiness.get("schema_version") or ""),
        "expected_scope": expected_scope,
        "matching_release_count": len(exact_matches),
        "release": release,
        "source_safety": source_safety,
        "blockers": blockers,
        "persisted_evidence_only": readiness.get("persisted_facts_only") is True,
        "provider_contact_performed": bool(readiness.get("provider_contacted")),
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }, blockers


def build_order_fingerprint(order: dict[str, Any]) -> str:
    """Return the canonical fingerprint used by per-order capital evidence."""

    return _fingerprint(_order_contract(order))


def _order_contract(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(order.get("order_id") or ""),
        "intent_key": str(order.get("intent_key") or ""),
        "symbol": str(order.get("symbol") or ""),
        "side": str(order.get("side") or "").lower(),
        "asset_class": str(order.get("asset_class") or ""),
        "quantity": _number_string(order.get("quantity")),
        "order_type": str(order.get("order_type") or "").lower(),
        "limit_price": (
            _number_string(order.get("limit_price"))
            if order.get("limit_price") is not None
            else None
        ),
        "source": str(order.get("source") or ""),
        "source_ref": str(order.get("source_ref") or ""),
    }


def _missing_capital_summary(input_fingerprint: str = "") -> dict[str, Any]:
    return {
        "status": "missing",
        "input_fingerprint": input_fingerprint,
        "evaluation_id": None,
        "recorded_at": "",
        "authorization_id": "",
        "policy_version": "",
        "mode": "",
        "calculation_allowed": False,
        "effective_at": "",
        "expires_at": "",
        "scope": {
            "connector_id": "",
            "account_alias": "",
            "strategy_id": "",
            "symbol": "",
        },
        "effective_limits": {},
        "remaining_budget": {},
        "evidence_refs": [],
        "blockers": ["capital_evaluation_missing"],
        "operator_identity_verified": False,
        "runtime_authority_status": "disabled",
        "does_not_enable_execution": True,
    }


def _missing_reconciliation_summary() -> dict[str, Any]:
    return {
        "status": "missing",
        "run_id": "",
        "run_date": "",
        "reconciliation_status": "not_available",
        "open_item_count": None,
        "evidence_ref": "",
    }


def _resolve_signed_soak_promotion(
    provider: Callable[[str], dict[str, Any]] | None,
    *,
    connector_id: str,
) -> dict[str, Any]:
    if not connector_id:
        return _missing_signed_soak_promotion(["connector_id_missing"])
    if provider is None:
        return _missing_signed_soak_promotion(
            ["signed_promotion_evidence_provider_unavailable"]
        )
    try:
        raw = provider(connector_id) or {}
    except Exception:
        return _missing_signed_soak_promotion(
            ["signed_promotion_evidence_provider_failed"]
        )
    if not isinstance(raw, dict):
        return _missing_signed_soak_promotion(["signed_promotion_evidence_invalid"])

    operational = (
        raw.get("operational_evidence")
        if isinstance(raw.get("operational_evidence"), dict)
        else {}
    )
    account_truth = (
        raw.get("account_truth_evidence")
        if isinstance(raw.get("account_truth_evidence"), dict)
        else {}
    )
    acceptance = (
        raw.get("acceptance") if isinstance(raw.get("acceptance"), dict) else {}
    )
    dossier_fingerprint = str(raw.get("dossier_fingerprint") or "")
    operational_source_fingerprint = str(operational.get("source_fingerprint") or "")
    account_truth_source_fingerprint = str(
        account_truth.get("source_fingerprint") or ""
    )
    acceptance_id = str(acceptance.get("acceptance_id") or "")
    blockers = [str(item) for item in raw.get("promotion_blockers") or []]
    if str(raw.get("connector_id") or "") != connector_id:
        blockers.append("signed_promotion_connector_mismatch")
    if operational.get("status") != "clear":
        blockers.append("signed_promotion_operational_evidence_not_clear")
    if int(operational.get("selected_trading_day_count") or 0) != 20:
        blockers.append("signed_promotion_trading_day_count_invalid")
    if account_truth.get("status") != "clear":
        blockers.append("signed_promotion_account_truth_not_clear")
    for name, fingerprint in (
        ("dossier", dossier_fingerprint),
        ("operational_source", operational_source_fingerprint),
        ("account_truth_source", account_truth_source_fingerprint),
    ):
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            blockers.append(f"signed_promotion_{name}_fingerprint_invalid")
    if acceptance.get("status") != "recorded_verified_owner_acceptance":
        blockers.append("signed_promotion_owner_acceptance_missing")
    if not re.fullmatch(r"[a-f0-9]{64}", acceptance_id):
        blockers.append("signed_promotion_acceptance_id_invalid")
    if acceptance.get("operator_identity_verified") is not True:
        blockers.append("signed_promotion_owner_identity_unverified")
    if acceptance.get("authorizes_execution") is not False:
        blockers.append("signed_promotion_acceptance_authority_boundary_invalid")
    if raw.get("owner_acceptance_recorded") is not True:
        blockers.append("signed_promotion_owner_acceptance_flag_invalid")
    if raw.get("account_truth_reconciliation_linked") is not True:
        blockers.append("signed_promotion_account_truth_linkage_flag_invalid")
    if raw.get("promotion_ready") is not True:
        blockers.append("signed_promotion_not_ready")
    if raw.get("authorizes_execution") is not False:
        blockers.append("signed_promotion_authority_boundary_invalid")
    if raw.get("broker_submission_enabled") is not False:
        blockers.append("signed_promotion_submission_boundary_invalid")

    unique_blockers = list(dict.fromkeys(blockers))
    ready = not unique_blockers
    return {
        "schema_version": "karkinos.per_order_broker_soak_promotion_binding.v1",
        "status": "ready" if ready else "blocked",
        "connector_id": connector_id,
        "dossier_fingerprint": dossier_fingerprint,
        "operational_source_fingerprint": operational_source_fingerprint,
        "account_truth_source_fingerprint": account_truth_source_fingerprint,
        "acceptance_id": acceptance_id,
        "acceptance_recorded_at": str(acceptance.get("recorded_at") or ""),
        "operator_label": str(acceptance.get("operator_label") or ""),
        "promotion_ready": ready,
        "owner_acceptance_recorded": ready,
        "account_truth_reconciliation_linked": ready,
        "blockers": unique_blockers,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }


def _missing_signed_soak_promotion(blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.per_order_broker_soak_promotion_binding.v1",
        "status": "blocked",
        "connector_id": "",
        "dossier_fingerprint": "",
        "operational_source_fingerprint": "",
        "account_truth_source_fingerprint": "",
        "acceptance_id": "",
        "acceptance_recorded_at": "",
        "operator_label": "",
        "promotion_ready": False,
        "owner_acceptance_recorded": False,
        "account_truth_reconciliation_linked": False,
        "blockers": list(dict.fromkeys(blockers)),
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }


def _connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **payload,
    }


def _blocked_confirmation_resolution(
    confirmation_id: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": PER_ORDER_CONFIRMATION_SCHEMA_VERSION,
        "status": "blocked",
        "confirmation_id": confirmation_id,
        "order_id": "",
        "blockers": list(dict.fromkeys(blockers)),
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "safety": _safety_flags(),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_grant_or_expand_capital_authority": True,
        "does_not_auto_resume": True,
    }


def _number_string(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
