from __future__ import annotations

from typing import Any

import pytest

from server.db import AppDatabase
from server.models import AccountStrategyAssignment
from server.services.strategy_contribution import build_strategy_contribution_report


def _assignment() -> AccountStrategyAssignment:
    return AccountStrategyAssignment(strategy_id="dual_ma")


def _fill(
    *,
    fill_id: str = "FILL-1",
    side: str = "buy",
    quantity: float = 100,
) -> dict[str, Any]:
    return {
        "fill_id": fill_id,
        "timestamp": "2026-07-16T09:35:00+08:00",
        "symbol": "510300",
        "side": side,
        "fill_price": 4.57,
        "fill_quantity": quantity,
        "commission": 5.0,
        "slippage": 1.5,
        "asset_class": "fund",
    }


def _evidence(*fills: dict[str, Any], unattributed: int = 0) -> dict[str, Any]:
    return {
        "linked_fills": list(fills),
        "unattributed_fill_count": unattributed,
    }


def _database(tmp_path) -> AppDatabase:
    db = AppDatabase(tmp_path / "strategy-contribution.db")
    db.init_sync()
    return db


def _post_fill(db: AppDatabase, fill: dict[str, Any]) -> int:
    return db.insert_ledger_entry_sync(
        entry_type=f"trade_{fill['side']}",
        timestamp=fill["timestamp"],
        amount=abs(float(fill["fill_price"]) * float(fill["fill_quantity"])),
        symbol=fill["symbol"],
        direction=fill["side"],
        quantity=fill["fill_quantity"],
        price=fill["fill_price"],
        commission=fill["commission"],
        gross_amount=abs(float(fill["fill_price"]) * float(fill["fill_quantity"])),
        net_cash_impact=-462 if fill["side"] == "buy" else 452,
        fee_breakdown_json='{"commission":"5","stamp_tax":"0"}',
        asset_class=fill["asset_class"],
        note="strategy contribution fixture",
        source="controlled_submission_ledger_posting",
        source_ref=fill["fill_id"],
    )


def _publish_quote(
    db: AppDatabase,
    *,
    price: float = 4.8,
    quote_status: str = "confirmed",
) -> dict[str, Any]:
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=price,
        quote_timestamp="2026-07-16T15:00:00+08:00",
        quote_source="deterministic_fixture",
        provider_name="deterministic_fixture",
        provider_status="ok",
        quote_status=quote_status,
    )
    return db.publish_current_valuation_snapshot_sync()


def test_no_linked_fill_is_not_an_actionable_review() -> None:
    report = build_strategy_contribution_report(
        db=object(),
        assignment=_assignment(),
        evidence=_evidence(),
    )

    assert report.contribution_status == "no_linked_fills"
    assert report.evidence_binding_status == "not_applicable"
    assert report.next_manual_action == "no_action_until_strategy_linked_fill_exists"
    assert report.strategy_health_status == "not_applicable"
    assert report.net_contribution is None


def test_linked_fill_without_ledger_posting_fails_closed(tmp_path) -> None:
    report = build_strategy_contribution_report(
        db=_database(tmp_path),
        assignment=_assignment(),
        evidence=_evidence(_fill()),
    )

    assert report.contribution_status == "ledger_posting_pending"
    assert report.evidence_binding_status == "blocked"
    assert report.ledger_posted_fill_count == 0
    assert report.unposted_linked_fill_count == 1
    assert report.net_contribution is None
    assert report.evidence_refs == ["fill:FILL-1"]


def test_posted_fill_without_published_valuation_fails_closed(tmp_path) -> None:
    db = _database(tmp_path)
    fill = _fill()
    _post_fill(db, fill)
    db.set_runtime_control_sync(
        "valuation_snapshot_publication",
        {"status": "missing"},
    )

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "valuation_snapshot_missing"
    assert report.next_manual_action == "publish_persisted_valuation_snapshot"
    assert report.net_contribution is None


def test_unconfirmed_valuation_does_not_become_strategy_pnl(tmp_path) -> None:
    db = _database(tmp_path)
    fill = _fill()
    _post_fill(db, fill)
    _publish_quote(db, quote_status="stale")

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "valuation_missing"
    assert report.missing_valuation_symbols == ["510300"]
    assert report.net_contribution is None


def test_snapshot_identity_drift_blocks_replay(tmp_path) -> None:
    db = _database(tmp_path)
    fill = _fill()
    _post_fill(db, fill)
    published = _publish_quote(db)
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.9,
        quote_timestamp="2026-07-16T15:01:00+08:00",
        quote_source="deterministic_fixture",
        provider_name="deterministic_fixture",
        provider_status="ok",
        quote_status="confirmed",
    )

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "valuation_identity_drift"
    assert report.valuation_snapshot_id == published["snapshot_id"]
    assert report.contribution_fingerprint is None
    assert report.net_contribution is None


def test_sell_without_strategy_owned_inventory_is_blocked(tmp_path) -> None:
    db = _database(tmp_path)
    fill = _fill(side="sell")
    _post_fill(db, fill)
    _publish_quote(db)

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "inventory_lineage_incomplete"
    assert report.next_manual_action == "review_strategy_inventory_lineage"
    assert report.net_contribution is None


def test_ready_projection_is_read_only_and_provider_free(tmp_path, monkeypatch) -> None:
    db = _database(tmp_path)
    fill = _fill()
    ledger_id = _post_fill(db, fill)
    published = _publish_quote(db)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("strategy contribution projection attempted a database write")

    monkeypatch.setattr(db, "set_runtime_control_sync", unexpected_write)
    monkeypatch.setattr(db, "save_valuation_snapshot_sync", unexpected_write)

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "evidence_bound_from_posted_fills"
    assert report.evidence_binding_status == "bound"
    assert report.ledger_cutoff_id == published["ledger_cutoff_id"]
    assert f"ledger_entry:{ledger_id}" in report.evidence_refs
    assert report.contribution_fingerprint
    assert report.persisted_facts_only is True
    assert report.provider_contacted is False
    assert report.database_writes_performed is False
    assert report.authorizes_execution is False


def test_partial_fee_breakdown_does_not_drop_posted_commission(tmp_path) -> None:
    db = _database(tmp_path)
    fill = _fill()
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp=fill["timestamp"],
        amount=457,
        symbol=fill["symbol"],
        direction=fill["side"],
        quantity=fill["fill_quantity"],
        price=fill["fill_price"],
        commission=fill["commission"],
        gross_amount=457,
        net_cash_impact=-464,
        fee_breakdown_json='{"stamp_tax":"2"}',
        asset_class=fill["asset_class"],
        note="partial fee fixture",
        source="controlled_submission_ledger_posting",
        source_ref=fill["fill_id"],
    )
    _publish_quote(db)

    report = build_strategy_contribution_report(
        db=db,
        assignment=_assignment(),
        evidence=_evidence(fill),
    )

    assert report.contribution_status == "evidence_bound_from_posted_fills"
    assert report.total_commission == 5
    assert report.total_tax == 2
    assert report.net_contribution == 16
