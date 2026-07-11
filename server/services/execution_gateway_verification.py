"""Short-lived, non-submitting runtime verification for execution gateways."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Protocol

EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION = (
    "karkinos.execution_gateway_verification.v1"
)
EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION = (
    "karkinos.execution_gateway_verification_status.v1"
)
EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE = "execution_gateway.verification_recorded"
EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE = "execution_gateway_verification"
EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE = "execution_gateway_verification"
EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT = (
    "record_non_submitting_execution_gateway_verification"
)
EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS = 60
EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS = 300

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_CAPABILITIES = (
    "can_cancel_orders",
    "can_dry_run_orders",
    "can_query_fills",
    "can_query_orders",
    "can_submit_orders",
    "supports_idempotent_client_order_id",
)
_ORDER_FIELDS = (
    "asset_class",
    "limit_price",
    "order_type",
    "quantity",
    "side",
    "symbol",
)
_FORBIDDEN_KEY_PARTS = ("credential", "password", "private_key", "secret", "token")


class ExecutionGatewayRuntimeProtocol(Protocol):
    gateway_id: str
    evidence_connector_id: str
    account_alias: str
    account_binding_status: str
    capabilities: Any

    def get_health(self) -> dict[str, Any]: ...

    def dry_run_order(self, order: dict[str, Any]) -> dict[str, Any]: ...


class ExecutionGatewayVerificationRejected(ValueError):
    """Raised after a rejected verification attempt has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ExecutionGatewayVerificationService:
    """Verify gateway readiness without submitting, cancelling, or authorizing."""

    def __init__(
        self,
        *,
        db: Any,
        gateways: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateways = list(gateways or [])
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        gateway_ids = sorted(
            str(getattr(gateway, "gateway_id", "") or "")
            for gateway in self._gateways
            if str(getattr(gateway, "gateway_id", "") or "")
        )
        duplicate_ids = sorted(
            gateway_id
            for gateway_id in set(gateway_ids)
            if gateway_ids.count(gateway_id) > 1
        )
        return {
            "schema_version": EXECUTION_GATEWAY_VERIFICATION_STATUS_SCHEMA_VERSION,
            "contract_status": "non_submitting_runtime_verification",
            "registered_gateway_ids": sorted(set(gateway_ids)),
            "registered_gateway_count": len(set(gateway_ids)),
            "duplicate_gateway_ids": duplicate_ids,
            "runtime_gateway_available": bool(gateway_ids) and not duplicate_ids,
            "production_gateway_registered": bool(gateway_ids),
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "supported_capability_requirements": list(_REQUIRED_CAPABILITIES),
            "health_max_age_seconds": EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
            "verification_max_age_seconds": (
                EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS
            ),
            "safety": _safety_flags(),
        }

    def preview(
        self,
        *,
        gateway_id: str,
        evidence_connector_id: str,
        account_alias: str,
        order_id: str,
        order_fingerprint: str,
        order_contract: dict[str, Any],
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized_gateway_id = str(gateway_id or "").strip()
        normalized_evidence_connector_id = str(evidence_connector_id or "").strip()
        normalized_account_alias = str(account_alias or "").strip()
        normalized_order_id = str(order_id or "").strip()
        normalized_order_fingerprint = str(order_fingerprint or "").strip()
        normalized_order, order_blockers = _normalize_order_contract(order_contract)
        blockers = list(order_blockers)
        for value, label in (
            (normalized_gateway_id, "gateway_id"),
            (normalized_evidence_connector_id, "evidence_connector_id"),
            (normalized_order_id, "order_id"),
        ):
            if not _ID_PATTERN.fullmatch(value):
                blockers.append(f"{label}_invalid")
        if normalized_gateway_id == normalized_evidence_connector_id:
            blockers.append("connector_roles_not_separated")
        if not normalized_account_alias:
            blockers.append("account_alias_missing")
        if not _FINGERPRINT_PATTERN.fullmatch(normalized_order_fingerprint):
            blockers.append("order_fingerprint_invalid")

        matches = [
            gateway
            for gateway in self._gateways
            if str(getattr(gateway, "gateway_id", "") or "") == normalized_gateway_id
        ]
        if not matches:
            blockers.append("execution_gateway_not_registered")
        elif len(matches) > 1:
            blockers.append("execution_gateway_id_duplicated")
        gateway = matches[0] if len(matches) == 1 else None
        capabilities = _capabilities(gateway)
        for capability in _REQUIRED_CAPABILITIES:
            if capabilities.get(capability) is not True:
                blockers.append(f"execution_gateway_capability_missing:{capability}")

        if gateway is not None:
            if (
                str(getattr(gateway, "evidence_connector_id", "") or "")
                != normalized_evidence_connector_id
            ):
                blockers.append("execution_gateway_evidence_connector_mismatch")
            if (
                str(getattr(gateway, "account_alias", "") or "")
                != normalized_account_alias
            ):
                blockers.append("execution_gateway_account_alias_mismatch")
            if str(getattr(gateway, "account_binding_status", "") or "") != (
                "verified"
            ):
                blockers.append("connector_account_binding_not_verified")

        health, health_blockers = self._health(gateway, now=now)
        blockers.extend(health_blockers)
        client_order_id = _client_order_id(
            normalized_gateway_id,
            normalized_order_id,
            normalized_order_fingerprint,
        )
        dry_run: dict[str, Any] = _missing_dry_run()
        if gateway is not None and not blockers:
            dry_run, dry_run_blockers = self._dry_run(
                gateway,
                order={
                    **normalized_order,
                    "order_id": normalized_order_id,
                    "order_fingerprint": normalized_order_fingerprint,
                    "client_order_id": client_order_id,
                },
            )
            blockers.extend(dry_run_blockers)

        source_core = {
            "schema_version": EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
            "gateway_id": normalized_gateway_id,
            "evidence_connector_id": normalized_evidence_connector_id,
            "account_alias": normalized_account_alias,
            "order_id": normalized_order_id,
            "order_fingerprint": normalized_order_fingerprint,
            "order_contract": normalized_order,
            "client_order_id": client_order_id,
            "capabilities": capabilities,
            "health": {
                key: value
                for key, value in health.items()
                if key != "current_age_seconds"
            },
            "dry_run": dry_run,
            "blockers": list(dict.fromkeys(blockers)),
        }
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **source_core,
            "verification_fingerprint": _fingerprint(source_core),
            "generated_at": now.isoformat(),
            "current_health_age_seconds": health.get("current_age_seconds"),
            "review_status": "ready_to_record" if not unique_blockers else "blocked",
            "review_ready": not unique_blockers,
            "runtime_verification_status": "not_recorded",
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }

    def record(
        self,
        *,
        gateway_id: str,
        evidence_connector_id: str,
        account_alias: str,
        order_id: str,
        order_fingerprint: str,
        order_contract: dict[str, Any],
        verification_fingerprint: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        preview = self.preview(
            gateway_id=gateway_id,
            evidence_connector_id=evidence_connector_id,
            account_alias=account_alias,
            order_id=order_id,
            order_fingerprint=order_fingerprint,
            order_contract=order_contract,
        )
        rejection_reasons: list[str] = []
        if verification_fingerprint != preview["verification_fingerprint"]:
            rejection_reasons.append("verification_fingerprint_mismatch")
        if acknowledgement != EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        if preview["blockers"]:
            rejection_reasons.append("gateway_verification_blocked")
        status = (
            "rejected"
            if rejection_reasons
            else "recorded_non_submitting_runtime_verification"
        )
        evidence = self._record_attempt(
            preview=preview,
            submitted_verification_fingerprint=verification_fingerprint,
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise ExecutionGatewayVerificationRejected(
                "execution gateway verification rejected: "
                + ", ".join(rejection_reasons),
                evidence=evidence,
            )
        return evidence

    def resolve(self, verification_fingerprint: str) -> dict[str, Any]:
        normalized = str(verification_fingerprint or "").strip()
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            return _blocked_resolution(
                normalized,
                ["verification_fingerprint_invalid"],
            )
        for item in self.list_verifications(limit=500):
            if (
                item.get("status") == "recorded_non_submitting_runtime_verification"
                and item.get("verification_fingerprint") == normalized
            ):
                recorded_at = _parse_aware_timestamp(item.get("recorded_at"))
                now = _aware_utc(self._clock())
                if recorded_at is None:
                    return _blocked_resolution(
                        normalized,
                        ["verification_recorded_at_invalid"],
                    )
                if (now - recorded_at).total_seconds() > (
                    EXECUTION_GATEWAY_VERIFICATION_MAX_AGE_SECONDS
                ):
                    return _blocked_resolution(normalized, ["verification_expired"])
                current = self.preview(
                    gateway_id=str(item.get("gateway_id") or ""),
                    evidence_connector_id=str(item.get("evidence_connector_id") or ""),
                    account_alias=str(item.get("account_alias") or ""),
                    order_id=str(item.get("order_id") or ""),
                    order_fingerprint=str(item.get("order_fingerprint") or ""),
                    order_contract=(
                        item.get("order_contract")
                        if isinstance(item.get("order_contract"), dict)
                        else {}
                    ),
                )
                if current["verification_fingerprint"] != normalized:
                    return _blocked_resolution(
                        normalized,
                        ["verification_source_changed"],
                    )
                if current["blockers"]:
                    return _blocked_resolution(
                        normalized,
                        ["verification_currently_blocked", *current["blockers"]],
                    )
                return {
                    "schema_version": EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
                    "status": "clear",
                    "verification_fingerprint": normalized,
                    "verification_id": str(item.get("verification_id") or ""),
                    "gateway_id": str(item.get("gateway_id") or ""),
                    "evidence_connector_id": str(
                        item.get("evidence_connector_id") or ""
                    ),
                    "account_alias": str(item.get("account_alias") or ""),
                    "order_id": str(item.get("order_id") or ""),
                    "order_fingerprint": str(item.get("order_fingerprint") or ""),
                    "order_contract": (
                        dict(item.get("order_contract") or {})
                        if isinstance(item.get("order_contract"), dict)
                        else {}
                    ),
                    "recorded_at": item.get("recorded_at"),
                    "runtime_gateway_verified": True,
                    "runtime_verification_status": ("verified_non_submitting_dry_run"),
                    "blockers": [],
                    "runtime_execution_authority": "disabled",
                    "broker_submission_enabled": False,
                    "authorizes_execution": False,
                    "safety": _safety_flags(),
                }
        return _blocked_resolution(normalized, ["verification_not_found"])

    def list_verifications(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
            entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
            source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _health(
        self,
        gateway: Any | None,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any], list[str]]:
        if gateway is None:
            return _missing_health(), ["execution_gateway_health_unavailable"]
        getter = getattr(gateway, "get_health", None)
        if not callable(getter):
            return _missing_health(), ["execution_gateway_health_unavailable"]
        try:
            raw = getter() or {}
        except Exception:
            return _missing_health(), ["execution_gateway_health_provider_failed"]
        raw = raw if isinstance(raw, dict) else {}
        status = str(raw.get("status") or "")
        captured_at = _parse_aware_timestamp(raw.get("captured_at"))
        blockers: list[str] = []
        age_seconds: int | None = None
        freshness = "missing"
        if status != "healthy":
            blockers.append("execution_gateway_not_healthy")
        if captured_at is None:
            blockers.append("execution_gateway_health_timestamp_invalid")
        else:
            age = (now - captured_at).total_seconds()
            age_seconds = int(max(0, age))
            if age < -30:
                freshness = "future"
                blockers.append("execution_gateway_health_timestamp_in_future")
            elif age > EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS:
                freshness = "stale"
                blockers.append("execution_gateway_health_stale")
            else:
                freshness = "fresh"
        source_fingerprint = str(raw.get("source_fingerprint") or "")
        if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
            blockers.append("execution_gateway_health_fingerprint_invalid")
        return {
            "status": status or "missing",
            "captured_at": captured_at.isoformat() if captured_at else "",
            "source_fingerprint": source_fingerprint,
            "freshness_status": freshness,
            "current_age_seconds": age_seconds,
            "max_age_seconds": EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
        }, list(dict.fromkeys(blockers))

    def _dry_run(
        self,
        gateway: Any,
        *,
        order: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        runner = getattr(gateway, "dry_run_order", None)
        if not callable(runner):
            return _missing_dry_run(), ["execution_gateway_dry_run_unavailable"]
        try:
            raw = runner(dict(order)) or {}
        except Exception:
            return _missing_dry_run(), ["execution_gateway_dry_run_failed"]
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
            blockers.append("execution_gateway_dry_run_not_accepted")
        if result["order_fingerprint"] != order["order_fingerprint"]:
            blockers.append("execution_gateway_dry_run_order_fingerprint_mismatch")
        if result["client_order_id"] != order["client_order_id"]:
            blockers.append("execution_gateway_dry_run_client_order_id_mismatch")
        if not _FINGERPRINT_PATTERN.fullmatch(result["payload_fingerprint"]):
            blockers.append("execution_gateway_dry_run_payload_fingerprint_invalid")
        if result["submitted"]:
            blockers.append("execution_gateway_dry_run_submitted_order")
        if result["broker_order_id"]:
            blockers.append("execution_gateway_dry_run_returned_broker_order_id")
        if result["side_effect_count"] != 0:
            blockers.append("execution_gateway_dry_run_reported_side_effects")
        return result, list(dict.fromkeys(blockers))

    def _record_attempt(
        self,
        *,
        preview: dict[str, Any],
        submitted_verification_fingerprint: str,
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "verification_fingerprint": preview["verification_fingerprint"],
            "submitted_verification_fingerprint": (submitted_verification_fingerprint),
            "gateway_id": preview["gateway_id"],
            "evidence_connector_id": preview["evidence_connector_id"],
            "account_alias": preview["account_alias"],
            "order_id": preview["order_id"],
            "order_fingerprint": preview["order_fingerprint"],
            "order_contract": preview["order_contract"],
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": list(rejection_reasons),
        }
        verification_id = _fingerprint(identity)
        payload = {
            "schema_version": EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
            "verification_id": verification_id,
            **identity,
            "capabilities": preview["capabilities"],
            "health": preview["health"],
            "dry_run": preview["dry_run"],
            "review_blockers": list(preview["blockers"]),
            "runtime_gateway_verified": status
            == "recorded_non_submitting_runtime_verification",
            "runtime_verification_status": (
                "verified_non_submitting_dry_run"
                if status == "recorded_non_submitting_runtime_verification"
                else "rejected"
            ),
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
            entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
            entity_id=verification_id,
            source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        now = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
            timestamp=now.isoformat(),
            entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
            entity_id=verification_id,
            source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
            source_ref=preview["verification_fingerprint"],
            payload=payload,
        )
        rows = self._db.list_events_sync(
            event_type=EXECUTION_GATEWAY_VERIFICATION_EVENT_TYPE,
            entity_type=EXECUTION_GATEWAY_VERIFICATION_ENTITY_TYPE,
            entity_id=verification_id,
            source=EXECUTION_GATEWAY_VERIFICATION_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            raise RuntimeError("execution gateway verification was not recorded")
        return _event_response(rows[0], reused=False)


def _capabilities(gateway: Any | None) -> dict[str, bool]:
    raw = getattr(gateway, "capabilities", None) if gateway is not None else None
    if isinstance(raw, dict):
        return {name: raw.get(name) is True for name in _REQUIRED_CAPABILITIES}
    return {
        name: getattr(raw, name, None) is True if raw is not None else False
        for name in _REQUIRED_CAPABILITIES
    }


def _normalize_order_contract(
    value: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    raw = value if isinstance(value, dict) else {}
    blockers: list[str] = []
    if any(
        forbidden in str(key).lower()
        for key in raw
        for forbidden in _FORBIDDEN_KEY_PARTS
    ):
        blockers.append("order_contract_contains_forbidden_field")
    if set(raw) - set(_ORDER_FIELDS):
        blockers.append("order_contract_contains_unknown_field")
    quantity = _decimal(raw.get("quantity"))
    limit_price = _decimal(raw.get("limit_price"))
    symbol = str(raw.get("symbol") or "").strip()
    side = str(raw.get("side") or "").strip().lower()
    order_type = str(raw.get("order_type") or "").strip().lower()
    asset_class = str(raw.get("asset_class") or "").strip().lower()
    if not symbol:
        blockers.append("order_symbol_missing")
    if side not in {"buy", "sell"}:
        blockers.append("order_side_invalid")
    if not asset_class:
        blockers.append("order_asset_class_missing")
    if quantity is None or quantity <= 0:
        blockers.append("order_quantity_invalid")
    if order_type != "limit":
        blockers.append("execution_gateway_verification_requires_limit_order")
    if limit_price is None or limit_price <= 0:
        blockers.append("order_limit_price_invalid")
    return {
        "symbol": symbol,
        "side": side,
        "asset_class": asset_class,
        "quantity": _decimal_string(quantity),
        "order_type": order_type,
        "limit_price": _decimal_string(limit_price),
    }, list(dict.fromkeys(blockers))


def _client_order_id(gateway_id: str, order_id: str, order_fingerprint: str) -> str:
    digest = _fingerprint(
        {
            "gateway_id": gateway_id,
            "order_id": order_id,
            "order_fingerprint": order_fingerprint,
        }
    )
    return f"karkinos-{digest[:24]}"


def _missing_health() -> dict[str, Any]:
    return {
        "status": "missing",
        "captured_at": "",
        "source_fingerprint": "",
        "freshness_status": "missing",
        "current_age_seconds": None,
        "max_age_seconds": EXECUTION_GATEWAY_HEALTH_MAX_AGE_SECONDS,
    }


def _missing_dry_run() -> dict[str, Any]:
    return {
        "status": "not_run",
        "order_fingerprint": "",
        "client_order_id": "",
        "payload_fingerprint": "",
        "submitted": False,
        "broker_order_id": "",
        "side_effect_count": 0,
    }


def _blocked_resolution(
    fingerprint: str,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_GATEWAY_VERIFICATION_SCHEMA_VERSION,
        "status": "blocked",
        "verification_fingerprint": fingerprint,
        "verification_id": "",
        "gateway_id": "",
        "evidence_connector_id": "",
        "account_alias": "",
        "order_id": "",
        "order_fingerprint": "",
        "order_contract": {},
        "recorded_at": "",
        "runtime_gateway_verified": False,
        "runtime_verification_status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "safety": _safety_flags(),
    }


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **_json_object(row.get("payload_json")),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_or_expand_authority": True,
        "does_not_reserve_or_consume_budget": True,
        "does_not_auto_resume": True,
    }


def _parse_aware_timestamp(value: object) -> datetime | None:
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


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
