"""Equal-or-narrower replacement workflow for paused runtime sessions."""

from __future__ import annotations

from typing import Any

from server.contracts.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS,
    CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
)
from server.services.controlled_session_runtime_policy import (
    replacement_bound_blockers as _replacement_bound_blockers,
)
from server.services.controlled_session_runtime_values import (
    FINGERPRINT_PATTERN as _FINGERPRINT_PATTERN,
)
from server.services.controlled_session_runtime_values import (
    SALT_PATTERN as _SALT_PATTERN,
)
from server.services.controlled_session_runtime_values import (
    TOKEN_PATTERN as _TOKEN_PATTERN,
)
from server.services.controlled_session_runtime_values import aware_utc as _aware_utc
from server.services.controlled_session_runtime_values import (
    fingerprint as _fingerprint,
)
from server.services.controlled_session_runtime_values import json_list as _json_list
from server.services.controlled_session_runtime_values import (
    parse_timestamp as _parse_timestamp,
)
from server.services.controlled_session_runtime_values import (
    replacement_response as _replacement_response,
)
from server.services.controlled_session_runtime_values import (
    safety_flags as _safety_flags,
)
from server.services.controlled_session_runtime_values import (
    session_response as _session_response,
)
from server.services.controlled_session_runtime_values import token_hash as _token_hash


