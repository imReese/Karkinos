from __future__ import annotations

from server.models import PortfolioSnapshot, PositionResponse
from server.services.current_holding_market_evidence_review import (
    build_current_holding_market_evidence_review,
)


def _position(
    symbol: str,
    *,
    quantity: float,
    quote_status: str,
    asset_class: str = "stock",
    quote_source: str | None = "fixture",
) -> PositionResponse:
    return PositionResponse(
        symbol=symbol,
        name=f"Asset {symbol}",
        asset_class=asset_class,
        quantity=quantity,
        available_qty=quantity,
        frozen_qty=0,
        avg_cost=10,
        latest_price=11,
        market_value=quantity * 11,
        unrealized_pnl=quantity,
        realized_pnl=0,
        commission_paid=0,
        quote_timestamp="2026-07-17T15:00:00+08:00",
        quote_status=quote_status,
        quote_source=quote_source,
    )


def _snapshot(positions: list[PositionResponse]) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=1000,
        total_equity=2000,
        positions=positions,
        allocation=[],
        valuation_snapshot_id="valuation-review-fixture",
        valuation_as_of="2026-07-17T15:00:00+08:00",
        valuation_trade_date="2026-07-17",
        valuation_policy="karkinos.persisted_valuation.v4",
        valuation_status="degraded",
        ledger_cutoff_id=17,
        ledger_fingerprint="ledger-fingerprint",
        quote_set_fingerprint="quote-set-fingerprint",
    )


def test_review_projects_only_current_nonzero_unconfirmed_holdings() -> None:
    report = build_current_holding_market_evidence_review(
        _snapshot(
            [
                _position("600001", quantity=100, quote_status="confirmed"),
                _position(
                    "FUND-A",
                    quantity=12.5,
                    quote_status="live",
                    asset_class="fund",
                    quote_source="eastmoney_fund_estimate",
                ),
                _position("NEGATIVE", quantity=-2, quote_status="stale"),
                _position("MISSING", quantity=3, quote_status="missing"),
                _position("RESIDUAL", quantity=0.0000004, quote_status="missing"),
                _position("CLOSED", quantity=0, quote_status="missing"),
            ]
        )
    )

    assert report.status == "review_required"
    assert report.current_holding_count == 4
    assert report.confirmed_holding_count == 1
    assert report.review_required_count == 3
    assert report.fund_nav_review_count == 1
    assert report.stale_or_cached_review_count == 1
    assert report.missing_or_error_review_count == 1
    assert report.refreshable_symbols == ["FUND-A", "MISSING", "NEGATIVE"]
    assert [item.symbol for item in report.items] == [
        "MISSING",
        "NEGATIVE",
        "FUND-A",
    ]
    fund = next(item for item in report.items if item.symbol == "FUND-A")
    assert fund.quote_status == "confirmed_nav_missing"
    assert fund.next_manual_action == (
        "wait_for_confirmed_nav_then_run_explicit_refresh"
    )
    assert fund.blocks_authoritative_decisions is True
    assert report.valuation_snapshot_id == "valuation-review-fixture"
    assert report.ledger_cutoff_id == 17
    assert report.reads_persisted_facts_only is True
    assert report.provider_contact_performed is False
    assert report.runtime_connector_query_performed is False
    assert report.database_writes_performed is False
    assert report.does_not_mutate_oms is True
    assert report.does_not_mutate_production_ledger is True
    assert report.does_not_mutate_risk is True
    assert report.does_not_mutate_kill_switch is True
    assert report.does_not_change_capital_authority is True
    assert report.authorizes_execution is False


def test_review_is_deterministic_and_changes_only_with_bound_evidence() -> None:
    snapshot = _snapshot([_position("600001", quantity=100, quote_status="stale")])

    first = build_current_holding_market_evidence_review(snapshot)
    restarted = build_current_holding_market_evidence_review(snapshot.model_copy())
    refreshed = build_current_holding_market_evidence_review(
        snapshot.model_copy(
            update={
                "quote_set_fingerprint": "new-quote-set-fingerprint",
                "positions": [
                    _position("600001", quantity=100, quote_status="confirmed")
                ],
            }
        )
    )

    assert first.review_fingerprint == restarted.review_fingerprint
    assert refreshed.review_fingerprint != first.review_fingerprint
    assert refreshed.status == "complete"
    assert refreshed.review_required_count == 0
    assert refreshed.refreshable_symbols == []


def test_review_fails_closed_when_valuation_identity_is_missing() -> None:
    snapshot = _snapshot([_position("600001", quantity=100, quote_status="confirmed")])
    snapshot = snapshot.model_copy(
        update={
            "valuation_snapshot_id": None,
            "quote_set_fingerprint": None,
            "ledger_fingerprint": None,
        }
    )

    report = build_current_holding_market_evidence_review(snapshot)

    assert report.status == "blocked_identity"
    assert report.next_manual_action == "restore_valuation_identity_before_review"
    assert report.source_blockers == [
        "valuation_snapshot_id_missing",
        "quote_set_fingerprint_missing",
        "ledger_fingerprint_missing",
    ]
    assert report.confirmed_holding_count == 1
    assert report.authorizes_execution is False


def test_review_reports_no_current_holdings_without_inventing_tasks() -> None:
    report = build_current_holding_market_evidence_review(_snapshot([]))

    assert report.status == "no_current_holdings"
    assert report.current_holding_count == 0
    assert report.review_required_count == 0
    assert report.items == []
    assert report.next_manual_action == "none"


def test_review_keeps_unknown_quote_status_explicit() -> None:
    report = build_current_holding_market_evidence_review(
        _snapshot([_position("UNKNOWN", quantity=1, quote_status="mystery_state")])
    )

    assert report.review_required_count == 1
    assert report.unknown_status_review_count == 1
    assert report.items[0].review_reason == "quote_status_not_confirmed"
    assert (
        report.items[0].next_manual_action
        == "review_unknown_quote_status_before_refresh"
    )
