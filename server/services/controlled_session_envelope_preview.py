"""Non-mutating envelope preview workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_ENVELOPE_SCHEMA_VERSION,
)
from server.services.controlled_session_envelope_policy import (
    budget_projection as _budget_projection,
)
from server.services.controlled_session_envelope_policy import (
    per_symbol_runtime_limit_summary as _per_symbol_runtime_limit_summary,
)
from server.services.controlled_session_envelope_policy import (
    time_and_request_blockers as _time_and_request_blockers,
)
from server.services.controlled_session_envelope_policy import (
    verification_reference_blockers as _verification_reference_blockers,
)
from server.services.controlled_session_envelope_values import aware_utc as _aware_utc
from server.services.controlled_session_envelope_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_envelope_values import is_aware as _is_aware
from server.services.controlled_session_envelope_values import (
    public_capital_summary as _public_capital_summary,
)
from server.services.controlled_session_envelope_values import (
    safety_flags as _safety_flags,
)


class ControlledSessionEnvelopePreviewMixin:
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
            self._build_execution_gateway_binding(
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
            self._resolve_session_start_account_truth_binding(
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
            prior_batch_reconciliation_fingerprint,
            expected_strategy_id=str(context.get("strategy_id") or ""),
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
