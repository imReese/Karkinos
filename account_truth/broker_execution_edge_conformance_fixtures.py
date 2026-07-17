"""Deterministic local fixtures for the execution-edge conformance contract."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from account_truth.broker_execution_edge_conformance import (
    BROKER_EXECUTION_EDGE_CONFORMANCE_FIXTURE_KIND,
    BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
    BROKER_EXECUTION_EDGE_CONFORMANCE_SUITE_VERSION,
    preview_broker_execution_edge_conformance_result,
)

_ORDER = {
    "order_id": "fixture-order-001",
    "order_fingerprint": "1" * 64,
    "client_order_id": "KARK-FIXTURE-ORDER-001",
    "symbol": "510300.SH",
    "side": "buy",
    "quantity": "100",
    "order_type": "limit",
    "limit_price": "4.0000",
}


class _FixtureTimeout(RuntimeError):
    pass


class _FixtureDisconnected(RuntimeError):
    pass


@dataclass
class _FixtureState:
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    cancel_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepted_submit_side_effect_count: int = 0
    lock: Any = field(default_factory=Lock)


class DeterministicFakeExecutionEdge:
    """In-memory contract fake; it has no provider or external I/O capability."""

    gateway_id = "fixture-execution-edge"
    account_alias = "fixture-account"

    def __init__(self, *, state: _FixtureState | None = None) -> None:
        self.state = state or _FixtureState()
        self.submit_call_count = 0
        self.query_call_count = 0
        self.cancel_call_count = 0
        self.disconnected = False
        self.capabilities = {
            "can_dry_run_orders": True,
            "can_submit_orders": True,
            "can_query_orders": True,
            "can_cancel_orders": True,
            "supports_idempotent_client_order_id": True,
        }

    def dry_run_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "accepted",
            "order_fingerprint": str(order["order_fingerprint"]),
            "client_order_id": str(order["client_order_id"]),
            "payload_fingerprint": _fingerprint(order),
            "side_effect_count": 0,
            "submitted": False,
        }

    def submit_order(
        self,
        order: dict[str, Any],
        *,
        timeout_after_accept: bool = False,
        definitive_rejection: bool = False,
    ) -> dict[str, Any]:
        with self.state.lock:
            self.submit_call_count += 1
            client_order_id = str(order["client_order_id"])
            existing = self.state.orders.get(client_order_id)
            if existing is not None:
                return {**existing, "status": "reused", "reused": True}
            if definitive_rejection:
                result = {
                    "status": "rejected",
                    "submitted": False,
                    "definitive": True,
                    "client_order_id": client_order_id,
                    "order_fingerprint": str(order["order_fingerprint"]),
                    "broker_order_id": "",
                    "rejection_code": "fixture_policy_rejection",
                    "filled_quantity": "0",
                    "remaining_quantity": str(order["quantity"]),
                }
            else:
                result = {
                    "status": "accepted",
                    "submitted": True,
                    "definitive": not timeout_after_accept,
                    "client_order_id": client_order_id,
                    "order_fingerprint": str(order["order_fingerprint"]),
                    "broker_order_id": (
                        f"FIXTURE-{_fingerprint(client_order_id)[:16]}"
                    ),
                    "filled_quantity": "0",
                    "remaining_quantity": str(order["quantity"]),
                }
            self.state.orders[client_order_id] = dict(result)
            if not definitive_rejection:
                self.state.accepted_submit_side_effect_count += 1
        if timeout_after_accept:
            raise _FixtureTimeout("deterministic timeout after fixture acceptance")
        return dict(result)

    def query_order(self, client_order_id: str) -> dict[str, Any]:
        self.query_call_count += 1
        if self.disconnected:
            raise _FixtureDisconnected("deterministic disconnected fixture")
        result = self.state.orders.get(client_order_id)
        if result is None:
            return {
                "status": "not_found",
                "client_order_id": client_order_id,
                "definitive": False,
            }
        return {**result, "status": "resolved", "definitive": True}

    def mark_partial_fill(self, client_order_id: str, quantity: str) -> None:
        result = self.state.orders[client_order_id]
        total = int(str(_ORDER["quantity"]))
        filled = int(quantity)
        result.update(
            {
                "status": "partially_filled",
                "filled_quantity": str(filled),
                "remaining_quantity": str(total - filled),
            }
        )

    def cancel_order(
        self,
        *,
        client_order_id: str,
        cancel_command_id: str,
        command_fingerprint: str,
    ) -> dict[str, Any]:
        if len(command_fingerprint) != 64:
            raise ValueError("exact cancel command fingerprint required")
        self.cancel_call_count += 1
        existing = self.state.cancel_results.get(cancel_command_id)
        if existing is not None:
            return {**existing, "status": "reused", "reused": True}
        order = self.state.orders.get(client_order_id)
        if order is None:
            return {"status": "blocked", "reason": "order_not_found"}
        status = (
            "partial_cancelled"
            if order.get("status") == "partially_filled"
            else "cancelled"
        )
        result = {
            "status": status,
            "client_order_id": client_order_id,
            "broker_order_id": str(order["broker_order_id"]),
            "cancel_command_id": cancel_command_id,
            "command_fingerprint": command_fingerprint,
            "filled_quantity": str(order.get("filled_quantity") or "0"),
            "cancelled_quantity": str(order.get("remaining_quantity") or "0"),
            "definitive": True,
        }
        order.update(result)
        self.state.cancel_results[cancel_command_id] = dict(result)
        return result


def run_deterministic_broker_execution_edge_conformance(
    manifest_preview: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Run the fixed local matrix without registering or contacting an adapter."""

    scenarios = [
        _capability_contract_scenario(manifest_preview),
        _dry_run_scenario(),
        _submit_scenario(),
        _rejected_submit_scenario(),
        _duplicate_submit_scenario(),
        _concurrent_submit_scenario(),
        *_unknown_recovery_scenarios(),
        _restart_recovery_scenario(),
        _cancel_requires_command_scenario(),
        _cancel_scenario(),
        _duplicate_cancel_scenario(),
        _partial_fill_cancel_race_scenario(),
        _disconnect_query_scenario(),
    ]
    return preview_broker_execution_edge_conformance_result(
        {
            "schema_version": (BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION),
            "run_id": run_id,
            "execution_edge_ref": str(manifest_preview.get("execution_edge_ref") or ""),
            "manifest_fingerprint": str(
                manifest_preview.get("manifest_fingerprint") or ""
            ),
            "suite_version": BROKER_EXECUTION_EDGE_CONFORMANCE_SUITE_VERSION,
            "fixture_kind": BROKER_EXECUTION_EDGE_CONFORMANCE_FIXTURE_KIND,
            "scenarios": scenarios,
            "provider_contacted": False,
            "adapter_registered": False,
            "production_broker_contacted": False,
            "real_order_side_effect_count": 0,
        }
    )


