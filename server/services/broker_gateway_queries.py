"""Persisted-only query workflows for the broker gateway boundary."""

from __future__ import annotations

from typing import Any

from server.contracts.broker_gateway import BROKER_GATEWAY_SCHEMA_VERSION
from server.services.broker_gateway_values import (
    broker_account_fill_payload as _broker_account_fill_payload,
)
from server.services.broker_gateway_values import (
    broker_fill_payload as _broker_fill_payload,
)
from server.services.broker_gateway_values import (
    cash_balance_payloads as _cash_balance_payloads,
)
from server.services.broker_gateway_values import decimal_value as _decimal_value
from server.services.broker_gateway_values import (
    gateway_event_payload as _gateway_event_payload,
)
from server.services.broker_gateway_values import (
    position_payloads as _position_payloads,
)


class BrokerGatewayQueryMixin:
    """Read canonical local evidence without provider or broker contact."""

    def list_connector_health(self) -> list[dict[str, Any]]:
        """Return persisted collector health without touching edge adapters."""
        return self._build_lifecycle_evidence_view().list_health()

    def query_staged_account_facts(self) -> dict[str, Any]:
        import_runs, broker_events = self._staged_broker_events(limit=20)
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "staged_broker_evidence",
            "status": "available" if broker_events else "empty",
            "query_scope": "staged_broker_evidence",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "source_import_run_ids": [
                import_run.import_run_id for import_run in import_runs
            ],
            "broker_event_count": len(broker_events),
            "cash_balances": _cash_balance_payloads(broker_events),
            "positions": _position_payloads(broker_events),
            "fills": [
                _broker_account_fill_payload(event)
                for event in broker_events
                if str(getattr(event, "event_type", "")).startswith("trade_")
            ],
            "limitations": [
                "This query reads staged broker evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
                "Staged facts must be reconciled before strategy promotion or live-like use.",
            ],
        }

    def query_connector_snapshot(self, connector_id: str) -> dict[str, Any]:
        """Compatibility entry; runtime snapshots are no longer canonical."""
        lifecycle_evidence = self.query_connector_lifecycle_evidence(connector_id)
        return {
            "schema_version": "karkinos.broker_connector_snapshot_migration.v1",
            "status": "migrated_to_persisted_lifecycle_evidence",
            "query_scope": "snapshot_compatibility_entry",
            "connector_id": lifecycle_evidence["connector_id"],
            "lifecycle_evidence": lifecycle_evidence,
            "account_facts_included": False,
            "provider_contact_performed": False,
            "reads_persisted_facts_only": True,
            "broker_submission_enabled": False,
            "can_submit_orders": False,
            "can_cancel_orders": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "migration": {
                "legacy_contract": "runtime_connector_snapshot",
                "canonical_contract": "broker_order_lifecycle_evidence",
                "legacy_runtime_snapshot_supported": False,
                "explicit_ingestion_required": True,
            },
            "limitations": [
                "This path is an explicitly marked compatibility entry only.",
                "It never calls an adapter and no longer returns runtime cash, position, order, or fill snapshots.",
            ],
        }

    def query_connector_lifecycle_evidence(
        self,
        connector_id: str,
    ) -> dict[str, Any]:
        """Read canonical broker-neutral lifecycle collector evidence."""
        return self._build_lifecycle_evidence_view().query(connector_id)

    def query_staged_fills(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip()
        safe_limit = max(1, min(int(limit), 500))
        import_runs, broker_events = self._staged_broker_events(limit=safe_limit)
        fills: list[dict[str, Any]] = []
        for event in broker_events:
            event_type = str(getattr(event, "event_type", "") or "")
            if not event_type.startswith("trade_"):
                continue
            if (
                normalized_symbol
                and str(getattr(event, "symbol", "")) != normalized_symbol
            ):
                continue
            fills.append(_broker_account_fill_payload(event))
            if len(fills) >= safe_limit:
                break
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "staged_broker_evidence",
            "status": "available" if fills else "empty",
            "query_scope": "staged_broker_fills",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "symbol": normalized_symbol or None,
            "source_import_run_ids": [
                import_run.import_run_id for import_run in import_runs
            ],
            "broker_event_count": len(broker_events),
            "fill_count": len(fills),
            "fills": fills,
            "limitations": [
                "This query reads staged broker fill evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
                "Staged fills must be reconciled before any ledger update is suggested.",
            ],
        }

    def query_order(self, order_id: str) -> dict[str, Any]:
        order = self._require_order(order_id)
        gateway_events = self._db.list_broker_gateway_events_sync(order_id=order_id)
        staged_broker_fills = self._staged_broker_fills_for_order(order)
        return {
            "schema_version": BROKER_GATEWAY_SCHEMA_VERSION,
            "gateway_id": "manual_ticket",
            "status": "query_ready",
            "query_scope": "local_audit_and_staged_broker_evidence",
            "submitted_to_broker": False,
            "can_submit_orders": False,
            "oms_order": order,
            "gateway_event_count": len(gateway_events),
            "gateway_events": [
                _gateway_event_payload(event) for event in gateway_events
            ],
            "staged_broker_fill_count": len(staged_broker_fills),
            "staged_broker_fills": staged_broker_fills,
            "limitations": [
                "This query reads local Karkinos facts and staged broker evidence only.",
                "It does not contact a broker, submit orders, or mutate OMS status.",
            ],
        }

    def _staged_broker_events(self, *, limit: int) -> tuple[list[Any], list[Any]]:
        repository = self._broker_evidence_repository()
        if repository is None:
            return [], []
        import_runs = repository.list_import_runs(limit=limit)
        broker_events: list[Any] = []
        for import_run in import_runs:
            broker_events.extend(repository.list_events(import_run.import_run_id))
        return import_runs, broker_events

    def _staged_broker_fills_for_order(
        self, order: dict[str, Any]
    ) -> list[dict[str, Any]]:
        repository = self._broker_evidence_repository()
        if repository is None:
            return []
        expected_type = (
            "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
        )
        symbol = str(order.get("symbol") or "")
        order_quantity = _decimal_value(order.get("quantity"))
        fills: list[dict[str, Any]] = []
        for import_run in repository.list_import_runs(limit=20):
            for event in repository.list_events(import_run.import_run_id):
                if getattr(event, "event_type", "") != expected_type:
                    continue
                if str(getattr(event, "symbol", "")) != symbol:
                    continue
                fills.append(
                    _broker_fill_payload(
                        event,
                        order_quantity=order_quantity,
                    )
                )
        return fills