class RuntimeAuthorityReplacementMixin:
    def preview_replacement(
        self,
        *,
        predecessor_session_id: str,
        reservation_id: str,
    ) -> dict[str, Any]:
        """Preview a signed, equal-or-narrower replacement for one paused session."""
        now = _aware_utc(self._clock())
        predecessor_id = str(predecessor_session_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(predecessor_id):
            blockers.append("runtime_session_replacement_predecessor_id_invalid")
        existing_replacement = (
            self._db.get_controlled_session_replacement_for_predecessor_sync(
                predecessor_id
            )
            or {}
        )
        if existing_replacement:
            existing = _replacement_response(existing_replacement, reused=True)
            if (
                existing.get("replacement_reservation_id")
                == str(reservation_id or "").strip().lower()
            ):
                return {
                    **existing,
                    "status": "ready_for_signed_replacement",
                    "ready": True,
                    "blockers": [],
                    "reused": True,
                    "replacement_session_issued": True,
                    "automatic_resume_enabled": False,
                    "broker_submission_enabled": False,
                    "safety": _safety_flags(runtime_authority=False),
                }
            blockers.append("runtime_session_replacement_conflict")
        predecessor = (
            self._db.get_controlled_session_runtime_session_sync(predecessor_id) or {}
        )
        pause_state = (
            self._db.get_controlled_session_runtime_state_sync(predecessor_id) or {}
        )
        if not predecessor:
            blockers.append("runtime_session_replacement_predecessor_not_found")
        elif predecessor.get("status") != "enabled":
            blockers.append("runtime_session_replacement_predecessor_not_enabled")
        if pause_state.get("status") != "paused":
            blockers.append("runtime_session_replacement_predecessor_not_paused")

        target = self.preview_issuance(
            reservation_id=reservation_id,
            _replacement_of_session_id=predecessor_id,
        )
        if target.get("blockers"):
            blockers.append("runtime_session_replacement_target_not_ready")
            blockers.extend(f"target:{item}" for item in target.get("blockers") or [])
        if str(target.get("reservation_id") or "") == str(
            predecessor.get("reservation_id") or ""
        ):
            blockers.append("runtime_session_replacement_requires_new_reservation")
        if str(target.get("operator_id") or "") != str(
            predecessor.get("operator_id") or ""
        ):
            blockers.append("runtime_session_replacement_operator_mismatch")

        old_reservation = (
            self._db.get_controlled_session_budget_reservation_sync(
                str(predecessor.get("reservation_id") or "")
            )
            or {}
        )
        new_reservation = (
            self._db.get_controlled_session_budget_reservation_sync(
                str(target.get("reservation_id") or "")
            )
            or {}
        )
        blockers.extend(
            _replacement_bound_blockers(
                predecessor=predecessor,
                pause_state=pause_state,
                old_reservation=old_reservation,
                new_reservation=new_reservation,
                target=target,
            )
        )

        paused_at_epoch_ms = int(pause_state.get("paused_at_epoch_ms") or 0)
        snapshot_rows = (
            self._db.list_controlled_session_gate_snapshots_for_session_sync(
                session_id=predecessor_id,
                since_epoch_ms=paused_at_epoch_ms + 1,
                limit=500,
            )
            if predecessor_id
            else []
        )
        last_blocked_index = -1
        for index, row in enumerate(snapshot_rows):
            if row.get("status") != "clear" or _json_list(row.get("blockers_json")):
                last_blocked_index = index
        clear_snapshots = [
            row
            for row in snapshot_rows[last_blocked_index + 1 :]
            if row.get("status") == "clear" and not _json_list(row.get("blockers_json"))
        ]
        first_snapshot = clear_snapshots[0] if clear_snapshots else {}
        latest_snapshot = clear_snapshots[-1] if clear_snapshots else {}
        first_ms = int(first_snapshot.get("observed_at_epoch_ms") or 0)
        latest_ms = int(latest_snapshot.get("observed_at_epoch_ms") or 0)
        now_epoch_ms = int(now.timestamp() * 1000)
        minimum_stability_ms = (
            CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS * 1000
        )
        maximum_snapshot_age_ms = (
            CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS * 1000
        )
        if len(clear_snapshots) < 2:
            blockers.append("runtime_session_replacement_recovery_snapshots_missing")
        elif latest_ms - first_ms < minimum_stability_ms:
            blockers.append("runtime_session_replacement_recovery_not_stable")
        if (
            not latest_ms
            or latest_ms > now_epoch_ms
            or now_epoch_ms - latest_ms > maximum_snapshot_age_ms
        ):
            blockers.append("runtime_session_replacement_recovery_snapshot_stale")

        recovery_snapshot_ids = [
            str(first_snapshot.get("snapshot_id") or ""),
            str(latest_snapshot.get("snapshot_id") or ""),
        ]
        recovery_snapshot_fingerprints = [
            str(first_snapshot.get("snapshot_fingerprint") or ""),
            str(latest_snapshot.get("snapshot_fingerprint") or ""),
        ]
        replacement_core = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "action": "replace_paused_controlled_session",
            "predecessor_session_id": predecessor_id,
            "predecessor_session_fingerprint": str(
                predecessor.get("session_fingerprint") or ""
            ),
            "pause_event_id": str(pause_state.get("pause_event_id") or ""),
            "pause_reason_fingerprint": str(
                pause_state.get("reason_fingerprint") or ""
            ),
            "recovery_snapshot_ids": recovery_snapshot_ids,
            "recovery_snapshot_fingerprints": recovery_snapshot_fingerprints,
            "recovery_first_observed_at": str(first_snapshot.get("observed_at") or ""),
            "recovery_latest_observed_at": str(
                latest_snapshot.get("observed_at") or ""
            ),
            "minimum_recovery_stability_seconds": (
                CONTROLLED_SESSION_REPLACEMENT_MINIMUM_STABILITY_SECONDS
            ),
            "maximum_snapshot_age_seconds": (
                CONTROLLED_SESSION_REPLACEMENT_SNAPSHOT_MAX_AGE_SECONDS
            ),
            "target_issuance_fingerprint": str(
                target.get("issuance_fingerprint") or ""
            ),
            "replacement_reservation_id": str(target.get("reservation_id") or ""),
            "replacement_session_id": str(target.get("session_id") or ""),
            "replacement_session_fingerprint": str(
                target.get("session_fingerprint") or ""
            ),
            "authorization_id": str(target.get("authorization_id") or ""),
            "account_alias": str(target.get("account_alias") or ""),
            "strategy_id": str(target.get("strategy_id") or ""),
            "operator_id": str(target.get("operator_id") or ""),
            "order_ids": [str(item) for item in target.get("order_ids") or []],
            "effective_at": str(target.get("effective_at") or ""),
            "expires_at": str(target.get("expires_at") or ""),
            "max_order_rate_per_minute": int(
                target.get("max_order_rate_per_minute") or 0
            ),
        }
        replacement_fingerprint = _fingerprint(replacement_core)
        replacement_id = _fingerprint(
            {
                "domain": "karkinos.controlled_session.replacement_id.v1",
                "replacement_fingerprint": replacement_fingerprint,
            }
        )
        retirement_revocation_fingerprint = _fingerprint(
            {
                "domain": "karkinos.controlled_session.replacement_retirement.v1",
                "replacement_id": replacement_id,
                "predecessor_session_id": predecessor_id,
                "predecessor_session_fingerprint": replacement_core[
                    "predecessor_session_fingerprint"
                ],
            }
        )
        retirement_revocation_id = _fingerprint(
            {
                "domain": "karkinos.controlled_session.revocation_id.v1",
                "revocation_fingerprint": retirement_revocation_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **replacement_core,
            "replacement_id": replacement_id,
            "replacement_fingerprint": replacement_fingerprint,
            "retirement_revocation_id": retirement_revocation_id,
            "retirement_revocation_fingerprint": (retirement_revocation_fingerprint),
            "generated_at": now.isoformat(),
            "status": (
                "ready_for_signed_replacement" if not unique_blockers else "blocked"
            ),
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "required_operator_approval": {
                "action": "replace_paused_controlled_session",
                "artifact_type": "controlled_session_replacement",
                "artifact_fingerprint": replacement_fingerprint,
            },
            "predecessor_will_be_revoked_atomically": True,
            "replacement_session_issued": False,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }

    def replace_paused(
        self,
        *,
        predecessor_session_id: str,
        reservation_id: str,
        replacement_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        """Atomically revoke one paused session and issue its signed replacement."""
        preview = self.preview_replacement(
            predecessor_session_id=predecessor_session_id,
            reservation_id=reservation_id,
        )
        rejection_reasons: list[str] = []
        if replacement_fingerprint != preview["replacement_fingerprint"]:
            rejection_reasons.append("runtime_session_replacement_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "runtime_session_replacement_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("runtime_session_replacement_review_blocked")
        approval, approval_blockers = self._resolve_operator_approval(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="replace_paused_controlled_session",
            expected_artifact_type="controlled_session_replacement",
            expected_artifact_fingerprint=preview["replacement_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "runtime_session_replace_operator_approval_blocked"
            )
        elif approval.get("operator_id") != preview["operator_id"]:
            rejection_reasons.append("runtime_session_replace_operator_mismatch")
        if rejection_reasons:
            evidence = self._record_rejection(
                action="replace_paused_controlled_session",
                artifact=preview,
                submitted_fingerprint=replacement_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
            )
            raise self._runtime_authority_rejection(
                "controlled session replacement rejected",
                evidence=evidence,
            )

        token = str(self._token_factory() or "")
        salt = str(self._salt_factory() or "")
        if not _TOKEN_PATTERN.fullmatch(token) or not _SALT_PATTERN.fullmatch(salt):
            evidence = self._record_rejection(
                action="replace_paused_controlled_session",
                artifact=preview,
                submitted_fingerprint=replacement_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_secret_generation_failed"],
                transaction_blockers=[],
            )
            raise self._runtime_authority_rejection(
                "controlled session replacement secret rejected",
                evidence=evidence,
            )
        now = _aware_utc(self._clock())
        reservation = (
            self._db.get_controlled_session_budget_reservation_sync(
                preview["replacement_reservation_id"]
            )
            or {}
        )
        session_payload = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "session_id": preview["replacement_session_id"],
            "session_fingerprint": preview["replacement_session_fingerprint"],
            "issuance_fingerprint": preview["target_issuance_fingerprint"],
            "reservation_id": preview["replacement_reservation_id"],
            "attestation_id": str(reservation.get("attestation_id") or ""),
            "envelope_fingerprint": str(reservation.get("envelope_fingerprint") or ""),
            "authorization_id": preview["authorization_id"],
            "account_alias": preview["account_alias"],
            "strategy_id": preview["strategy_id"],
            "operator_id": preview["operator_id"],
            "operator_approval_id": operator_approval_id,
            "order_ids": preview["order_ids"],
            "effective_at": preview["effective_at"],
            "expires_at": preview["expires_at"],
            "max_order_rate_per_minute": preview["max_order_rate_per_minute"],
            "status": "enabled",
            "replacement_of_session_id": preview["predecessor_session_id"],
            "replacement_id": preview["replacement_id"],
            "runtime_session_issued": True,
            "runtime_authority_enabled": True,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=True),
        }
        retirement_payload = {
            "schema_version": CONTROLLED_SESSION_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            "status": "revoked",
            "reason_code": "signed_replacement_after_pause_review",
            "session_id": preview["predecessor_session_id"],
            "session_fingerprint": preview["predecessor_session_fingerprint"],
            "replacement_id": preview["replacement_id"],
            "replacement_session_id": preview["replacement_session_id"],
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }
        replacement_payload = {
            **preview,
            "status": "replaced_with_new_bounded_session",
            "operator_approval_id": operator_approval_id,
            "predecessor_revoked": True,
            "replacement_session_issued": True,
            "session_token": "",
            "broker_submission_enabled": False,
            "safety": _safety_flags(runtime_authority=False),
        }
        transaction = self._db.replace_paused_controlled_session_sync(
            replacement={
                "replacement_id": preview["replacement_id"],
                "replacement_fingerprint": preview["replacement_fingerprint"],
                "predecessor_session_id": preview["predecessor_session_id"],
                "predecessor_session_fingerprint": preview[
                    "predecessor_session_fingerprint"
                ],
                "pause_event_id": preview["pause_event_id"],
                "recovery_snapshot_ids": preview["recovery_snapshot_ids"],
                "minimum_recovery_stability_ms": (
                    preview["minimum_recovery_stability_seconds"] * 1000
                ),
                "maximum_snapshot_age_ms": (
                    preview["maximum_snapshot_age_seconds"] * 1000
                ),
                "retirement_revocation_id": preview["retirement_revocation_id"],
                "retirement_revocation_fingerprint": preview[
                    "retirement_revocation_fingerprint"
                ],
                "retirement_payload": retirement_payload,
                "session_id": session_payload["session_id"],
                "session_fingerprint": session_payload["session_fingerprint"],
                "issuance_fingerprint": session_payload["issuance_fingerprint"],
                "reservation_id": session_payload["reservation_id"],
                "attestation_id": str(reservation.get("attestation_id") or ""),
                "envelope_fingerprint": str(
                    reservation.get("envelope_fingerprint") or ""
                ),
                "authorization_id": session_payload["authorization_id"],
                "account_alias": session_payload["account_alias"],
                "strategy_id": session_payload["strategy_id"],
                "operator_id": session_payload["operator_id"],
                "operator_approval_id": operator_approval_id,
                "order_ids": session_payload["order_ids"],
                "effective_at_epoch_ms": int(
                    _parse_timestamp(session_payload["effective_at"]).timestamp() * 1000
                ),
                "expires_at_epoch_ms": int(
                    _parse_timestamp(session_payload["expires_at"]).timestamp() * 1000
                ),
                "requested_start_at": session_payload["effective_at"],
                "requested_expires_at": session_payload["expires_at"],
                "max_order_rate_per_minute": session_payload[
                    "max_order_rate_per_minute"
                ],
                "token_salt": salt,
                "token_hash": _token_hash(token, salt),
                "session_payload": session_payload,
                "replacement_payload": replacement_payload,
                "reviewed_at_epoch_ms": int(now.timestamp() * 1000),
                "reviewed_at": now.isoformat(),
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") not in {"enabled", "revoked"}:
            evidence = self._record_rejection(
                action="replace_paused_controlled_session",
                artifact=preview,
                submitted_fingerprint=replacement_fingerprint,
                operator_approval_id=operator_approval_id,
                rejection_reasons=["runtime_session_replacement_transaction_rejected"],
                transaction_blockers=[
                    str(item) for item in transaction.get("blockers") or []
                ],
            )
            raise self._runtime_authority_rejection(
                "controlled session replacement transaction rejected",
                evidence=evidence,
            )
        response = _session_response(
            transaction.get("session") or {},
            reused=bool(transaction.get("reused")),
        )
        replacement_evidence = _replacement_response(
            transaction.get("replacement") or {},
            reused=bool(transaction.get("reused")),
        )
        if transaction.get("reused"):
            return {
                **response,
                "replacement": replacement_evidence,
                "runtime_authority_enabled": response.get("status") == "enabled",
                "session_token": "",
                "session_token_issued": False,
                "session_token_notice": "token_not_reissued_on_idempotent_retry",
            }
        return {
            **response,
            "replacement": replacement_evidence,
            "runtime_authority_enabled": True,
            "session_token": token,
            "session_token_issued": True,
            "session_token_notice": "store_securely_token_will_not_be_shown_again",
        }

    def list_replacements(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_replacements_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_replacement_response(row, reused=False) for row in rows]
