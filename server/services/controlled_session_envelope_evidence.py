"""Persisted capital and OMS evidence resolution for session envelopes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_ENTITY_TYPE,
    CAPITAL_AUTHORIZATION_EVENT_SOURCE,
    CAPITAL_AUTHORIZATION_EVENT_TYPE,
)
from server.services.controlled_session_envelope_policy import (
    gateway_gate_summary as _gateway_gate_summary,
)
from server.services.controlled_session_envelope_values import (
    decimal_string as _decimal_string,
)
from server.services.controlled_session_envelope_values import decimal_value as _decimal
from server.services.controlled_session_envelope_values import (
    json_object as _json_object,
)
from server.services.controlled_session_envelope_values import (
    missing_capital_summary as _missing_capital_summary,
)
from server.services.controlled_session_envelope_values import (
    parse_timestamp as _parse_timestamp,
)


class ControlledSessionEnvelopeEvidenceMixin:
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
                    "order_fingerprint": self._build_order_fingerprint(order),
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
                        self._build_execution_gateway_order_contract(order)
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
            binding, binding_blockers = (
                self._resolve_execution_gateway_verification_binding(
                    self._execution_gateway_verification_provider,
                    fingerprint=verification_fingerprints.get(order_id, ""),
                    expected_gateway_id=str(context.get("execution_gateway_id") or ""),
                    expected_evidence_connector_id=str(
                        context.get("evidence_connector_id") or ""
                    ),
                    expected_account_alias=str(context.get("account_alias") or ""),
                    expected_order_id=order_id,
                    expected_order_fingerprint=str(
                        order.get("order_fingerprint") or ""
                    ),
                    expected_order_contract=(
                        order.get("gateway_order_contract")
                        if isinstance(order.get("gateway_order_contract"), dict)
                        else {}
                    ),
                )
            )
            results.append(binding)
            blockers.extend(f"{reason}:{order_id}" for reason in binding_blockers)
        return results, list(dict.fromkeys(blockers))
