"""Persisted live-gate snapshots and automatic-pause orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
)

CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION = (
    "karkinos.controlled_session_live_gate_snapshot.v1"
)
CONTROLLED_SESSION_LIVE_GATE_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_session_live_gate_status.v1"
)
CONTROLLED_SESSION_LIVE_GATE_REJECTION_EVENT_TYPE = (
    "controlled_session.live_gate_snapshot_rejected"
)
CONTROLLED_SESSION_LIVE_GATE_ENTITY_TYPE = "controlled_session_live_gate_snapshot"
CONTROLLED_SESSION_LIVE_GATE_EVENT_SOURCE = "controlled_session_live_gates"
CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS = 30
CONTROLLED_SESSION_MARKET_DATA_MAX_AGE_SECONDS = 120
CONTROLLED_SESSION_REJECTION_WINDOW_SECONDS = 60
CONTROLLED_SESSION_REJECTION_SPIKE_THRESHOLD = 3

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ControlledSessionLiveGateRejected(ValueError):
    """Raised after a live-gate or authenticated orchestration rejection."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledSessionLiveGateSnapshotService:
    """Build an allowlisted current snapshot from persisted runtime evidence."""

    def __init__(
        self,
        *,
        db: Any,
        session_monitor_provider: Callable[[str], dict[str, Any]] | None = None,
        reservation_provider: Callable[[str], dict[str, Any]] | None = None,
        attestation_provider: Callable[[str], dict[str, Any]] | None = None,
        trading_controls: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        market_data_max_age_seconds: int = (
            CONTROLLED_SESSION_MARKET_DATA_MAX_AGE_SECONDS
        ),
    ) -> None:
        self._db = db
        self._session_monitor_provider = session_monitor_provider
        self._reservation_provider = reservation_provider
        self._attestation_provider = attestation_provider
        self._trading_controls = trading_controls
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._market_data_max_age_seconds = max(1, int(market_data_max_age_seconds))

    def get_status(self) -> dict[str, Any]:
        providers_configured = all(
            callable(provider)
            for provider in (
                self._session_monitor_provider,
                self._reservation_provider,
                self._attestation_provider,
            )
        )
        return {
            "schema_version": CONTROLLED_SESSION_LIVE_GATE_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "persisted_live_gate_snapshot_ready"
                if providers_configured and self._trading_controls is not None
                else "disabled_waiting_for_live_gate_sources"
            ),
            "session_monitor_provider_configured": callable(
                self._session_monitor_provider
            ),
            "reservation_provider_configured": callable(self._reservation_provider),
            "attestation_provider_configured": callable(self._attestation_provider),
            "kill_switch_provider_configured": self._trading_controls is not None,
            "snapshot_max_age_seconds": CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS,
            "market_data_max_age_seconds": self._market_data_max_age_seconds,
            "rejection_window_seconds": CONTROLLED_SESSION_REJECTION_WINDOW_SECONDS,
            "rejection_spike_threshold": (CONTROLLED_SESSION_REJECTION_SPIKE_THRESHOLD),
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def capture(self, *, session_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized = str(session_id or "").strip().lower()
        session = self._provider_value(
            self._session_monitor_provider,
            normalized,
        )
        if (
            not _FINGERPRINT_PATTERN.fullmatch(normalized)
            or session.get("status") != "monitorable_bounded_session"
            or not session.get("monitoring_identity_verified")
        ):
            evidence = self._record_rejection(
                session_id=normalized,
                blockers=["live_gate_monitoring_identity_unavailable"],
            )
            raise ControlledSessionLiveGateRejected(
                "controlled session live-gate capture rejected",
                evidence=evidence,
            )
        session_fingerprint = str(session.get("session_fingerprint") or "")
        reservation_id = str(session.get("reservation_id") or "")
        attestation_id = str(session.get("attestation_id") or "")
        if not all(
            _FINGERPRINT_PATTERN.fullmatch(value)
            for value in (session_fingerprint, reservation_id, attestation_id)
        ):
            evidence = self._record_rejection(
                session_id=normalized,
                blockers=["live_gate_session_evidence_identity_invalid"],
            )
            raise ControlledSessionLiveGateRejected(
                "controlled session live-gate identity rejected",
                evidence=evidence,
            )

        provider_blockers: list[str] = []
        reservation = self._provider_value(
            self._reservation_provider,
            reservation_id,
            blockers=provider_blockers,
            unavailable="live_gate_reservation_provider_unavailable",
            failed="live_gate_reservation_provider_failed",
        )
        attestation = self._provider_value(
            self._attestation_provider,
            attestation_id,
            blockers=provider_blockers,
            unavailable="live_gate_attestation_provider_unavailable",
            failed="live_gate_attestation_provider_failed",
        )
        reservation_clear = reservation.get("resolution_status") == (
            "current_reserved_non_executing"
        )
        attestation_clear = attestation.get("status") == (
            "current_verified_non_executing"
        )
        envelope = _mapping(attestation.get("current_envelope"))
        orders = [
            item for item in envelope.get("orders") or [] if isinstance(item, dict)
        ]
        capital = _mapping(envelope.get("capital_evaluation"))
        effective_limits = _mapping(capital.get("effective_limits"))
        remaining_budget = _mapping(capital.get("remaining_budget"))

        account_truth = _mapping(envelope.get("session_start_account_truth"))
        account_truth_clear = (
            attestation_clear and account_truth.get("status") == "pass"
        )
        risk_clear = bool(orders) and all(
            _nested_gate_status(order, "risk") == "pass" for order in orders
        )
        paper_shadow_clear = bool(orders) and all(
            _nested_gate_status(order, "paper_shadow") == "pass" for order in orders
        )
        reconciliation = _mapping(envelope.get("prior_execution_reconciliation"))
        reconciliation_clear = (
            attestation_clear and reconciliation.get("status") == "pass"
        )
        gateway = _mapping(envelope.get("execution_gateway"))
        gateway_verifications = [
            item
            for item in envelope.get("execution_gateway_verifications") or []
            if isinstance(item, dict)
        ]
        gateway_clear = (
            bool(gateway_verifications)
            and bool(gateway.get("runtime_gateway_verified"))
            and all(item.get("status") == "pass" for item in gateway_verifications)
        )

        market_data, market_blockers = self._market_data_evidence(orders, now=now)
        provider_blockers.extend(market_blockers)
        metrics = self._runtime_metrics(normalized, now=now)
        metric_blockers = [str(item) for item in metrics.pop("blockers", [])]
        provider_blockers.extend(metric_blockers)
        kill_switch = self._kill_switch_evidence()
        if kill_switch["enabled"] is None:
            provider_blockers.append("live_gate_kill_switch_unavailable")

        daily_loss_remaining = _decimal(remaining_budget.get("daily_loss"))
        drawdown_remaining = _decimal(remaining_budget.get("drawdown_pct"))
        max_consecutive_errors = _positive_int(
            effective_limits.get("max_consecutive_errors")
        )
        gate_snapshot = {
            "source_fingerprint": "",
            "account_truth_status": "pass" if account_truth_clear else "blocked",
            "risk_gate_status": "passed" if risk_clear else "blocked",
            "reconciliation_status": ("clear" if reconciliation_clear else "blocked"),
            "paper_shadow_status": (
                "within_expectations" if paper_shadow_clear else "blocked"
            ),
            "gateway_health_status": "healthy" if gateway_clear else "degraded",
            "market_data_status": market_data["status"],
            "budget_status": (
                "current_reserved_non_executing"
                if reservation_clear and attestation_clear
                else "blocked"
            ),
            "rate_limit_status": metrics["rate_limit_status"],
            "kill_switch_enabled": kill_switch["enabled"],
            "budget_exhausted": metrics["budget_exhausted"],
            "daily_loss_limit_reached": (
                None
                if daily_loss_remaining is None
                else daily_loss_remaining <= Decimal("0")
            ),
            "drawdown_limit_reached": (
                None
                if drawdown_remaining is None
                else drawdown_remaining <= Decimal("0")
            ),
            "rejection_spike": metrics["rejection_spike"],
            "unexpected_account_change": not account_truth_clear,
            "consecutive_errors": metrics["consecutive_errors"],
            "max_consecutive_errors": max_consecutive_errors,
        }
        source_evidence = {
            "session_id": normalized,
            "session_fingerprint": session_fingerprint,
            "reservation_id": reservation_id,
            "attestation_id": attestation_id,
            "reservation_resolution_status": str(
                reservation.get("resolution_status") or "missing"
            ),
            "attestation_status": str(attestation.get("status") or "missing"),
            "envelope_fingerprint": str(attestation.get("envelope_fingerprint") or ""),
            "account_truth_fingerprint": str(
                account_truth.get("account_truth_fingerprint") or ""
            ),
            "prior_reconciliation_fingerprint": str(
                reconciliation.get("batch_reconciliation_fingerprint") or ""
            ),
            "gateway_verification_fingerprints": sorted(
                str(item.get("verification_fingerprint") or "")
                for item in gateway_verifications
            ),
            "market_data": market_data,
            "runtime_metrics": metrics,
            "kill_switch": kill_switch,
            "provider_blockers": list(dict.fromkeys(provider_blockers)),
        }
        source_fingerprint = _fingerprint(source_evidence)
        gate_snapshot["source_fingerprint"] = source_fingerprint
        gate_blockers = _gate_blockers(gate_snapshot)
        all_blockers = list(dict.fromkeys([*provider_blockers, *gate_blockers]))
        snapshot_core = {
            "schema_version": CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION,
            "session_id": normalized,
            "session_fingerprint": session_fingerprint,
            "source_fingerprint": source_fingerprint,
            "gate_snapshot": gate_snapshot,
            "source_evidence": source_evidence,
            "blockers": all_blockers,
            "observed_at": now.isoformat(),
        }
        snapshot_fingerprint = _fingerprint(snapshot_core)
        snapshot_id = _fingerprint(
            {
                "domain": "karkinos.controlled_session.live_gate_snapshot.v1",
                "snapshot_fingerprint": snapshot_fingerprint,
                "observed_at_epoch_ms": int(now.timestamp() * 1000),
            }
        )
        payload = {
            **snapshot_core,
            "snapshot_id": snapshot_id,
            "snapshot_fingerprint": snapshot_fingerprint,
            "status": "clear" if not all_blockers else "blocked",
            "automatic_pause_evaluated": False,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        transaction = self._db.record_controlled_session_gate_snapshot_sync(
            snapshot={
                "snapshot_id": snapshot_id,
                "snapshot_fingerprint": snapshot_fingerprint,
                "session_id": normalized,
                "session_fingerprint": session_fingerprint,
                "source_fingerprint": source_fingerprint,
                "observed_at_epoch_ms": int(now.timestamp() * 1000),
                "observed_at": now.isoformat(),
                "status": payload["status"],
                "gate_snapshot": gate_snapshot,
                "source_evidence": source_evidence,
                "blockers": all_blockers,
                "payload": payload,
                "created_at": now.isoformat(),
            }
        )
        if transaction.get("status") not in {"clear", "blocked"}:
            evidence = self._record_rejection(
                session_id=normalized,
                blockers=[str(item) for item in transaction.get("blockers") or []],
            )
            raise ControlledSessionLiveGateRejected(
                "controlled session live-gate transaction rejected",
                evidence=evidence,
            )
        return _snapshot_response(
            transaction.get("snapshot") or {},
            reused=bool(transaction.get("reused")),
        )

    def latest(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip().lower()
        row = self._db.latest_controlled_session_gate_snapshot_sync(normalized)
        if row is None:
            return _missing_snapshot(normalized, ["live_gate_snapshot_not_found"])
        response = _snapshot_response(row, reused=False)
        observed_at = _parse_timestamp(response.get("observed_at"))
        now = _aware_utc(self._clock())
        if observed_at is None or (now - observed_at).total_seconds() > (
            CONTROLLED_SESSION_LIVE_GATE_MAX_AGE_SECONDS
        ):
            return {
                **response,
                "resolution_status": "stale",
                "resolution_blockers": ["live_gate_snapshot_stale"],
            }
        return {
            **response,
            "resolution_status": "current",
            "resolution_blockers": [],
        }

    def resolve_gate_snapshot(self, session_id: str) -> dict[str, Any]:
        latest = self.latest(session_id)
        if latest.get("resolution_status") != "current":
            return _missing_gate_values()
        return _mapping(latest.get("gate_snapshot"))

    def list_snapshots(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_controlled_session_gate_snapshots_sync(
            limit=max(1, min(int(limit), 500))
        )
        return [_snapshot_response(row, reused=False) for row in rows]

    def _market_data_evidence(
        self,
        orders: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[dict[str, Any], list[str]]:
        symbols = sorted({str(item.get("symbol") or "") for item in orders if item})
        blockers: list[str] = []
        observations: list[dict[str, Any]] = []
        if not symbols:
            blockers.append("live_gate_market_symbol_scope_missing")
        for symbol in symbols:
            row = self._db.get_latest_quote_sync(symbol) or {}
            timestamp = _parse_timestamp(
                row.get("quote_timestamp") or row.get("timestamp")
            )
            age_seconds = (
                None
                if timestamp is None
                else max(0, int((now - timestamp).total_seconds()))
            )
            quote_status = str(row.get("quote_status") or "").lower()
            provider_status = str(row.get("provider_status") or "").lower()
            current = bool(
                row
                and timestamp is not None
                and timestamp <= now
                and age_seconds is not None
                and age_seconds <= self._market_data_max_age_seconds
                and quote_status in {"live", "current", "confirmed"}
                and provider_status not in {"failed", "error", "unavailable"}
            )
            if not current:
                blockers.append(f"live_gate_market_data_not_current:{symbol}")
            observations.append(
                {
                    "symbol": symbol,
                    "quote_timestamp": timestamp.isoformat() if timestamp else "",
                    "age_seconds": age_seconds,
                    "quote_status": quote_status,
                    "provider_status": provider_status,
                    "current": current,
                }
            )
        return {
            "status": "current" if observations and not blockers else "stale",
            "observations": observations,
        }, blockers

    def _runtime_metrics(self, session_id: str, *, now: datetime) -> dict[str, Any]:
        observed_at_epoch_ms = int(now.timestamp() * 1000)
        window_start_epoch_ms = observed_at_epoch_ms - (
            CONTROLLED_SESSION_REJECTION_WINDOW_SECONDS * 1000
        )
        metrics = self._db.get_controlled_session_runtime_metrics_sync(
            session_id=session_id,
            window_start_epoch_ms=window_start_epoch_ms,
            observed_at_epoch_ms=observed_at_epoch_ms,
        )
        blockers: list[str] = []
        if not metrics:
            blockers.append("live_gate_runtime_metrics_unavailable")
        admitted_total = int(metrics.get("admitted_total") or 0)
        admitted_in_window = int(metrics.get("admitted_in_window") or 0)
        max_rate = _positive_int(metrics.get("max_order_rate_per_minute"))
        reserved_order_count = _positive_int(metrics.get("reserved_order_count"))
        if max_rate is None or reserved_order_count is None:
            blockers.append("live_gate_runtime_limits_invalid")
        rejection_rows = self._db.list_events_sync(
            event_type=CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
            limit=500,
        )
        recent_rejections = []
        latest_admission = int(metrics.get("latest_admitted_at_epoch_ms") or 0)
        for row in rejection_rows:
            payload = _json_object(row.get("payload_json"))
            if str(payload.get("session_id") or "") != session_id:
                continue
            timestamp = _parse_timestamp(row.get("timestamp"))
            if timestamp is None:
                continue
            timestamp_ms = int(timestamp.timestamp() * 1000)
            if window_start_epoch_ms < timestamp_ms <= observed_at_epoch_ms:
                recent_rejections.append(timestamp_ms)
        consecutive_errors = sum(
            1 for timestamp_ms in recent_rejections if timestamp_ms > latest_admission
        )
        return {
            "admitted_total": admitted_total,
            "admitted_in_window": admitted_in_window,
            "max_order_rate_per_minute": max_rate,
            "reserved_order_count": reserved_order_count,
            "rate_limit_status": (
                "clear"
                if max_rate is not None and admitted_in_window < max_rate
                else "reached"
            ),
            "budget_exhausted": (
                None
                if reserved_order_count is None
                else admitted_total >= reserved_order_count
            ),
            "recent_rejection_count": len(recent_rejections),
            "rejection_spike": (
                len(recent_rejections) >= CONTROLLED_SESSION_REJECTION_SPIKE_THRESHOLD
            ),
            "consecutive_errors": consecutive_errors,
            "blockers": blockers,
        }

    def _kill_switch_evidence(self) -> dict[str, Any]:
        if self._trading_controls is None:
            return {"enabled": None, "reason_present": False}
        snapshot = getattr(self._trading_controls, "snapshot", None)
        if not callable(snapshot):
            return {"enabled": None, "reason_present": False}
        try:
            value = snapshot()
        except Exception:
            return {"enabled": None, "reason_present": False}
        return {
            "enabled": bool(getattr(value, "kill_switch_enabled", False)),
            "reason_present": bool(str(getattr(value, "reason", "") or "")),
        }

    def _provider_value(
        self,
        provider: Callable[[str], dict[str, Any]] | None,
        identifier: str,
        *,
        blockers: list[str] | None = None,
        unavailable: str = "provider_unavailable",
        failed: str = "provider_failed",
    ) -> dict[str, Any]:
        if not callable(provider):
            if blockers is not None:
                blockers.append(unavailable)
            return {}
        try:
            value = provider(identifier) or {}
        except Exception:
            if blockers is not None:
                blockers.append(failed)
            return {}
        return value if isinstance(value, dict) else {}

    def _record_rejection(
        self,
        *,
        session_id: str,
        blockers: list[str],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION,
            "status": "rejected",
            "session_id": str(session_id or ""),
            "blockers": list(dict.fromkeys(blockers)),
            "automatic_pause_evaluated": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=CONTROLLED_SESSION_LIVE_GATE_REJECTION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=CONTROLLED_SESSION_LIVE_GATE_ENTITY_TYPE,
            entity_id=attempt_id,
            source=CONTROLLED_SESSION_LIVE_GATE_EVENT_SOURCE,
            source_ref=str(session_id or ""),
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
        }


class ControlledSessionAutomaticPauseOrchestratorService:
    """Capture current gates and immediately evaluate one-way pause."""

    def __init__(
        self,
        *,
        runtime_authority: Any,
        live_gates: ControlledSessionLiveGateSnapshotService,
        automatic_pause: ControlledSessionAutomaticPauseService,
    ) -> None:
        self._runtime_authority = runtime_authority
        self._live_gates = live_gates
        self._automatic_pause = automatic_pause

    def evaluate(self, *, session_id: str) -> dict[str, Any]:
        snapshot = self._live_gates.capture(session_id=session_id)
        pause = self._automatic_pause.evaluate(session_id=session_id)
        return {
            "schema_version": CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION,
            "status": "paused" if pause.get("pause_applied") else "clear_no_pause",
            "session_id": session_id,
            "gate_snapshot": snapshot,
            "pause_evaluation": pause,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }

    def evaluate_authenticated(
        self,
        *,
        session_id: str,
        session_token: str,
    ) -> dict[str, Any]:
        authenticated = self._runtime_authority.authenticate_for_monitoring(
            session_id,
            session_token,
        )
        if authenticated.get(
            "status"
        ) != "monitorable_bounded_session" or not authenticated.get(
            "runtime_authentication_verified"
        ):
            raise ControlledSessionLiveGateRejected(
                "controlled session pause self-check authentication rejected",
                evidence={
                    "status": "rejected",
                    "session_id": session_id,
                    "blockers": [
                        str(item) for item in authenticated.get("blockers") or []
                    ],
                    "broker_submission_enabled": False,
                    "safety": _safety_flags(),
                },
            )
        return self.evaluate(session_id=session_id)

    def evaluate_all(self) -> dict[str, Any]:
        sessions = self._runtime_authority.list_sessions(limit=500)
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for session in sessions:
            if session.get("status") != "enabled":
                continue
            session_id = str(session.get("session_id") or "")
            try:
                results.append(self.evaluate(session_id=session_id))
            except Exception as exc:
                failures.append(
                    {
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                    }
                )
        return {
            "schema_version": CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION,
            "evaluated_count": len(results),
            "paused_count": sum(item.get("status") == "paused" for item in results),
            "failure_count": len(failures),
            "results": results,
            "failures": failures,
            "automatic_resume_enabled": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }


def _snapshot_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "snapshot_id": str(row.get("snapshot_id") or payload.get("snapshot_id") or ""),
        "snapshot_fingerprint": str(
            row.get("snapshot_fingerprint") or payload.get("snapshot_fingerprint") or ""
        ),
        "session_id": str(row.get("session_id") or payload.get("session_id") or ""),
        "observed_at": str(row.get("observed_at") or payload.get("observed_at") or ""),
        "status": str(row.get("status") or payload.get("status") or "blocked"),
        "gate_snapshot": _json_object(
            row.get("gate_snapshot_json") or payload.get("gate_snapshot") or {}
        ),
        "source_evidence": _json_object(
            row.get("source_evidence_json") or payload.get("source_evidence") or {}
        ),
        "blockers": _json_list(
            row.get("blockers_json") or payload.get("blockers") or []
        ),
        "persisted": bool(row),
        "reused": reused,
        "broker_submission_enabled": False,
        "safety": _safety_flags(),
    }


def _nested_gate_status(order: dict[str, Any], gate: str) -> str:
    gateway_gates = _mapping(order.get("gateway_gates"))
    gates = _mapping(gateway_gates.get("gates"))
    item = _mapping(gates.get(gate))
    return str(item.get("status") or "missing").lower()


def _gate_blockers(gates: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    expected = {
        "account_truth_status": {"pass", "clear"},
        "risk_gate_status": {"pass", "passed"},
        "reconciliation_status": {"clear", "manually_accepted"},
        "paper_shadow_status": {"within_expectations", "manually_accepted"},
        "gateway_health_status": {"healthy"},
        "market_data_status": {"current", "confirmed", "live"},
        "budget_status": {"current_reserved", "current_reserved_non_executing"},
        "rate_limit_status": {"clear"},
    }
    for field, passing in expected.items():
        if gates.get(field) not in passing:
            blockers.append(f"live_gate_not_clear:{field}")
    if gates.get("kill_switch_enabled") is not False:
        blockers.append("live_gate_kill_switch_not_clear")
    for field in (
        "budget_exhausted",
        "daily_loss_limit_reached",
        "drawdown_limit_reached",
        "rejection_spike",
        "unexpected_account_change",
    ):
        if gates.get(field) is not False:
            blockers.append(f"live_gate_boolean_fact_not_clear:{field}")
    consecutive = gates.get("consecutive_errors")
    maximum = gates.get("max_consecutive_errors")
    if (
        not isinstance(consecutive, int)
        or not isinstance(maximum, int)
        or consecutive < 0
        or maximum <= 0
        or consecutive >= maximum
    ):
        blockers.append("live_gate_consecutive_error_limit_not_clear")
    return blockers


def _missing_gate_values() -> dict[str, Any]:
    return {
        "source_fingerprint": "",
        "account_truth_status": "missing",
        "risk_gate_status": "missing",
        "reconciliation_status": "missing",
        "paper_shadow_status": "missing",
        "gateway_health_status": "missing",
        "market_data_status": "missing",
        "budget_status": "missing",
        "rate_limit_status": "missing",
        "kill_switch_enabled": None,
        "budget_exhausted": None,
        "daily_loss_limit_reached": None,
        "drawdown_limit_reached": None,
        "rejection_spike": None,
        "unexpected_account_change": None,
        "consecutive_errors": None,
        "max_consecutive_errors": None,
    }


def _missing_snapshot(session_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_SESSION_LIVE_GATE_SCHEMA_VERSION,
        "status": "blocked",
        "session_id": session_id,
        "gate_snapshot": _missing_gate_values(),
        "blockers": list(dict.fromkeys(blockers)),
        "resolution_status": "missing",
        "resolution_blockers": list(dict.fromkeys(blockers)),
        "persisted": False,
        "broker_submission_enabled": False,
        "safety": _safety_flags(),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_contact_broker": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_resume_renew_or_expand_session": True,
        "does_not_grant_or_scale_capital_authority": True,
    }
