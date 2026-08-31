"""Provider-free preview orchestration for per-order confirmation dossiers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import server.services.per_order_confirmation_evidence as evidence
import server.services.per_order_confirmation_values as values
from server.contracts.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PER_ORDER_CONFIRMATION_MAX_SOAK_AGE_SECONDS,
    PER_ORDER_DOSSIER_SCHEMA_VERSION,
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
from server.services.execution_identity import build_order_contract
from server.services.per_order_gateway_evidence import (
    resolve_per_order_gateway_evidence,
)


class PerOrderConfirmationPreviewMixin:
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
            "safety": values.safety_flags(),
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
        now = values.aware_utc(self._clock())
        order_contract = build_order_contract(order)
        order_fingerprint = values.fingerprint(order_contract)
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
            evidence.resolve_broker_adapter_release_binding(
                evidence.read_broker_adapter_readiness(self._db),
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
            prior_batch_reconciliation_fingerprint,
            expected_strategy_id=str(scope.get("strategy_id") or ""),
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
        dossier_fingerprint = values.fingerprint(fingerprint_core)
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
            "safety": values.safety_flags(),
        }

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
            return values.missing_capital_summary(), ["capital_evaluation_missing"]
        rows = self._db.list_events_sync(
            event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE,
            entity_type=CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
            entity_id=input_fingerprint,
            source=CAPITAL_AUTHORIZATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            return values.missing_capital_summary(input_fingerprint), [
                "capital_evaluation_not_found"
            ]
        payload = values.json_object(rows[0].get("payload_json"))
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
        effective_at = values.parse_timestamp(policy.get("effective_at"))
        expires_at = values.parse_timestamp(policy.get("expires_at"))
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
            "effective_limits": values.json_object(decision.get("effective_limits")),
            "remaining_budget": values.json_object(decision.get("remaining_budget")),
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
        signed_promotion = evidence.resolve_signed_soak_promotion(
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
            (
                item
                for item in self._connectors
                if values.connector_id(item) == connector_id
            ),
            None,
        )
        capabilities = getattr(connector, "capabilities", None)
        can_submit = bool(getattr(capabilities, "can_submit_orders", False))
        latest_observation = (
            summary.get("latest_observation")
            if summary and isinstance(summary.get("latest_observation"), dict)
            else {}
        )
        source_captured_at = values.parse_timestamp(
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
        *,
        expected_strategy_id: str,
    ) -> tuple[dict[str, Any], list[str]]:
        return resolve_prior_batch_reconciliation(
            db=self._db,
            fingerprint=fingerprint,
            expected_strategy_id=expected_strategy_id,
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
