"""Non-executing session-bounded envelope proposals and attestations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

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
from server.services.per_order_confirmation import build_order_fingerprint
from server.services.session_start_account_truth import (
    resolve_session_start_account_truth_binding,
)

CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION = "karkinos.controlled_session_envelope.v5"
CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION = (
    "karkinos.controlled_session_attestation.v6"
)
CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE = "controlled_session.envelope_attested"
CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE = "controlled_session_attestation"
CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE = "controlled_session_envelope"
CONTROLLED_SESSION_ACKNOWLEDGEMENT = (
    "approve_exact_non_executing_session_envelope_for_review"
)
CONTROLLED_SESSION_MAX_DURATION_SECONDS = 30 * 60
CONTROLLED_SESSION_MAX_ORDER_COUNT = 50
CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS = 900

_REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, frozenset[str]]] = {
    "account_truth": ("gate_status", frozenset({"pass", "passed"})),
    "research_evidence": ("gate_status", frozenset({"pass", "passed"})),
    "risk": ("gate_status", frozenset({"pass", "passed"})),
    "paper_shadow": (
        "divergence_status",
        frozenset({"within_expectations"}),
    ),
}


class ControlledSessionAttestationRejected(ValueError):
    """Raised after an invalid session attestation has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionEnvelopeService:
    """Build bounded-session proposals without issuing runtime authority."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...] = (),
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        execution_gateway_verification_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        session_start_account_truth_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._trusted_operator_identities = list(trusted_operator_identities or [])
        self._trading_controls = trading_controls
        self._execution_gateway_verification_provider = (
            execution_gateway_verification_provider
        )
        self._session_start_account_truth_provider = (
            session_start_account_truth_provider
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.controlled_session_status.v5",
            "contract_status": "proposal_only_non_executing",
            "runtime_session_authority": "separate_signed_service_required",
            "session_issue_enabled": False,
            "separate_session_issue_endpoint_available": True,
            "session_enable_enabled": False,
            "session_pause_runtime_enabled": False,
            "session_resume_enabled": False,
            "session_revoke_runtime_enabled": True,
            "broker_submission_enabled": False,
            "operator_identity_verified": False,
            "signature_verification_configured": bool(
                self._trusted_operator_identities
            ),
            "automatic_scale_up_enabled": False,
            "exact_prior_batch_reconciliation_required": True,
            "per_order_gateway_verification_binding": "required_per_envelope",
            "session_start_account_truth_binding": "required_per_envelope",
            "per_symbol_runtime_limits": "required_explicit_map_per_envelope",
            "runtime_rate_limiter_foundation": ("implemented_internal_default_closed"),
            "maximum_proposal_duration_seconds": (
                CONTROLLED_SESSION_MAX_DURATION_SECONDS
            ),
            "maximum_proposal_order_count": CONTROLLED_SESSION_MAX_ORDER_COUNT,
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
            "safety": _safety_flags(),
        }

    def preview_envelope(
        self,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        per_symbol_runtime_limits: dict[str, Any],
        order_ids: list[str] | tuple[str, ...],
        requested_start_at: datetime,
        requested_expires_at: datetime,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        timezone_blockers: list[str] = []
        if not _is_aware(requested_start_at):
            timezone_blockers.append("session_start_timezone_missing")
        if not _is_aware(requested_expires_at):
            timezone_blockers.append("session_expiry_timezone_missing")
        start_at = _aware_utc(requested_start_at)
        expires_at = _aware_utc(requested_expires_at)
        requested_ids = [str(item or "").strip() for item in order_ids]
        normalized_ids = sorted({item for item in requested_ids if item})
        verification_fingerprints = {
            str(order_id or ""): str(fingerprint or "")
            for order_id, fingerprint in (
                execution_gateway_verification_fingerprints or {}
            ).items()
        }
        verification_reference_blockers = _verification_reference_blockers(
            normalized_ids,
            verification_fingerprints,
        )
        review_blockers = [
            *timezone_blockers,
            *_time_and_request_blockers(
                now=now,
                start_at=start_at,
                expires_at=expires_at,
                requested_ids=requested_ids,
                normalized_ids=normalized_ids,
            ),
            *verification_reference_blockers,
        ]
        capital, capital_blockers = self._capital_summary(
            capital_evaluation_input_fingerprint,
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(verification_fingerprints),
            session_start_account_truth_fingerprint=(
                session_start_account_truth_fingerprint
            ),
            now=now,
            requested_start_at=start_at,
            requested_expires_at=expires_at,
        )
        review_blockers.extend(capital_blockers)
        policy = (
            capital.get("policy") if isinstance(capital.get("policy"), dict) else {}
        )
        context = (
            capital.get("context") if isinstance(capital.get("context"), dict) else {}
        )
        orders, order_blockers = self._order_projections(
            normalized_ids,
            allowed_symbols=[str(item) for item in policy.get("symbols") or []],
        )
        review_blockers.extend(order_blockers)
        budget, budget_blockers = _budget_projection(
            orders=orders,
            policy=policy,
            context=context,
            decision=(
                capital.get("decision")
                if isinstance(capital.get("decision"), dict)
                else {}
            ),
            duration_seconds=max(0, int((expires_at - start_at).total_seconds())),
        )
        review_blockers.extend(budget_blockers)
        symbol_limits, symbol_limit_blockers = _per_symbol_runtime_limit_summary(
            requested_limits=per_symbol_runtime_limits,
            projected_by_symbol=(budget.get("projected_by_symbol") or {}),
            capital_decision=(
                capital.get("decision")
                if isinstance(capital.get("decision"), dict)
                else {}
            ),
        )
        review_blockers.extend(symbol_limit_blockers)

        connector_id = str(context.get("evidence_connector_id") or "")
        soak, soak_review_blockers, soak_hard_blockers = self._soak_summary(
            connector_id,
            now=now,
        )
        execution_gateway, execution_gateway_hard_blockers = (
            build_execution_gateway_binding(
                gateway_id=context.get("execution_gateway_id"),
                health_status=context.get("execution_gateway_health_status"),
                can_submit_orders=context.get("execution_gateway_can_submit"),
                account_binding_status=context.get("connector_account_binding_status"),
            )
        )
        gateway_verifications, gateway_verification_blockers = (
            self._gateway_verification_bindings(
                orders,
                verification_fingerprints=verification_fingerprints,
                context=context,
            )
        )
        all_gateway_verifications_clear = bool(normalized_ids) and (
            not verification_reference_blockers
            and not gateway_verification_blockers
            and len(gateway_verifications) == len(normalized_ids)
        )
        execution_gateway = {
            **execution_gateway,
            "runtime_verification_status": (
                "verified_non_submitting_dry_run"
                if all_gateway_verifications_clear
                else "blocked"
            ),
            "runtime_gateway_verified": all_gateway_verifications_clear,
            "verification_count": len(gateway_verifications),
            "required_verification_count": len(normalized_ids),
        }
        if all_gateway_verifications_clear:
            execution_gateway_hard_blockers = [
                blocker
                for blocker in execution_gateway_hard_blockers
                if blocker != "execution_gateway_runtime_not_verified"
            ]
        session_start_account_truth, account_truth_blockers = (
            resolve_session_start_account_truth_binding(
                self._session_start_account_truth_provider,
                fingerprint=session_start_account_truth_fingerprint,
                expected_evidence_connector_id=str(
                    context.get("evidence_connector_id") or ""
                ),
                expected_account_alias=str(context.get("account_alias") or ""),
            )
        )
        review_blockers.extend(soak_review_blockers)
        review_blockers.extend(gateway_verification_blockers)
        review_blockers.extend(account_truth_blockers)
        reconciliation, reconciliation_blockers = self._reconciliation_summary(
            prior_batch_reconciliation_fingerprint
        )
        review_blockers.extend(reconciliation_blockers)
        kill_switch, kill_switch_blockers = self._kill_switch_summary()
        review_blockers.extend(kill_switch_blockers)
        review_blockers = list(dict.fromkeys(review_blockers))

        hard_submission_blockers = list(
            dict.fromkeys(
                [
                    *soak_hard_blockers,
                    *execution_gateway_hard_blockers,
                    "per_order_controlled_bridge_not_promoted",
                    *(
                        []
                        if session_start_account_truth.get("status") == "pass"
                        else ["session_account_truth_snapshot_not_bound"]
                    ),
                    *(
                        []
                        if symbol_limits.get("status") == "pass"
                        else ["per_symbol_runtime_limits_not_bound"]
                    ),
                    *(
                        []
                        if reconciliation.get("status") == "pass"
                        else ["prior_batch_reconciliation_not_bound_or_clear"]
                    ),
                    "operator_identity_unverified",
                    "runtime_session_requires_separate_signed_issuance",
                    "atomic_budget_reservation_required_after_attestation",
                    "automatic_pause_controller_not_wired_to_live_gates",
                    "session_resume_requires_new_review_not_implemented",
                    "live_gateway_not_implemented",
                    "broker_submission_disabled",
                ]
            )
        )
        envelope_core = {
            "schema_version": CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION,
            "capital_evaluation": _public_capital_summary(capital),
            "requested_start_at": start_at.isoformat(),
            "requested_expires_at": expires_at.isoformat(),
            "duration_seconds": max(0, int((expires_at - start_at).total_seconds())),
            "order_ids": normalized_ids,
            "execution_gateway_verification_fingerprints": dict(
                sorted(verification_fingerprints.items())
            ),
            "orders": orders,
            "budget_projection": budget,
            "per_symbol_runtime_limits": symbol_limits,
            "connector_soak": soak,
            "execution_gateway": execution_gateway,
            "execution_gateway_verifications": gateway_verifications,
            "session_start_account_truth": session_start_account_truth,
            "prior_execution_reconciliation": reconciliation,
            "kill_switch": kill_switch,
            "review_blockers": review_blockers,
            "hard_submission_blockers": hard_submission_blockers,
        }
        fingerprint_core = {
            **envelope_core,
            "connector_soak": {
                key: value
                for key, value in soak.items()
                if key != "current_age_seconds"
            },
        }
        envelope_fingerprint = _fingerprint(fingerprint_core)
        return {
            **envelope_core,
            "envelope_fingerprint": envelope_fingerprint,
            "generated_at": now.isoformat(),
            "review_status": (
                "review_ready_non_executing"
                if not review_blockers
                else "blocked_review"
            ),
            "review_ready": not review_blockers,
            "runtime_session_status": "not_issued",
            "submission_status": "blocked",
            "attestation": self._latest_matching_attestation(envelope_fingerprint),
            "operator_identity_verified": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }

    def record_attestation(
        self,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        per_symbol_runtime_limits: dict[str, Any],
        order_ids: list[str] | tuple[str, ...],
        requested_start_at: datetime,
        requested_expires_at: datetime,
        envelope_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        envelope = self.preview_envelope(
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(
                execution_gateway_verification_fingerprints
            ),
            session_start_account_truth_fingerprint=(
                session_start_account_truth_fingerprint
            ),
            per_symbol_runtime_limits=per_symbol_runtime_limits,
            order_ids=order_ids,
            requested_start_at=requested_start_at,
            requested_expires_at=requested_expires_at,
        )
        rejection_reasons: list[str] = []
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != CONTROLLED_SESSION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if envelope_fingerprint != envelope["envelope_fingerprint"]:
            rejection_reasons.append("envelope_fingerprint_mismatch")
        if envelope["review_blockers"]:
            rejection_reasons.append("envelope_review_blocked")
        operator_approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            expected_action="attest_controlled_session_envelope",
            expected_artifact_type="controlled_session_envelope",
            expected_artifact_fingerprint=envelope["envelope_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append("operator_approval_blocked")
        elif str(operator_label or "").strip() != operator_approval["operator_id"]:
            rejection_reasons.append("operator_label_approval_mismatch")
        status = "rejected" if rejection_reasons else "recorded_verified_identity"
        attempt = self._record_attempt(
            envelope=envelope,
            submitted_envelope_fingerprint=envelope_fingerprint,
            capital_evaluation_input_fingerprint=(capital_evaluation_input_fingerprint),
            prior_batch_reconciliation_fingerprint=(
                prior_batch_reconciliation_fingerprint
            ),
            execution_gateway_verification_fingerprints=(
                execution_gateway_verification_fingerprints
            ),
            session_start_account_truth_fingerprint=(
                session_start_account_truth_fingerprint
            ),
            per_symbol_runtime_limits=per_symbol_runtime_limits,
            operator_label=str(operator_label or "").strip(),
            operator_approval=operator_approval,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise ControlledSessionAttestationRejected(
                "controlled session attestation rejected: "
                + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def list_attestations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def resolve_attestation(self, attestation_id: str) -> dict[str, Any]:
        """Re-resolve every mutable source behind one signed envelope."""
        normalized = str(attestation_id or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", normalized):
            return _blocked_attestation_resolution(
                normalized,
                ["controlled_session_attestation_id_invalid"],
            )
        rows = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=normalized,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return _blocked_attestation_resolution(
                normalized,
                ["controlled_session_attestation_not_found"],
            )
        recorded = _event_response(rows[0], reused=False)
        blockers: list[str] = []
        if recorded.get("schema_version") != (
            CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION
        ):
            blockers.append("controlled_session_attestation_schema_invalid")
        if recorded.get("status") != "recorded_verified_identity":
            blockers.append("controlled_session_attestation_not_verified")
        start_at = _parse_timestamp(recorded.get("requested_start_at"))
        expires_at = _parse_timestamp(recorded.get("requested_expires_at"))
        if start_at is None or expires_at is None:
            blockers.append("controlled_session_attestation_window_invalid")

        current_envelope: dict[str, Any] = {}
        if start_at is not None and expires_at is not None:
            try:
                current_envelope = self.preview_envelope(
                    capital_evaluation_input_fingerprint=str(
                        recorded.get("capital_evaluation_input_fingerprint") or ""
                    ),
                    prior_batch_reconciliation_fingerprint=str(
                        recorded.get("prior_batch_reconciliation_fingerprint") or ""
                    ),
                    execution_gateway_verification_fingerprints=(
                        recorded.get("execution_gateway_verification_fingerprints")
                        if isinstance(
                            recorded.get("execution_gateway_verification_fingerprints"),
                            dict,
                        )
                        else {}
                    ),
                    session_start_account_truth_fingerprint=str(
                        recorded.get("session_start_account_truth_fingerprint") or ""
                    ),
                    per_symbol_runtime_limits=(
                        recorded.get("per_symbol_runtime_limits")
                        if isinstance(recorded.get("per_symbol_runtime_limits"), dict)
                        else {}
                    ),
                    order_ids=[str(item) for item in recorded.get("order_ids") or []],
                    requested_start_at=start_at,
                    requested_expires_at=expires_at,
                )
            except Exception:
                blockers.append(
                    "controlled_session_attestation_source_resolution_failed"
                )
        if current_envelope:
            if current_envelope.get("envelope_fingerprint") != recorded.get(
                "envelope_fingerprint"
            ):
                blockers.append("controlled_session_envelope_source_changed")
            if current_envelope.get("review_blockers"):
                blockers.append("controlled_session_envelope_currently_blocked")

        operator_approval, approval_blockers = resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=str(recorded.get("operator_approval_id") or ""),
            expected_action="attest_controlled_session_envelope",
            expected_artifact_type="controlled_session_envelope",
            expected_artifact_fingerprint=str(
                recorded.get("envelope_fingerprint") or ""
            ),
            clock=self._clock,
        )
        if approval_blockers:
            blockers.append("controlled_session_operator_approval_blocked")
        elif str(recorded.get("operator_label") or "") != str(
            operator_approval.get("operator_id") or ""
        ):
            blockers.append("controlled_session_operator_identity_changed")
        unique_blockers = list(dict.fromkeys(blockers))
        if unique_blockers:
            return _blocked_attestation_resolution(normalized, unique_blockers)
        return {
            "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
            "status": "current_verified_non_executing",
            "attestation_id": normalized,
            "envelope_fingerprint": str(recorded["envelope_fingerprint"]),
            "operator_label": str(recorded.get("operator_label") or ""),
            "operator_approval_id": str(recorded.get("operator_approval_id") or ""),
            "recorded_at": str(recorded.get("recorded_at") or ""),
            "current_envelope": current_envelope,
            "blockers": [],
            "runtime_session_status": "not_issued",
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def _capital_summary(
        self,
        input_fingerprint: str,
        *,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        now: datetime,
        requested_start_at: datetime,
        requested_expires_at: datetime,
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
        if str(policy.get("mode") or "") != "session_bounded":
            blockers.append("capital_mode_not_session_bounded")
        effective_at = _parse_timestamp(policy.get("effective_at"))
        expires_at = _parse_timestamp(policy.get("expires_at"))
        if effective_at is None or expires_at is None:
            blockers.append("capital_authorization_window_invalid")
        else:
            if now < effective_at:
                blockers.append("capital_authorization_not_yet_effective")
            if now >= expires_at:
                blockers.append("capital_authorization_expired")
            if requested_start_at < effective_at:
                blockers.append("session_starts_before_capital_authorization")
            if requested_expires_at > expires_at:
                blockers.append("session_exceeds_capital_authorization_window")
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
        expected_gateway_refs = {
            f"execution_gateway_verification:{fingerprint}"
            for fingerprint in execution_gateway_verification_fingerprints.values()
        }
        recorded_gateway_refs = {
            ref
            for ref in capital_refs
            if ref.startswith("execution_gateway_verification:")
        }
        if expected_gateway_refs != recorded_gateway_refs:
            blockers.append("capital_execution_gateway_verification_refs_mismatch")
        expected_account_truth_ref = (
            "session_start_account_truth:" f"{session_start_account_truth_fingerprint}"
        )
        recorded_account_truth_refs = {
            ref
            for ref in capital_refs
            if ref.startswith("session_start_account_truth:")
        }
        if recorded_account_truth_refs != {expected_account_truth_ref}:
            blockers.append("capital_session_start_account_truth_ref_mismatch")
        summary = {
            "status": "pass" if not blockers else "blocked",
            "input_fingerprint": input_fingerprint,
            "evaluation_id": int(rows[0]["id"]),
            "recorded_at": rows[0]["timestamp"],
            "policy": policy,
            "context": context,
            "decision": decision,
            "blockers": blockers,
        }
        return summary, blockers

    def _order_projections(
        self,
        order_ids: list[str],
        *,
        allowed_symbols: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        blockers: list[str] = []
        for order_id in order_ids:
            order = self._db.get_oms_order_sync(order_id)
            if order is None:
                blockers.append(f"oms_order_not_found:{order_id}")
                continue
            order = dict(order)
            status = str(order.get("status") or "")
            if status not in {
                "awaiting_manual_confirmation",
                "manually_confirmed",
            }:
                blockers.append(f"oms_order_not_session_candidate:{order_id}")
            symbol = str(order.get("symbol") or "")
            if symbol not in allowed_symbols:
                blockers.append(f"order_symbol_not_authorized:{order_id}")
            quantity = _decimal(order.get("quantity"))
            price = _decimal(order.get("limit_price"))
            order_value: Decimal | None = None
            if quantity is None or quantity <= 0:
                blockers.append(f"order_quantity_invalid:{order_id}")
            if (
                str(order.get("order_type") or "").lower() != "limit"
                or price is None
                or price <= 0
            ):
                blockers.append(f"order_value_unavailable:{order_id}")
            elif quantity is not None and quantity > 0:
                order_value = abs(quantity * price)
            gateway_gates, gateway_blockers = _gateway_gate_summary(order)
            blockers.extend(f"{reason}:{order_id}" for reason in gateway_blockers)
            results.append(
                {
                    "order_id": order_id,
                    "order_fingerprint": build_order_fingerprint(order),
                    "symbol": symbol,
                    "side": str(order.get("side") or "").lower(),
                    "asset_class": str(order.get("asset_class") or "").lower(),
                    "quantity": _decimal_string(quantity),
                    "order_type": str(order.get("order_type") or "").lower(),
                    "limit_price": _decimal_string(price),
                    "projected_order_value": _decimal_string(order_value),
                    "oms_status": status,
                    "gateway_gates": gateway_gates,
                    "gateway_order_contract": (
                        build_execution_gateway_order_contract(order)
                    ),
                }
            )
        return results, list(dict.fromkeys(blockers))

    def _gateway_verification_bindings(
        self,
        orders: list[dict[str, Any]],
        *,
        verification_fingerprints: dict[str, str],
        context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        blockers: list[str] = []
        for order in orders:
            order_id = str(order.get("order_id") or "")
            binding, binding_blockers = resolve_execution_gateway_verification_binding(
                self._execution_gateway_verification_provider,
                fingerprint=verification_fingerprints.get(order_id, ""),
                expected_gateway_id=str(context.get("execution_gateway_id") or ""),
                expected_evidence_connector_id=str(
                    context.get("evidence_connector_id") or ""
                ),
                expected_account_alias=str(context.get("account_alias") or ""),
                expected_order_id=order_id,
                expected_order_fingerprint=str(order.get("order_fingerprint") or ""),
                expected_order_contract=(
                    order.get("gateway_order_contract")
                    if isinstance(order.get("gateway_order_contract"), dict)
                    else {}
                ),
            )
            results.append(binding)
            blockers.extend(f"{reason}:{order_id}" for reason in binding_blockers)
        return results, list(dict.fromkeys(blockers))

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
        latest = (
            summary.get("latest_observation")
            if summary and isinstance(summary.get("latest_observation"), dict)
            else {}
        )
        captured_at = _parse_timestamp(latest.get("source_captured_at"))
        age_seconds: int | None = None
        freshness = "missing"
        if captured_at is not None:
            age = (now - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -300:
                freshness = "future"
            elif age > CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS:
                freshness = "stale"
            else:
                freshness = "fresh"
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
            "promotion_ready": bool(status.get("promotion_ready")),
            "account_truth_reconciliation_linked": bool(
                status.get("account_truth_reconciliation_linked")
            ),
            "owner_acceptance_recorded": bool(status.get("owner_acceptance_recorded")),
            "connector_can_submit": can_submit,
            "evidence_connector_can_submit": can_submit,
            "source_captured_at": captured_at.isoformat() if captured_at else "",
            "current_age_seconds": age_seconds,
            "max_age_seconds": CONTROLLED_SESSION_MAX_SOAK_AGE_SECONDS,
            "freshness_status": freshness,
            "broker_contacted": False,
        }
        review: list[str] = []
        if not connector_id:
            review.append("capital_connector_id_missing")
        if connector is None:
            review.append("connector_not_configured")
        if summary is None:
            review.append("connector_soak_evidence_missing")
        elif result["latest_soak_status"] != "healthy":
            review.append("connector_latest_soak_not_healthy")
        if freshness != "fresh":
            review.append("connector_soak_evidence_not_fresh")
        hard: list[str] = []
        if not result["operational_soak_complete"]:
            hard.append("broker_soak_operational_evidence_incomplete")
        if not result["account_truth_reconciliation_linked"]:
            hard.append("broker_soak_account_truth_reconciliation_not_linked")
        if not result["owner_acceptance_recorded"]:
            hard.append("broker_soak_owner_acceptance_missing")
        if not result["promotion_ready"]:
            hard.append("broker_soak_promotion_not_ready")
        if can_submit:
            hard.append("evidence_connector_exposes_submit_capability")
        return result, review, hard

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
            }, ["kill_switch_status_unavailable"]
        snapshot = getter()
        enabled = bool(getattr(snapshot, "kill_switch_enabled", False))
        return {
            "status": "blocked" if enabled else "pass",
            "enabled": enabled,
            "reason": str(getattr(snapshot, "reason", "") or ""),
            "evidence_ref": (
                "trading_controls:kill_switch_enabled"
                if enabled
                else "trading_controls:kill_switch_clear"
            ),
        }, (["kill_switch_enabled"] if enabled else [])

    def _record_attempt(
        self,
        *,
        envelope: dict[str, Any],
        submitted_envelope_fingerprint: str,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        execution_gateway_verification_fingerprints: dict[str, str],
        session_start_account_truth_fingerprint: str,
        per_symbol_runtime_limits: dict[str, Any],
        operator_label: str,
        operator_approval: dict[str, Any],
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "envelope_fingerprint": envelope["envelope_fingerprint"],
            "submitted_envelope_fingerprint": submitted_envelope_fingerprint,
            "capital_evaluation_input_fingerprint": (
                capital_evaluation_input_fingerprint
            ),
            "prior_batch_reconciliation_fingerprint": (
                prior_batch_reconciliation_fingerprint
            ),
            "execution_gateway_verification_fingerprints": dict(
                sorted(
                    (
                        str(order_id or ""),
                        str(fingerprint or ""),
                    )
                    for order_id, fingerprint in (
                        execution_gateway_verification_fingerprints or {}
                    ).items()
                )
            ),
            "resolved_execution_gateway_verification_fingerprints": {
                str(item.get("order_id") or ""): str(
                    item.get("verification_fingerprint") or ""
                )
                for item in envelope.get("execution_gateway_verifications") or []
            },
            "session_start_account_truth_fingerprint": (
                session_start_account_truth_fingerprint
            ),
            "per_symbol_runtime_limits": {
                str(symbol): _decimal_string(_decimal(value))
                for symbol, value in sorted((per_symbol_runtime_limits or {}).items())
            },
            "resolved_session_start_account_truth_fingerprint": str(
                (envelope.get("session_start_account_truth") or {}).get(
                    "account_truth_fingerprint"
                )
                or ""
            ),
            "order_ids": list(envelope["order_ids"]),
            "requested_start_at": envelope["requested_start_at"],
            "requested_expires_at": envelope["requested_expires_at"],
            "operator_label": operator_label,
            "operator_approval_id": operator_approval.get("approval_id"),
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": rejection_reasons,
        }
        attestation_id = _fingerprint(identity)
        payload = {
            "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
            "attestation_id": attestation_id,
            **identity,
            "review_status": envelope["review_status"],
            "review_blockers": list(envelope["review_blockers"]),
            "hard_submission_blockers": [
                blocker
                for blocker in envelope["hard_submission_blockers"]
                if blocker != "operator_identity_unverified"
                or not operator_approval.get("operator_identity_verified")
            ],
            "operator_approval": operator_approval,
            "runtime_session_status": "not_issued",
            "operator_identity_verified": bool(
                operator_approval.get("operator_identity_verified")
            ),
            "authorizes_execution": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        now = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            source_ref=envelope["envelope_fingerprint"],
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
            entity_type=CONTROLLED_SESSION_ATTESTATION_ENTITY_TYPE,
            entity_id=attestation_id,
            source=CONTROLLED_SESSION_ATTESTATION_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("controlled session attestation was not recorded")
        return _event_response(saved[0], reused=False)

    def _latest_matching_attestation(
        self,
        envelope_fingerprint: str,
    ) -> dict[str, Any]:
        for item in self.list_attestations(limit=500):
            if (
                item.get("status") == "recorded_verified_identity"
                and item.get("envelope_fingerprint") == envelope_fingerprint
            ):
                return {
                    "status": "recorded_verified_identity",
                    "attestation_id": item.get("attestation_id"),
                    "recorded_at": item.get("recorded_at"),
                    "operator_label": item.get("operator_label"),
                    "operator_identity_verified": True,
                    "authorizes_execution": False,
                }
        return {
            "status": "missing",
            "attestation_id": "",
            "recorded_at": "",
            "operator_label": "",
            "operator_identity_verified": False,
            "authorizes_execution": False,
        }


def _time_and_request_blockers(
    *,
    now: datetime,
    start_at: datetime,
    expires_at: datetime,
    requested_ids: list[str],
    normalized_ids: list[str],
) -> list[str]:
    blockers: list[str] = []
    if not normalized_ids:
        blockers.append("session_order_set_empty")
    if len(normalized_ids) > CONTROLLED_SESSION_MAX_ORDER_COUNT:
        blockers.append("session_order_count_exceeded")
    if len(requested_ids) != len(normalized_ids):
        blockers.append("session_order_ids_invalid_or_duplicate")
    if start_at < now and (now - start_at).total_seconds() > 60:
        blockers.append("session_start_in_past")
    if start_at > now.replace(microsecond=0) and (start_at - now).total_seconds() > 300:
        blockers.append("session_start_too_far_in_future")
    duration = (expires_at - start_at).total_seconds()
    if duration <= 0:
        blockers.append("session_window_invalid")
    elif duration > CONTROLLED_SESSION_MAX_DURATION_SECONDS:
        blockers.append("session_duration_exceeded")
    return blockers


def _verification_reference_blockers(
    order_ids: list[str],
    verification_fingerprints: dict[str, str],
) -> list[str]:
    blockers: list[str] = []
    if set(verification_fingerprints) != set(order_ids):
        blockers.append("execution_gateway_verification_order_set_mismatch")
    for order_id, fingerprint in sorted(verification_fingerprints.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", order_id):
            blockers.append("execution_gateway_verification_order_id_invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            blockers.append(
                f"execution_gateway_verification_fingerprint_invalid:{order_id}"
            )
    values = list(verification_fingerprints.values())
    if len(set(values)) != len(values):
        blockers.append("execution_gateway_verification_fingerprint_reused")
    return list(dict.fromkeys(blockers))


def _per_symbol_runtime_limit_summary(
    *,
    requested_limits: dict[str, Any],
    projected_by_symbol: dict[str, Any],
    capital_decision: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    expected_symbols = {str(symbol) for symbol in projected_by_symbol}
    raw_limits = requested_limits if isinstance(requested_limits, dict) else {}
    submitted_symbols = {str(symbol) for symbol in raw_limits}
    blockers: list[str] = []
    if submitted_symbols != expected_symbols:
        blockers.append("per_symbol_runtime_limit_set_mismatch")
    effective_limits = (
        capital_decision.get("effective_limits")
        if isinstance(capital_decision.get("effective_limits"), dict)
        else {}
    )
    capital_symbol_ceiling = _decimal(effective_limits.get("symbol_capital_limit"))
    effective_capital = _decimal(effective_limits.get("effective_capital"))
    if capital_symbol_ceiling is None or capital_symbol_ceiling <= 0:
        blockers.append("capital_symbol_limit_missing_or_invalid")
    if effective_capital is None or effective_capital <= 0:
        blockers.append("capital_effective_limit_missing_or_invalid")
    ceiling = min(
        value
        for value in (
            capital_symbol_ceiling or Decimal("0"),
            effective_capital or Decimal("0"),
        )
    )
    results: dict[str, dict[str, str]] = {}
    canonical_limits: dict[str, str] = {}
    for raw_symbol, raw_limit in sorted(raw_limits.items()):
        symbol = str(raw_symbol)
        if symbol != symbol.strip() or not symbol:
            blockers.append("per_symbol_runtime_limit_symbol_invalid")
        limit = _decimal(raw_limit)
        projected = _decimal(projected_by_symbol.get(symbol))
        if limit is None or limit <= 0:
            blockers.append(f"per_symbol_runtime_limit_invalid:{symbol}")
            continue
        canonical_limits[symbol] = _decimal_string(limit)
        if ceiling <= 0 or limit > ceiling:
            blockers.append(f"per_symbol_runtime_limit_exceeds_cap:{symbol}")
        if projected is None or projected < 0:
            blockers.append(f"per_symbol_projection_invalid:{symbol}")
            projected = Decimal("0")
        if projected > limit:
            blockers.append(f"per_symbol_runtime_limit_projection_exceeded:{symbol}")
        results[symbol] = {
            "limit_value": _decimal_string(limit),
            "projected_gross_value": _decimal_string(projected),
            "remaining_after_projection": _decimal_string(
                max(Decimal("0"), limit - projected)
            ),
        }
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "status": "pass" if not unique_blockers else "blocked",
        "calculation_mode": "explicit_signed_map_capped_by_capital_evaluation",
        "capital_symbol_ceiling": _decimal_string(ceiling),
        "requested_limits": canonical_limits,
        "symbols": results,
        "blockers": unique_blockers,
        "authorizes_execution": False,
    }, unique_blockers


def _budget_projection(
    *,
    orders: list[dict[str, Any]],
    policy: dict[str, Any],
    context: dict[str, Any],
    decision: dict[str, Any],
    duration_seconds: int,
) -> tuple[dict[str, Any], list[str]]:
    limits = policy.get("limits") if isinstance(policy.get("limits"), dict) else {}
    values: list[tuple[dict[str, Any], Decimal]] = []
    blockers: list[str] = []
    for order in orders:
        value = _decimal(order.get("projected_order_value"))
        if value is not None and value > 0:
            values.append((order, value))
    gross = sum((value for _, value in values), Decimal("0"))
    buy_value = sum(
        (value for order, value in values if order.get("side") == "buy"),
        Decimal("0"),
    )
    sell_value = sum(
        (value for order, value in values if order.get("side") == "sell"),
        Decimal("0"),
    )
    max_order_value = _decimal(limits.get("max_order_value")) or Decimal("0")
    max_position_change = _decimal(limits.get("max_position_change_value")) or Decimal(
        "0"
    )
    max_daily_turnover = _decimal(limits.get("max_daily_turnover")) or Decimal("0")
    effective_limits = (
        decision.get("effective_limits")
        if isinstance(decision.get("effective_limits"), dict)
        else {}
    )
    effective_capital = _decimal(effective_limits.get("effective_capital")) or Decimal(
        "0"
    )
    current_exposure = _decimal(context.get("current_authorized_exposure")) or Decimal(
        "0"
    )
    daily_turnover_used = _decimal(context.get("daily_turnover_used")) or Decimal("0")
    available_cash = _decimal(context.get("available_cash")) or Decimal("0")
    liquidity_limit = _decimal(context.get("liquidity_capital_limit")) or Decimal("0")
    for order, value in values:
        order_id = str(order.get("order_id") or "")
        if max_order_value <= 0 or value > max_order_value:
            blockers.append(f"session_order_value_exceeded:{order_id}")
        if max_position_change <= 0 or value > max_position_change:
            blockers.append(f"session_position_change_exceeded:{order_id}")
        if liquidity_limit <= 0 or value > liquidity_limit:
            blockers.append(f"session_liquidity_limit_exceeded:{order_id}")
    if effective_capital <= 0 or current_exposure + gross > effective_capital:
        blockers.append("session_authorized_capital_exceeded")
    if max_daily_turnover <= 0 or daily_turnover_used + gross > max_daily_turnover:
        blockers.append("session_daily_turnover_exceeded")
    if available_cash <= 0 or buy_value > available_cash:
        blockers.append("session_available_cash_exceeded")
    max_rate = int(limits.get("max_order_rate_per_minute") or 0)
    duration_minutes = max(1, math.ceil(duration_seconds / 60))
    projected_rate_capacity = max_rate * duration_minutes
    if max_rate <= 0 or len(orders) > projected_rate_capacity:
        blockers.append("session_projected_order_rate_exceeded")
    by_symbol: dict[str, Decimal] = {}
    for order, value in values:
        symbol = str(order.get("symbol") or "")
        by_symbol[symbol] = by_symbol.get(symbol, Decimal("0")) + value
    return {
        "calculation_mode": "conservative_gross_without_buy_sell_netting",
        "order_count": len(orders),
        "priced_order_count": len(values),
        "projected_gross_order_value": _decimal_string(gross),
        "projected_buy_value": _decimal_string(buy_value),
        "projected_sell_value": _decimal_string(sell_value),
        "projected_by_symbol": {
            symbol: _decimal_string(value)
            for symbol, value in sorted(by_symbol.items())
        },
        "effective_capital": _decimal_string(effective_capital),
        "current_authorized_exposure": _decimal_string(current_exposure),
        "remaining_authorized_capital_after_projection": _decimal_string(
            max(Decimal("0"), effective_capital - current_exposure - gross)
        ),
        "available_cash": _decimal_string(available_cash),
        "remaining_cash_after_projected_buys": _decimal_string(
            max(Decimal("0"), available_cash - buy_value)
        ),
        "daily_turnover_used": _decimal_string(daily_turnover_used),
        "remaining_daily_turnover_after_projection": _decimal_string(
            max(Decimal("0"), max_daily_turnover - daily_turnover_used - gross)
        ),
        "max_order_rate_per_minute": max_rate,
        "duration_minutes": duration_minutes,
        "projected_rate_capacity": projected_rate_capacity,
        "reserved": False,
        "does_not_consume_runtime_budget": True,
    }, list(dict.fromkeys(blockers))


def _gateway_gate_summary(
    order: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    payload = _order_payload(order)
    evidence = payload.get("gateway_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    gates: dict[str, Any] = {}
    blockers: list[str] = []
    for gate, (status_field, passing_values) in _REQUIRED_GATEWAY_EVIDENCE.items():
        item = evidence.get(gate)
        item = item if isinstance(item, dict) else {}
        raw_status = str(item.get(status_field) or "").lower()
        evidence_ref = str(item.get("evidence_ref") or "")
        passed = bool(evidence_ref) and raw_status in passing_values
        gates[gate] = {
            "status": "pass" if passed else (raw_status or "missing"),
            "evidence_ref": evidence_ref,
        }
        if not evidence_ref:
            blockers.append(f"gateway_evidence_missing:{gate}")
        elif not passed:
            blockers.append(f"gateway_evidence_not_passing:{gate}")
    return {
        "status": "pass" if not blockers else "blocked",
        "gates": gates,
    }, blockers


def _public_capital_summary(capital: dict[str, Any]) -> dict[str, Any]:
    policy = capital.get("policy") if isinstance(capital.get("policy"), dict) else {}
    context = capital.get("context") if isinstance(capital.get("context"), dict) else {}
    decision = (
        capital.get("decision") if isinstance(capital.get("decision"), dict) else {}
    )
    return {
        "status": str(capital.get("status") or "missing"),
        "input_fingerprint": str(capital.get("input_fingerprint") or ""),
        "evaluation_id": capital.get("evaluation_id"),
        "recorded_at": str(capital.get("recorded_at") or ""),
        "authorization_id": str(policy.get("authorization_id") or ""),
        "policy_version": str(policy.get("policy_version") or ""),
        "mode": str(policy.get("mode") or ""),
        "effective_at": str(policy.get("effective_at") or ""),
        "expires_at": str(policy.get("expires_at") or ""),
        "scope": {
            "connector_id": str(context.get("connector_id") or ""),
            "evidence_connector_id": str(context.get("evidence_connector_id") or ""),
            "execution_gateway_id": str(context.get("execution_gateway_id") or ""),
            "account_alias": str(context.get("account_alias") or ""),
            "strategy_id": str(context.get("strategy_id") or ""),
            "symbols": [str(item) for item in policy.get("symbols") or []],
        },
        "effective_limits": (
            decision.get("effective_limits")
            if isinstance(decision.get("effective_limits"), dict)
            else {}
        ),
        "remaining_budget": (
            decision.get("remaining_budget")
            if isinstance(decision.get("remaining_budget"), dict)
            else {}
        ),
        "calculation_allowed": bool(decision.get("allowed")),
        "blockers": [str(item) for item in capital.get("blockers") or []],
        "operator_identity_verified": False,
        "runtime_session_authority": "disabled",
    }


def _missing_capital_summary(input_fingerprint: str = "") -> dict[str, Any]:
    return {
        "status": "missing",
        "input_fingerprint": input_fingerprint,
        "evaluation_id": None,
        "recorded_at": "",
        "policy": {},
        "context": {},
        "decision": {},
        "blockers": ["capital_evaluation_missing"],
    }


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("payload")
    if isinstance(value, dict):
        return value
    return _json_object(order.get("payload_json"))


def _connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


def _blocked_attestation_resolution(
    attestation_id: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_ATTESTATION_SCHEMA_VERSION,
        "status": "blocked",
        "attestation_id": attestation_id,
        "envelope_fingerprint": "",
        "operator_label": "",
        "operator_approval_id": "",
        "recorded_at": "",
        "current_envelope": {},
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_session_status": "not_issued",
        "operator_identity_verified": False,
        "authorizes_execution": False,
        "broker_submission_enabled": False,
        "safety": _safety_flags(),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_or_enable_runtime_session": True,
        "does_not_consume_or_reserve_runtime_budget": True,
        "does_not_auto_resume_renew_or_expand": True,
        "does_not_grant_or_scale_capital_authority": True,
    }


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


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


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


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