def _capability_contract_scenario(
    manifest_preview: dict[str, Any],
) -> dict[str, str]:
    capabilities = dict(manifest_preview.get("capabilities") or {})
    boundaries = dict(manifest_preview.get("boundaries") or {})
    passed = bool(
        capabilities
        and all(value is True for value in capabilities.values())
        and boundaries.get("default_registered") is False
        and boundaries.get("production_enabled") is False
    )
    return _scenario(
        "capability_contract_default_closed",
        "pass" if passed else "unexpected",
        {"capabilities": capabilities, "boundaries": boundaries},
    )


def _dry_run_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    result = edge.dry_run_order(dict(_ORDER))
    observed = (
        "pass"
        if result["status"] == "accepted"
        and result["side_effect_count"] == 0
        and result["submitted"] is False
        and edge.submit_call_count == 0
        else "unexpected"
    )
    return _scenario("dry_run_no_side_effect", observed, result)


def _submit_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    result = edge.submit_order(dict(_ORDER))
    observed = (
        "accepted"
        if result["client_order_id"] == _ORDER["client_order_id"]
        and result["order_fingerprint"] == _ORDER["order_fingerprint"]
        and edge.submit_call_count == 1
        else "unexpected"
    )
    return _scenario("submit_exact_identity", observed, result)


