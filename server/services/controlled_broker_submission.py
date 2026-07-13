"""One-shot, human-signed broker submission with query-only recovery."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.execution_gateway_verification_binding import (
    build_execution_gateway_order_contract,
)
from server.services.operator_approval import resolve_operator_approval_with_proof
from server.services.per_order_confirmation import build_order_fingerprint

CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION = "karkinos.controlled_broker_submission.v1"
CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_submission_status.v1"
)
CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT = (
    "submit_one_exact_manually_confirmed_order_once"
)
CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE = (
    "controlled_broker.submission_rejected"
)
CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE = (
    "controlled_broker_submission_rejection"
)
CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE = "controlled_broker_submission"
CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS = 30
CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS = 60

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_CAPABILITIES = (
    "can_cancel_orders",
    "can_dry_run_orders",
    "can_query_orders",
    "can_submit_orders",
    "supports_idempotent_client_order_id",
)
_REQUIRED_RELEASE_ASSERTIONS = (
    "broker_agreement_reviewed",
    "connector_tested",
    "program_trading_reporting_reviewed",
    "risk_controls_reviewed",
)
_GATEWAY_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "rejected",
        "not_found",
        "gateway_unavailable_after_prepare",
        "gateway_submit_exception",
        "gateway_query_exception",
    }
)


class ControlledBrokerSubmissionRejected(ValueError):
    """Raised after a rejected one-shot submission attempt is audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledBrokerSubmissionService:
    """Submit one exact order only after fresh human and operational evidence."""

    def __init__(
        self,
        *,
        db: Any,
        gateways: list[Any] | tuple[Any, ...] = (),
        confirmation_provider: Callable[[str], dict[str, Any]] | None = None,
        release_evidence_provider: Callable[[str], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        trading_controls: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateways = list(gateways or [])
        self._confirmation_provider = confirmation_provider
        self._release_evidence_provider = release_evidence_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._trading_controls = trading_controls
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        gateway_ids = [
            str(getattr(gateway, "gateway_id", "") or "")
            for gateway in self._gateways
            if str(getattr(gateway, "gateway_id", "") or "")
        ]
        duplicates = sorted(
            item for item in set(gateway_ids) if gateway_ids.count(item) > 1
        )
        dependencies_ready = bool(
            gateway_ids
            and not duplicates
            and callable(self._confirmation_provider)
            and callable(self._release_evidence_provider)
            and self._trusted_operator_identities
            and self._trading_controls is not None
        )
        interlock = self._submission_interlock()
        return {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "disabled_waiting_for_explicit_write_gateway_and_release_evidence"
                if not dependencies_ready
                else (
                    "blocked_by_unreconciled_controlled_submission"
                    if interlock["blocked"]
                    else "one_shot_manual_submission_available"
                )
            ),
            "registered_gateway_ids": sorted(set(gateway_ids)),
            "duplicate_gateway_ids": duplicates,
            "confirmation_provider_configured": callable(self._confirmation_provider),
            "release_evidence_provider_configured": callable(
                self._release_evidence_provider
            ),
            "trusted_operator_signature_configured": bool(
                self._trusted_operator_identities
            ),
            "kill_switch_provider_configured": self._trading_controls is not None,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "recovery_resubmission_enabled": False,
            "recovery_minimum_wait_seconds": (
                CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS
            ),
            "submission_interlock": interlock,
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        order_id: str,
        confirmation_id: str,
        release_evidence_id: str,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_order_id = str(order_id or "").strip()
        normalized_confirmation_id = str(confirmation_id or "").strip().lower()
        normalized_release_id = str(release_evidence_id or "").strip().lower()
        blockers: list[str] = []
        if not _ID_PATTERN.fullmatch(normalized_order_id):
            blockers.append("controlled_broker_submit_order_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_confirmation_id):
            blockers.append("controlled_broker_submit_confirmation_id_invalid")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_release_id):
            blockers.append("controlled_broker_submit_release_evidence_id_invalid")

        interlock = self._submission_interlock(exclude_order_id=normalized_order_id)
        if interlock["blocked"]:
            blockers.append("controlled_broker_submit_unreconciled_intent_exists")

        order = self._db.get_oms_order_sync(normalized_order_id) or {}
        if not order:
            blockers.append("controlled_broker_submit_order_not_found")
        elif str(order.get("status") or "") != "manually_confirmed":
            blockers.append("controlled_broker_submit_order_not_manually_confirmed")
        order_payload = _json_object(order.get("payload_json"))
        if str(order_payload.get("execution_mode") or "").lower() == "paper_shadow":
            blockers.append("controlled_broker_submit_simulated_order_forbidden")
        order_fingerprint = build_order_fingerprint(order) if order else ""
        order_contract = build_execution_gateway_order_contract(order)

        confirmation = self._resolve_provider(
            self._confirmation_provider,
            normalized_confirmation_id,
            unavailable="controlled_broker_submit_confirmation_provider_unavailable",
            failed="controlled_broker_submit_confirmation_provider_failed",
            blockers=blockers,
        )
        if confirmation.get("status") != (
            "current_verified_non_authorizing_confirmation"
        ):
            blockers.append("controlled_broker_submit_confirmation_not_current")
            blockers.extend(
                f"confirmation:{item}" for item in confirmation.get("blockers") or []
            )
        if str(confirmation.get("confirmation_id") or "") != (
            normalized_confirmation_id
        ):
            blockers.append("controlled_broker_submit_confirmation_identity_mismatch")
        if str(confirmation.get("order_id") or "") != normalized_order_id:
            blockers.append("controlled_broker_submit_confirmation_order_mismatch")
        dossier = _mapping(confirmation.get("current_dossier"))
        if str(dossier.get("order_fingerprint") or "") != order_fingerprint:
            blockers.append("controlled_broker_submit_order_fingerprint_changed")
        gateway_verification = _mapping(dossier.get("execution_gateway_verification"))
        capital = _mapping(dossier.get("capital_evaluation"))
        scope = _mapping(capital.get("scope"))
        gateway_id = str(gateway_verification.get("gateway_id") or "")
        account_alias = str(scope.get("account_alias") or "")
        gateway_verification_fingerprint = str(
            gateway_verification.get("verification_fingerprint") or ""
        )
        if gateway_verification.get("status") != "pass":
            blockers.append("controlled_broker_submit_gateway_verification_not_clear")
        if gateway_verification.get("runtime_gateway_verified") is not True:
            blockers.append("controlled_broker_submit_gateway_not_verified")

        release = self._resolve_release(
            normalized_release_id,
            expected_gateway_id=gateway_id,
            expected_account_alias=account_alias,
            now=now,
        )
        blockers.extend(release["blockers"])
        gateway, gateway_blockers = self._gateway(gateway_id)
        blockers.extend(gateway_blockers)
        capabilities, capability_blockers = _capabilities(gateway)
        blockers.extend(capability_blockers)
        health, health_blockers = _health(gateway, now=now)
        blockers.extend(health_blockers)
        kill_switch = self._kill_switch()
        if kill_switch["enabled"] is not False:
            blockers.append("controlled_broker_submit_kill_switch_enabled")

        client_order_id = _client_order_id(
            order_id=normalized_order_id,
            order_fingerprint=order_fingerprint,
            confirmation_id=normalized_confirmation_id,
            release_evidence_fingerprint=release["evidence_fingerprint"],
        )
        gateway_order = {
            **order_contract,
            "order_id": normalized_order_id,
            "order_fingerprint": order_fingerprint,
            "client_order_id": client_order_id,
        }
        dry_run, dry_run_blockers = _dry_run(gateway, gateway_order)
        blockers.extend(dry_run_blockers)
        submission_core = {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
            "action": "submit_confirmed_broker_order",
            "order_id": normalized_order_id,
            "order_fingerprint": order_fingerprint,
            "order_contract": order_contract,
            "confirmation_id": normalized_confirmation_id,
            "dossier_fingerprint": str(confirmation.get("dossier_fingerprint") or ""),
            "gateway_id": gateway_id,
            "gateway_verification_fingerprint": (gateway_verification_fingerprint),
            "gateway_health_source_fingerprint": health["source_fingerprint"],
            "dry_run_payload_fingerprint": dry_run["payload_fingerprint"],
            "release_evidence_id": normalized_release_id,
            "release_evidence_fingerprint": release["evidence_fingerprint"],
            "client_order_id": client_order_id,
            "operator_id": str(confirmation.get("operator_id") or ""),
            "account_alias": account_alias,
        }
        submit_fingerprint = _fingerprint(submission_core)
        submit_intent_id = _fingerprint(
            {
                "domain": "karkinos.controlled_broker.submit_intent_id.v1",
                "submit_fingerprint": submit_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **submission_core,
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "generated_at": now.isoformat(),
            "status": "ready_for_final_signature" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "gateway_capabilities": capabilities,
            "gateway_health": health,
            "dry_run": dry_run,
            "release_evidence": release,
            "kill_switch": kill_switch,
            "submission_interlock": interlock,
            "required_operator_approval": {
                "action": "submit_confirmed_broker_order",
                "artifact_type": "controlled_broker_submission",
                "artifact_fingerprint": submit_fingerprint,
            },
            "submitted_to_broker": False,
            "default_broker_submission_enabled": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "production_ledger_mutated": False,
            "safety": _safety_flags(),
        }

    def submit(
        self,
        *,
        order_id: str,
        confirmation_id: str,
        release_evidence_id: str,
        submit_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        existing = self._db.get_controlled_broker_submit_intent_for_order_sync(order_id)
        if existing is not None:
            if (
                str(existing.get("submit_fingerprint") or "") == submit_fingerprint
                and str(existing.get("confirmation_id") or "") == confirmation_id
                and str(existing.get("release_evidence_id") or "")
                == release_evidence_id
            ):
                return _intent_response(
                    existing,
                    reused=True,
                    external_call_performed=False,
                )
            raise ControlledBrokerSubmissionRejected(
                "controlled broker submission retry conflicts with persisted intent",
                evidence={
                    "status": "rejected",
                    "order_id": order_id,
                    "submit_intent_id": str(existing.get("submit_intent_id") or ""),
                    "blockers": ["controlled_broker_submit_retry_conflict"],
                    "submitted_to_broker": False,
                    "production_ledger_mutated": False,
                },
            )
        preview = self.preview(
            order_id=order_id,
            confirmation_id=confirmation_id,
            release_evidence_id=release_evidence_id,
        )
        rejection_reasons: list[str] = []
        if submit_fingerprint != preview["submit_fingerprint"]:
            rejection_reasons.append("controlled_broker_submit_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_broker_submit_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_broker_submit_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="submit_confirmed_broker_order",
            expected_artifact_type="controlled_broker_submission",
            expected_artifact_fingerprint=preview["submit_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_broker_submit_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append("controlled_broker_submit_operator_mismatch")
        if rejection_reasons:
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=submit_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise ControlledBrokerSubmissionRejected(
                "controlled broker submission rejected",
                evidence=evidence,
            )

        now = _aware_utc(self._clock())
        order = self._db.get_oms_order_sync(preview["order_id"]) or {}
        payload = {
            **{
                key: preview[key]
                for key in (
                    "schema_version",
                    "submit_intent_id",
                    "submit_fingerprint",
                    "order_id",
                    "order_fingerprint",
                    "order_contract",
                    "confirmation_id",
                    "dossier_fingerprint",
                    "gateway_id",
                    "gateway_verification_fingerprint",
                    "release_evidence_id",
                    "release_evidence_fingerprint",
                    "client_order_id",
                    "operator_id",
                    "account_alias",
                )
            },
            "operator_approval_id": operator_approval_id,
            "status": "prepared",
            "external_call_count": 0,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
            "production_ledger_mutated": False,
        }
        transaction = self._db.prepare_controlled_broker_submit_intent_sync(
            intent={
                **{
                    key: payload[key]
                    for key in (
                        "submit_intent_id",
                        "submit_fingerprint",
                        "order_id",
                        "order_fingerprint",
                        "confirmation_id",
                        "dossier_fingerprint",
                        "gateway_id",
                        "gateway_verification_fingerprint",
                        "release_evidence_id",
                        "release_evidence_fingerprint",
                        "client_order_id",
                        "operator_id",
                        "operator_approval_id",
                    )
                },
                "order_snapshot": {
                    key: order.get(key)
                    for key in (
                        "symbol",
                        "side",
                        "asset_class",
                        "quantity",
                        "order_type",
                        "limit_price",
                    )
                },
                "prepared_at_epoch_ms": int(now.timestamp() * 1000),
                "prepared_at": now.isoformat(),
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") == "rejected":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=submit_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_broker_submit_prepare_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise ControlledBrokerSubmissionRejected(
                "controlled broker submit intent rejected",
                evidence=evidence,
            )
        if not transaction.get("external_call_permitted"):
            return _intent_response(
                transaction.get("intent") or {},
                reused=True,
                external_call_performed=False,
            )

        pre_call_blockers = self._pre_call_blockers(preview)
        if pre_call_blockers:
            finalized = self._finalize(
                submit_intent_id=preview["submit_intent_id"],
                classification="rejected",
                result={
                    "status": "rejected_before_gateway_call",
                    "blockers": pre_call_blockers,
                    "submitted": False,
                },
                recovered=False,
            )
            return _intent_response(
                finalized.get("intent") or {},
                reused=False,
                external_call_performed=False,
            )

        gateway, gateway_blockers = self._gateway(preview["gateway_id"])
        if gateway_blockers:
            classification = "submission_unknown"
            raw_result = {
                "status": "gateway_unavailable_after_prepare",
                "submitted": None,
            }
            external_call_performed = False
        else:
            submitter = getattr(gateway, "submit_order", None)
            external_call_performed = callable(submitter)
            try:
                raw_result = (
                    submitter(
                        {
                            **preview["order_contract"],
                            "order_id": preview["order_id"],
                            "order_fingerprint": preview["order_fingerprint"],
                            "client_order_id": preview["client_order_id"],
                            "submit_intent_id": preview["submit_intent_id"],
                        }
                    )
                    if callable(submitter)
                    else {}
                )
                raw_result = raw_result if isinstance(raw_result, dict) else {}
                classification = _classify_gateway_result(
                    raw_result,
                    client_order_id=preview["client_order_id"],
                    order_fingerprint=preview["order_fingerprint"],
                    allow_definitive_not_found=False,
                )
            except Exception as exc:
                classification = "submission_unknown"
                raw_result = {
                    "status": "gateway_submit_exception",
                    "error_type": type(exc).__name__,
                    "submitted": None,
                }
        finalized = self._finalize(
            submit_intent_id=preview["submit_intent_id"],
            classification=classification,
            result=_sanitize_gateway_result(raw_result),
            recovered=False,
        )
        return _intent_response(
            finalized.get("intent") or {},
            reused=False,
            external_call_performed=external_call_performed,
        )

    def recover(self, *, submit_intent_id: str) -> dict[str, Any]:
        """Recover only by broker query; never call submit again."""
        normalized = str(submit_intent_id or "").strip().lower()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            raise ControlledBrokerSubmissionRejected(
                "controlled broker recovery id invalid",
                evidence={
                    "status": "rejected",
                    "submit_intent_id": normalized,
                    "blockers": ["controlled_broker_submit_intent_id_invalid"],
                },
            )
        row = self._db.get_controlled_broker_submit_intent_sync(normalized)
        if row is None:
            raise ControlledBrokerSubmissionRejected(
                "controlled broker recovery intent not found",
                evidence={
                    "status": "rejected",
                    "submit_intent_id": normalized,
                    "blockers": ["controlled_broker_submit_intent_not_found"],
                },
            )
        if row.get("status") in {"submitted", "rejected"}:
            return _intent_response(
                row,
                reused=True,
                external_call_performed=False,
            )
        now = _aware_utc(self._clock())
        age_seconds = max(
            0,
            int(now.timestamp()) - int(row.get("prepared_at_epoch_ms") or 0) // 1000,
        )
        if age_seconds < CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS:
            return {
                **_intent_response(
                    row,
                    reused=True,
                    external_call_performed=False,
                ),
                "status": "recovery_wait_required",
                "recovery_wait_remaining_seconds": (
                    CONTROLLED_BROKER_RECOVERY_MINIMUM_WAIT_SECONDS - age_seconds
                ),
            }
        gateway, gateway_blockers = self._gateway(str(row.get("gateway_id") or ""))
        query = getattr(gateway, "query_order", None) if not gateway_blockers else None
        try:
            raw_result = (
                query(str(row.get("client_order_id") or "")) if callable(query) else {}
            )
            raw_result = raw_result if isinstance(raw_result, dict) else {}
        except Exception as exc:
            raw_result = {
                "status": "gateway_query_exception",
                "error_type": type(exc).__name__,
                "submitted": None,
            }
        classification = _classify_gateway_result(
            raw_result,
            client_order_id=str(row.get("client_order_id") or ""),
            order_fingerprint=str(row.get("order_fingerprint") or ""),
            allow_definitive_not_found=True,
        )
        finalized = self._finalize(
            submit_intent_id=normalized,
            classification=classification,
            result=_sanitize_gateway_result(raw_result),
            recovered=True,
        )
        return _intent_response(
            finalized.get("intent") or {},
            reused=False,
            external_call_performed=False,
        )

    def list_intents(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_broker_submit_intents_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [
            _intent_response(row, reused=False, external_call_performed=False)
            for row in rows
        ]

    def get_intent(self, submit_intent_id: str) -> dict[str, Any]:
        row = self._db.get_controlled_broker_submit_intent_sync(submit_intent_id)
        if row is None:
            return {
                "status": "not_found",
                "submit_intent_id": submit_intent_id,
                "default_broker_submission_enabled": False,
            }
        return _intent_response(row, reused=False, external_call_performed=False)

    def _resolve_provider(
        self,
        provider: Callable[[str], dict[str, Any]] | None,
        identifier: str,
        *,
        unavailable: str,
        failed: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        if not callable(provider):
            blockers.append(unavailable)
            return {}
        try:
            value = provider(identifier) or {}
        except Exception:
            blockers.append(failed)
            return {}
        return value if isinstance(value, dict) else {}

    def _submission_interlock(
        self,
        *,
        exclude_order_id: str = "",
    ) -> dict[str, Any]:
        try:
            rows = self._db.list_unreconciled_controlled_broker_submit_intents_sync(
                limit=500
            )
        except Exception:
            return {
                "status": "blocked_source_unavailable",
                "blocked": True,
                "unresolved_count": 0,
                "unresolved_intents": [],
                "clearing_operation_available": False,
            }
        unresolved = [
            {
                "submit_intent_id": str(row.get("submit_intent_id") or ""),
                "order_id": str(row.get("order_id") or ""),
                "status": str(row.get("status") or "unknown"),
            }
            for row in rows
            if str(row.get("order_id") or "") != exclude_order_id
        ]
        return {
            "status": "blocked_unreconciled_submission" if unresolved else "clear",
            "blocked": bool(unresolved),
            "unresolved_count": len(unresolved),
            "unresolved_intents": unresolved[:20],
            "clearing_operation_available": False,
        }

    def _resolve_release(
        self,
        release_evidence_id: str,
        *,
        expected_gateway_id: str,
        expected_account_alias: str,
        now: datetime,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        raw = self._resolve_provider(
            self._release_evidence_provider,
            release_evidence_id,
            unavailable="controlled_broker_submit_release_provider_unavailable",
            failed="controlled_broker_submit_release_provider_failed",
            blockers=blockers,
        )
        evidence_fingerprint = str(raw.get("evidence_fingerprint") or "")
        if raw.get("status") != "current_clear_signed_release":
            blockers.append("controlled_broker_submit_release_not_current")
        if str(raw.get("release_evidence_id") or "") != release_evidence_id:
            blockers.append("controlled_broker_submit_release_identity_mismatch")
        if not _FINGERPRINT_PATTERN.fullmatch(evidence_fingerprint):
            blockers.append("controlled_broker_submit_release_fingerprint_invalid")
        if str(raw.get("gateway_id") or "") != expected_gateway_id:
            blockers.append("controlled_broker_submit_release_gateway_mismatch")
        if str(raw.get("account_alias") or "") != expected_account_alias:
            blockers.append("controlled_broker_submit_release_account_mismatch")
        if raw.get("operator_identity_verified") is not True:
            blockers.append("controlled_broker_submit_release_operator_unverified")
        if raw.get("execution_mode") != "manual_each_order":
            blockers.append("controlled_broker_submit_release_mode_invalid")
        if raw.get("automatic_execution_allowed") is not False:
            blockers.append("controlled_broker_submit_release_automatic_mode_invalid")
        if raw.get("strategy_direct_submission_allowed") is not False:
            blockers.append("controlled_broker_submit_release_strategy_path_invalid")
        for field in _REQUIRED_RELEASE_ASSERTIONS:
            if raw.get(field) is not True:
                blockers.append(f"controlled_broker_submit_release_{field}_missing")
        effective_at = _parse_timestamp(raw.get("effective_at"))
        expires_at = _parse_timestamp(raw.get("expires_at"))
        if effective_at is None or expires_at is None or expires_at <= effective_at:
            blockers.append("controlled_broker_submit_release_window_invalid")
        elif now < effective_at or now >= expires_at:
            blockers.append("controlled_broker_submit_release_not_effective")
        return {
            "status": "clear" if not blockers else "blocked",
            "release_evidence_id": release_evidence_id,
            "evidence_fingerprint": evidence_fingerprint,
            "gateway_id": str(raw.get("gateway_id") or ""),
            "account_alias": str(raw.get("account_alias") or ""),
            "effective_at": str(raw.get("effective_at") or ""),
            "expires_at": str(raw.get("expires_at") or ""),
            "review_assertions": {
                field: raw.get(field) is True for field in _REQUIRED_RELEASE_ASSERTIONS
            },
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _gateway(self, gateway_id: str) -> tuple[Any | None, list[str]]:
        matches = [
            item
            for item in self._gateways
            if str(getattr(item, "gateway_id", "") or "") == gateway_id
        ]
        if not matches:
            return None, ["controlled_broker_submit_gateway_not_registered"]
        if len(matches) > 1:
            return None, ["controlled_broker_submit_gateway_id_duplicated"]
        return matches[0], []

    def _kill_switch(self) -> dict[str, Any]:
        getter = getattr(self._trading_controls, "snapshot", None)
        if not callable(getter):
            return {"enabled": None, "reason_present": False, "updated_at": ""}
        try:
            value = getter()
        except Exception:
            return {"enabled": None, "reason_present": False, "updated_at": ""}
        return {
            "enabled": bool(getattr(value, "kill_switch_enabled", False)),
            "reason_present": bool(str(getattr(value, "reason", "") or "")),
            "updated_at": str(getattr(value, "updated_at", "") or ""),
        }

    def _pre_call_blockers(self, preview: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        if self._kill_switch().get("enabled") is not False:
            blockers.append("controlled_broker_submit_kill_switch_changed")
        release = self._resolve_release(
            preview["release_evidence_id"],
            expected_gateway_id=preview["gateway_id"],
            expected_account_alias=preview["account_alias"],
            now=_aware_utc(self._clock()),
        )
        if release["evidence_fingerprint"] != preview["release_evidence_fingerprint"]:
            blockers.append("controlled_broker_submit_release_changed")
        blockers.extend(release["blockers"])
        gateway, gateway_blockers = self._gateway(preview["gateway_id"])
        blockers.extend(gateway_blockers)
        _, capability_blockers = _capabilities(gateway)
        blockers.extend(capability_blockers)
        _, health_blockers = _health(gateway, now=_aware_utc(self._clock()))
        blockers.extend(health_blockers)
        return list(dict.fromkeys(blockers))

    def _finalize(
        self,
        *,
        submit_intent_id: str,
        classification: str,
        result: dict[str, Any],
        recovered: bool,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        broker_order_id = str(result.get("broker_order_id") or "")
        broker_status = str(result.get("status") or "")
        transaction = self._db.finalize_controlled_broker_submit_intent_sync(
            submit_intent_id=submit_intent_id,
            status=classification,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            result=result,
            actor="controlled-broker-submission",
            finalized_at_epoch_ms=int(now.timestamp() * 1000),
            finalized_at=now.isoformat(),
            recovered=recovered,
        )
        if transaction.get("status") == "rejected" and transaction.get("blockers"):
            raise ControlledBrokerSubmissionRejected(
                "controlled broker submission result persistence rejected",
                evidence=transaction,
            )
        return transaction

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_BROKER_SUBMISSION_SCHEMA_VERSION,
            "status": "rejected",
            "order_id": str(preview.get("order_id") or ""),
            "submit_intent_id": str(preview.get("submit_intent_id") or ""),
            "expected_fingerprint": str(preview.get("submit_fingerprint") or ""),
            "submitted_fingerprint": str(submitted_fingerprint or ""),
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "submitted_to_broker": False,
            "production_ledger_mutated": False,
            "automatic_submission_enabled": False,
            "strategy_direct_submission_enabled": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_BROKER_SUBMISSION_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_BROKER_SUBMISSION_REJECTION_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_BROKER_SUBMISSION_EVENT_SOURCE,
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }


def _capabilities(gateway: Any | None) -> tuple[dict[str, bool], list[str]]:
    raw = getattr(gateway, "capabilities", {}) if gateway is not None else {}
    result = {
        field: bool(
            raw.get(field) if isinstance(raw, dict) else getattr(raw, field, False)
        )
        for field in _REQUIRED_CAPABILITIES
    }
    blockers = [
        f"controlled_broker_submit_capability_missing:{field}"
        for field, enabled in result.items()
        if not enabled
    ]
    return result, blockers


def _health(gateway: Any | None, *, now: datetime) -> tuple[dict[str, Any], list[str]]:
    getter = getattr(gateway, "get_health", None)
    if not callable(getter):
        return _missing_health(), ["controlled_broker_submit_health_unavailable"]
    try:
        raw = getter() or {}
    except Exception:
        return _missing_health(), ["controlled_broker_submit_health_failed"]
    raw = raw if isinstance(raw, dict) else {}
    captured_at = _parse_timestamp(raw.get("captured_at"))
    source_fingerprint = str(raw.get("source_fingerprint") or "")
    blockers: list[str] = []
    if raw.get("status") != "healthy":
        blockers.append("controlled_broker_submit_gateway_unhealthy")
    if captured_at is None:
        blockers.append("controlled_broker_submit_health_timestamp_invalid")
        age_seconds = None
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -30:
            blockers.append("controlled_broker_submit_health_timestamp_future")
        elif age > CONTROLLED_BROKER_GATEWAY_HEALTH_MAX_AGE_SECONDS:
            blockers.append("controlled_broker_submit_health_stale")
    if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
        blockers.append("controlled_broker_submit_health_fingerprint_invalid")
    return {
        "status": str(raw.get("status") or "missing"),
        "captured_at": captured_at.isoformat() if captured_at else "",
        "source_fingerprint": source_fingerprint,
        "age_seconds": age_seconds,
    }, blockers


def _missing_health() -> dict[str, Any]:
    return {
        "status": "missing",
        "captured_at": "",
        "source_fingerprint": "",
        "age_seconds": None,
    }


def _dry_run(
    gateway: Any | None,
    order: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    runner = getattr(gateway, "dry_run_order", None)
    if not callable(runner):
        return _missing_dry_run(), ["controlled_broker_submit_dry_run_unavailable"]
    try:
        raw = runner(dict(order)) or {}
    except Exception:
        return _missing_dry_run(), ["controlled_broker_submit_dry_run_failed"]
    raw = raw if isinstance(raw, dict) else {}
    result = {
        "status": str(raw.get("status") or ""),
        "order_fingerprint": str(raw.get("order_fingerprint") or ""),
        "client_order_id": str(raw.get("client_order_id") or ""),
        "payload_fingerprint": str(raw.get("payload_fingerprint") or ""),
        "submitted": raw.get("submitted") is True,
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "side_effect_count": int(raw.get("side_effect_count") or 0),
    }
    blockers: list[str] = []
    if result["status"] not in {"accepted", "pass"}:
        blockers.append("controlled_broker_submit_dry_run_not_accepted")
    if result["order_fingerprint"] != order["order_fingerprint"]:
        blockers.append("controlled_broker_submit_dry_run_order_mismatch")
    if result["client_order_id"] != order["client_order_id"]:
        blockers.append("controlled_broker_submit_dry_run_client_id_mismatch")
    if not _FINGERPRINT_PATTERN.fullmatch(result["payload_fingerprint"]):
        blockers.append("controlled_broker_submit_dry_run_payload_invalid")
    if result["submitted"] or result["broker_order_id"] or result["side_effect_count"]:
        blockers.append("controlled_broker_submit_dry_run_had_side_effect")
    return result, blockers


def _missing_dry_run() -> dict[str, Any]:
    return {
        "status": "missing",
        "order_fingerprint": "",
        "client_order_id": "",
        "payload_fingerprint": "",
        "submitted": False,
        "broker_order_id": "",
        "side_effect_count": 0,
    }


def _classify_gateway_result(
    raw: dict[str, Any],
    *,
    client_order_id: str,
    order_fingerprint: str,
    allow_definitive_not_found: bool,
) -> str:
    status = str(raw.get("status") or "").lower()
    if str(raw.get("client_order_id") or "") != client_order_id:
        return "submission_unknown"
    raw_order_fingerprint = str(raw.get("order_fingerprint") or "")
    if raw_order_fingerprint and raw_order_fingerprint != order_fingerprint:
        return "submission_unknown"
    if (
        status in {"accepted", "submitted", "open", "partially_filled", "filled"}
        and raw.get("submitted") is True
        and _ID_PATTERN.fullmatch(str(raw.get("broker_order_id") or ""))
    ):
        return "submitted"
    if (
        status == "rejected"
        and raw.get("submitted") is False
        and raw.get("definitive") is True
        and not str(raw.get("broker_order_id") or "")
    ):
        return "rejected"
    if (
        allow_definitive_not_found
        and status == "not_found"
        and raw.get("submitted") is False
        and raw.get("definitive") is True
        and not str(raw.get("broker_order_id") or "")
    ):
        return "rejected"
    return "submission_unknown"


def _sanitize_gateway_result(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "").lower()
    client_order_id = str(raw.get("client_order_id") or "")
    order_fingerprint = str(raw.get("order_fingerprint") or "")
    broker_order_id = str(raw.get("broker_order_id") or "")
    error_type = str(raw.get("error_type") or "")
    return {
        "status": status if status in _GATEWAY_RESULT_STATUSES else "unknown",
        "client_order_id": (
            client_order_id if _ID_PATTERN.fullmatch(client_order_id) else ""
        ),
        "order_fingerprint": (
            order_fingerprint
            if _FINGERPRINT_PATTERN.fullmatch(order_fingerprint)
            else ""
        ),
        "broker_order_id": (
            broker_order_id if _ID_PATTERN.fullmatch(broker_order_id) else ""
        ),
        "submitted": (
            raw.get("submitted") if raw.get("submitted") in {True, False} else None
        ),
        "definitive": raw.get("definitive") is True,
        "error_type": (
            error_type
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", error_type)
            else ""
        ),
    }


def _intent_response(
    row: dict[str, Any],
    *,
    reused: bool,
    external_call_performed: bool,
) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    result = _json_object(row.get("result_json"))
    status = str(row.get("status") or payload.get("status") or "not_found")
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "submit_intent_id": str(
            row.get("submit_intent_id") or payload.get("submit_intent_id") or ""
        ),
        "submit_fingerprint": str(
            row.get("submit_fingerprint") or payload.get("submit_fingerprint") or ""
        ),
        "order_id": str(row.get("order_id") or payload.get("order_id") or ""),
        "gateway_id": str(row.get("gateway_id") or payload.get("gateway_id") or ""),
        "client_order_id": str(
            row.get("client_order_id") or payload.get("client_order_id") or ""
        ),
        "status": status,
        "broker_order_id": str(row.get("broker_order_id") or ""),
        "broker_status": str(row.get("broker_status") or ""),
        "gateway_result": result,
        "persisted": bool(row),
        "reused": reused,
        "external_call_performed": external_call_performed,
        "submitted_to_broker": status == "submitted",
        "submission_outcome_unknown": status == "submission_unknown",
        "default_broker_submission_enabled": False,
        "automatic_submission_enabled": False,
        "strategy_direct_submission_enabled": False,
        "recovery_resubmission_enabled": False,
        "production_ledger_mutated": False,
        "safety": _safety_flags(),
    }


def _client_order_id(
    *,
    order_id: str,
    order_fingerprint: str,
    confirmation_id: str,
    release_evidence_fingerprint: str,
) -> str:
    digest = _fingerprint(
        {
            "domain": "karkinos.controlled_broker.client_order_id.v1",
            "order_id": order_id,
            "order_fingerprint": order_fingerprint,
            "confirmation_id": confirmation_id,
            "release_evidence_fingerprint": release_evidence_fingerprint,
        }
    )
    return f"KARK-{digest[:32]}"


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


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safety_flags() -> dict[str, bool]:
    return {
        "manual_final_signature_required": True,
        "one_shot_order_authority_only": True,
        "default_broker_submission_disabled": True,
        "automatic_submission_disabled": True,
        "strategy_direct_submission_disabled": True,
        "unknown_outcome_resubmission_disabled": True,
        "production_ledger_mutation_disabled": True,
        "automatic_capital_expansion_disabled": True,
        "unreconciled_submission_blocks_new_orders": True,
    }