def _rejected_submit_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    result = edge.submit_order(dict(_ORDER), definitive_rejection=True)
    observed = (
        "rejected"
        if result["status"] == "rejected"
        and result["definitive"] is True
        and result["submitted"] is False
        and result["client_order_id"] == _ORDER["client_order_id"]
        and edge.state.accepted_submit_side_effect_count == 0
        else "unexpected"
    )
    return _scenario("submit_definitive_rejection", observed, result)


def _duplicate_submit_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    first = edge.submit_order(dict(_ORDER))
    replay = edge.submit_order(dict(_ORDER))
    observed = (
        "reused"
        if replay["status"] == "reused"
        and replay["broker_order_id"] == first["broker_order_id"]
        and len(edge.state.orders) == 1
        else "unexpected"
    )
    return _scenario(
        "duplicate_submit_idempotent",
        observed,
        {
            "first": first,
            "replay": replay,
            "stored_order_count": len(edge.state.orders),
        },
    )


def _concurrent_submit_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: edge.submit_order(dict(_ORDER)),
                range(2),
            )
        )
    statuses = sorted(str(item["status"]) for item in results)
    broker_order_ids = {str(item["broker_order_id"]) for item in results}
    observed = (
        "reused"
        if statuses == ["accepted", "reused"]
        and len(broker_order_ids) == 1
        and len(edge.state.orders) == 1
        and edge.state.accepted_submit_side_effect_count == 1
        else "unexpected"
    )
    return _scenario(
        "concurrent_submit_idempotent",
        observed,
        {
            "statuses": statuses,
            "broker_order_ids": sorted(broker_order_ids),
            "stored_order_count": len(edge.state.orders),
            "accepted_submit_side_effect_count": (
                edge.state.accepted_submit_side_effect_count
            ),
        },
    )


def _unknown_recovery_scenarios() -> list[dict[str, str]]:
    edge = DeterministicFakeExecutionEdge()
    try:
        edge.submit_order(dict(_ORDER), timeout_after_accept=True)
    except _FixtureTimeout:
        timeout_status = "unknown"
    else:
        timeout_status = "unexpected"
    query = edge.query_order(str(_ORDER["client_order_id"]))
    resolved = (
        "resolved"
        if query["status"] == "resolved"
        and query["client_order_id"] == _ORDER["client_order_id"]
        and edge.submit_call_count == 1
        else "unexpected"
    )

    missing_edge = DeterministicFakeExecutionEdge()
    missing = missing_edge.query_order("KARK-FIXTURE-MISSING")
    missing_status = (
        "blocked"
        if missing["status"] == "not_found" and missing_edge.submit_call_count == 0
        else "unexpected"
    )
    return [
        _scenario(
            "submit_timeout_classified_unknown",
            timeout_status,
            {
                "submit_call_count": edge.submit_call_count,
                "stored_order_count": len(edge.state.orders),
            },
        ),
        _scenario(
            "unknown_query_same_identity",
            resolved,
            {"query": query, "submit_call_count": edge.submit_call_count},
        ),
        _scenario(
            "unknown_not_found_no_resubmit",
            missing_status,
            {"query": missing, "submit_call_count": missing_edge.submit_call_count},
        ),
    ]


def _restart_recovery_scenario() -> dict[str, str]:
    state = _FixtureState()
    first = DeterministicFakeExecutionEdge(state=state)
    try:
        first.submit_order(dict(_ORDER), timeout_after_accept=True)
    except _FixtureTimeout:
        pass
    restarted = DeterministicFakeExecutionEdge(state=state)
    query = restarted.query_order(str(_ORDER["client_order_id"]))
    observed = (
        "resolved"
        if query["status"] == "resolved"
        and restarted.submit_call_count == 0
        and restarted.query_call_count == 1
        else "unexpected"
    )
    return _scenario(
        "restart_query_recovery",
        observed,
        {
            "query": query,
            "restart_submit_call_count": restarted.submit_call_count,
            "restart_query_call_count": restarted.query_call_count,
        },
    )


def _cancel_requires_command_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    edge.submit_order(dict(_ORDER))
    try:
        edge.cancel_order(
            client_order_id=str(_ORDER["client_order_id"]),
            cancel_command_id="fixture-cancel-invalid",
            command_fingerprint="",
        )
    except ValueError:
        observed = "blocked"
    else:
        observed = "unexpected"
    return _scenario(
        "cancel_requires_separate_exact_command",
        observed,
        {"cancel_call_count": edge.cancel_call_count},
    )


def _cancel_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    edge.submit_order(dict(_ORDER))
    result = edge.cancel_order(
        client_order_id=str(_ORDER["client_order_id"]),
        cancel_command_id="fixture-cancel-001",
        command_fingerprint="2" * 64,
    )
    observed = (
        "cancelled"
        if result["status"] == "cancelled"
        and result["client_order_id"] == _ORDER["client_order_id"]
        and edge.cancel_call_count == 1
        else "unexpected"
    )
    return _scenario("cancel_exact_identity", observed, result)


def _duplicate_cancel_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    edge.submit_order(dict(_ORDER))
    kwargs = {
        "client_order_id": str(_ORDER["client_order_id"]),
        "cancel_command_id": "fixture-cancel-replay",
        "command_fingerprint": "3" * 64,
    }
    first = edge.cancel_order(**kwargs)
    replay = edge.cancel_order(**kwargs)
    observed = (
        "reused"
        if replay["status"] == "reused"
        and replay["broker_order_id"] == first["broker_order_id"]
        and len(edge.state.cancel_results) == 1
        else "unexpected"
    )
    return _scenario(
        "duplicate_cancel_idempotent",
        observed,
        {
            "first": first,
            "replay": replay,
            "stored_cancel_count": len(edge.state.cancel_results),
        },
    )


def _partial_fill_cancel_race_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    edge.submit_order(dict(_ORDER))
    edge.mark_partial_fill(str(_ORDER["client_order_id"]), "40")
    result = edge.cancel_order(
        client_order_id=str(_ORDER["client_order_id"]),
        cancel_command_id="fixture-cancel-partial",
        command_fingerprint="4" * 64,
    )
    observed = (
        "partial_cancelled"
        if result["status"] == "partial_cancelled"
        and result["filled_quantity"] == "40"
        and result["cancelled_quantity"] == "60"
        else "unexpected"
    )
    return _scenario("partial_fill_cancel_race", observed, result)


def _disconnect_query_scenario() -> dict[str, str]:
    edge = DeterministicFakeExecutionEdge()
    edge.disconnected = True
    try:
        edge.query_order(str(_ORDER["client_order_id"]))
    except _FixtureDisconnected:
        observed = "blocked"
    else:
        observed = "unexpected"
    return _scenario(
        "disconnect_query_fail_closed",
        observed,
        {"query_call_count": edge.query_call_count, "submit_call_count": 0},
    )


def _scenario(
    scenario: str,
    observed_status: str,
    evidence: Any,
) -> dict[str, str]:
    expected = {
        "capability_contract_default_closed": "pass",
        "dry_run_no_side_effect": "pass",
        "submit_exact_identity": "accepted",
        "submit_definitive_rejection": "rejected",
        "duplicate_submit_idempotent": "reused",
        "concurrent_submit_idempotent": "reused",
        "submit_timeout_classified_unknown": "unknown",
        "unknown_query_same_identity": "resolved",
        "unknown_not_found_no_resubmit": "blocked",
        "restart_query_recovery": "resolved",
        "cancel_requires_separate_exact_command": "blocked",
        "cancel_exact_identity": "cancelled",
        "duplicate_cancel_idempotent": "reused",
        "partial_fill_cancel_race": "partial_cancelled",
        "disconnect_query_fail_closed": "blocked",
    }[scenario]
    return {
        "scenario": scenario,
        "expected_status": expected,
        "observed_status": observed_status,
        "evidence_fingerprint": _fingerprint(evidence),
    }


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DeterministicFakeExecutionEdge",
    "run_deterministic_broker_execution_edge_conformance",
]
