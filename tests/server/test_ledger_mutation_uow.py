"""Transactional and replay contracts for canonical ledger mutations."""

from __future__ import annotations

import sqlite3

import pytest

from server.contracts.content_identity import canonical_json
from server.contracts.idempotency import IdempotencyConflict
from server.contracts.ledger_mutations import (
    LedgerAppendCommand,
    LedgerEntryDraft,
    LedgerMutationConflict,
    LedgerTradeSettlementCommand,
)
from server.db import AppDatabase


def _append_command(
    request_id: str,
    *,
    source_ref: str,
    note: str = "verified ledger write",
    symbol: str = "600519",
) -> LedgerAppendCommand:
    return LedgerAppendCommand(
        operator_id="local-owner",
        request_id=request_id,
        entry=LedgerEntryDraft(
            entry_type="trade_sell",
            timestamp="2026-08-26T10:00:00+08:00",
            amount=1000.0,
            symbol=symbol,
            direction="sell",
            quantity=100.0,
            price=10.0,
            commission=5.0,
            gross_amount=1000.0,
            net_cash_impact=995.0,
            fee_breakdown_json=canonical_json(
                {
                    "commission": "5.0",
                    "stamp_tax": "0",
                    "transfer_fee": "0",
                    "other_fees": "0",
                    "total_fee": "5.0",
                }
            ),
            fee_rule_id="manual_fee_input",
            fee_rule_version="manual_fee_input",
            cost_basis_method="moving_average_buy_cost",
            source="manual",
            source_ref=source_ref,
            note=note,
        ),
    )


def _settlement_command(
    *,
    request_id: str,
    entry_id: int,
    expected_entry_fingerprint: str,
    net_cash_impact: float = 993.5,
) -> LedgerTradeSettlementCommand:
    return LedgerTradeSettlementCommand(
        operator_id="local-owner",
        request_id=request_id,
        entry_id=entry_id,
        expected_entry_fingerprint=expected_entry_fingerprint,
        commission=5.0,
        net_cash_impact=net_cash_impact,
        fee_breakdown_json=canonical_json(
            {
                "commission": "5.0",
                "stamp_tax": "1.5",
                "transfer_fee": "0",
                "other_fees": "0",
                "total_fee": "6.5",
            }
        ),
        settled_at="2026-08-27T16:00:00+08:00",
        settlement_source="broker_statement",
        settlement_source_ref="broker-fill-600519-1",
        settlement_note="reviewed broker statement",
    )


def _trade_draft(**overrides) -> LedgerEntryDraft:
    values = {
        "entry_type": "trade_buy",
        "timestamp": "2026-08-26T10:00:00+08:00",
        "amount": 1000.0,
        "symbol": "600519",
        "direction": "buy",
        "quantity": 100.0,
        "price": 10.0,
        "commission": 5.0,
        "gross_amount": 1000.0,
        "net_cash_impact": -1005.0,
        "source": "manual",
        "source_ref": "invalid-trade-boundary",
    }
    values.update(overrides)
    return LedgerEntryDraft(**values)


def _count(database: AppDatabase, table: str) -> int:
    with sqlite3.connect(database.path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_append_claim_replays_exact_request_and_rejects_changed_payload(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    command = _append_command("ledger-request-1", source_ref="manual-ledger-1")

    created = database.append_ledger_entry_sync(command)
    replayed = database.append_ledger_entry_sync(command)

    assert replayed.replayed is True
    assert replayed.entry["id"] == created.entry["id"]
    assert replayed.request_fingerprint == created.request_fingerprint
    assert _count(database, "ledger_entries") == 1
    assert _count(database, "ledger_mutation_claims") == 1
    assert _count(database, "valuation_snapshots") == 1

    changed = _append_command(
        "ledger-request-1",
        source_ref="manual-ledger-1",
        note="different immutable input",
    )
    with pytest.raises(IdempotencyConflict):
        database.append_ledger_entry_sync(changed)
    assert _count(database, "ledger_entries") == 1


def test_append_uses_complete_uncommitted_ledger_for_valuation(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    database.append_ledger_entry_sync(
        _append_command("ledger-request-1", source_ref="manual-ledger-1")
    )
    original_writer = database._financial_facts._valuation_transaction_writer
    captured_ids: list[int] = []

    def capture_full_ledger(conn, **kwargs):
        rows = kwargs["candidate_ledger_rows"]
        captured_ids.extend(int(row["id"]) for row in rows)
        return original_writer(conn, **kwargs)

    database._financial_facts._valuation_transaction_writer = capture_full_ledger
    second = database.append_ledger_entry_sync(
        _append_command(
            "ledger-request-2",
            source_ref="manual-ledger-2",
            symbol="000001",
        )
    )

    assert captured_ids == [1, int(second.entry["id"])]


def test_append_rolls_back_claim_ledger_event_and_publication_failure(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    original_writer = database._financial_facts._valuation_transaction_writer

    def fail_after_publication(conn, **kwargs):
        original_writer(conn, **kwargs)
        raise RuntimeError("injected valuation publication failure")

    database._financial_facts._valuation_transaction_writer = fail_after_publication

    with pytest.raises(RuntimeError, match="injected valuation publication failure"):
        database.append_ledger_entry_sync(
            _append_command("ledger-request-fault", source_ref="manual-ledger-fault")
        )

    assert _count(database, "ledger_entries") == 0
    assert _count(database, "ledger_mutation_claims") == 0
    assert _count(database, "event_log") == 0
    assert _count(database, "valuation_snapshots") == 0


def test_legacy_insert_adapter_has_no_weak_publication_bypass(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    original_writer = database._financial_facts._valuation_transaction_writer

    def fail_after_publication(conn, **kwargs):
        original_writer(conn, **kwargs)
        raise RuntimeError("legacy publication failure")

    database._financial_facts._valuation_transaction_writer = fail_after_publication

    with pytest.raises(RuntimeError, match="legacy publication failure"):
        database.insert_ledger_entry_sync(
            entry_type="cash_deposit",
            timestamp="2026-08-26T10:00:00+08:00",
            amount=1000.0,
            asset_class="cash",
            source="internal_fixture",
            source_ref="cash-1",
        )

    assert _count(database, "ledger_entries") == 0
    assert _count(database, "ledger_mutation_claims") == 0
    assert _count(database, "event_log") == 0


@pytest.mark.parametrize(
    ("overrides", "error"),
    (
        ({"quantity": -1.0}, "quantity must be positive"),
        ({"price": float("nan")}, "price must be a finite number"),
        ({"commission": float("inf")}, "commission must be a finite number"),
        ({"gross_amount": None}, "gross_amount must be a finite number"),
        ({"net_cash_impact": -1004.0}, "net_cash_impact must equal"),
    ),
)
def test_typed_append_rejects_invalid_trade_before_uow(
    tmp_path,
    overrides,
    error,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()

    with pytest.raises(ValueError, match=error):
        database.append_ledger_entry_sync(
            LedgerAppendCommand(
                operator_id="local-owner",
                request_id="invalid-trade-request",
                entry=_trade_draft(**overrides),
            )
        )

    assert _count(database, "ledger_entries") == 0
    assert _count(database, "ledger_mutation_claims") == 0


@pytest.mark.parametrize(
    ("entry", "error"),
    (
        (
            {
                "entry_type": "cash_deposit",
                "timestamp": "2026-08-26T10:00:00+08:00",
                "amount": 0.0,
                "asset_class": "cash",
            },
            "cash ledger amount must be positive",
        ),
        (
            {
                "entry_type": "dividend",
                "timestamp": "2026-08-26T10:00:00+08:00",
                "amount": -1.0,
                "symbol": "600519",
            },
            "dividend amount must be positive",
        ),
        (
            {
                "entry_type": "manual_adjustment",
                "timestamp": "2026-08-26T10:00:00+08:00",
                "amount": float("nan"),
            },
            "amount must be a finite number",
        ),
    ),
)
def test_typed_append_rejects_invalid_non_trade_fact_before_uow(
    tmp_path,
    entry,
    error,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()

    with pytest.raises(ValueError, match=error):
        database.append_ledger_entry_sync(
            LedgerAppendCommand(
                operator_id="local-owner",
                request_id="invalid-non-trade-request",
                entry=LedgerEntryDraft(**entry),
            )
        )

    assert _count(database, "ledger_entries") == 0
    assert _count(database, "ledger_mutation_claims") == 0


def test_settlement_is_idempotent_cas_and_preserves_estimate(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    appended = database.append_ledger_entry_sync(
        _append_command("ledger-request-1", source_ref="manual-ledger-1")
    )
    command = _settlement_command(
        request_id="ledger-settlement-1",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint=appended.entry_fingerprint,
    )

    settled = database.settle_ledger_trade_sync(command)
    replayed = database.settle_ledger_trade_sync(command)

    assert replayed.replayed is True
    assert replayed.entry_fingerprint == settled.entry_fingerprint
    assert settled.entry["settlement_status"] == "confirmed"
    assert settled.entry["estimated_net_cash_impact"] == 995.0
    assert settled.entry["net_cash_impact"] == 993.5
    events = database.list_events_sync(
        event_type="portfolio.trade_settlement.confirmed",
        entity_type="ledger_entry",
        entity_id=str(appended.entry["id"]),
    )
    assert len(events) == 1

    changed = _settlement_command(
        request_id="ledger-settlement-1",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint=appended.entry_fingerprint,
        net_cash_impact=992.5,
    )
    with pytest.raises(IdempotencyConflict):
        database.settle_ledger_trade_sync(changed)

    new_request = _settlement_command(
        request_id="ledger-settlement-2",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint=appended.entry_fingerprint,
    )
    with pytest.raises(LedgerMutationConflict, match="already confirmed"):
        database.settle_ledger_trade_sync(new_request)


def test_settlement_rejects_inconsistent_economics_before_claim(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    appended = database.append_ledger_entry_sync(
        _append_command("ledger-request-1", source_ref="manual-ledger-1")
    )
    before = database.get_ledger_entry_sync(int(appended.entry["id"]))
    command = _settlement_command(
        request_id="ledger-settlement-invalid-economics",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint=appended.entry_fingerprint,
        net_cash_impact=992.5,
    )

    with pytest.raises(ValueError, match="does not match trade gross amount"):
        database.settle_ledger_trade_sync(command)

    assert database.get_ledger_entry_sync(int(appended.entry["id"])) == before
    assert _count(database, "ledger_mutation_claims") == 1
    assert (
        database.list_events_sync(
            event_type="portfolio.trade_settlement.confirmed",
            entity_type="ledger_entry",
            entity_id=str(appended.entry["id"]),
        )
        == []
    )


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_settlement_command_rejects_non_finite_money(value) -> None:
    with pytest.raises(ValueError, match="net_cash_impact must be a finite number"):
        _settlement_command(
            request_id="ledger-settlement-non-finite",
            entry_id=1,
            expected_entry_fingerprint="a" * 64,
            net_cash_impact=value,
        )


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_settlement_command_rejects_non_finite_commission(value) -> None:
    with pytest.raises(ValueError, match="commission must be a finite number"):
        LedgerTradeSettlementCommand(
            operator_id="local-owner",
            request_id="ledger-settlement-non-finite-commission",
            entry_id=1,
            expected_entry_fingerprint="a" * 64,
            commission=value,
            net_cash_impact=993.5,
            fee_breakdown_json=canonical_json(
                {
                    "commission": "5.0",
                    "stamp_tax": "1.5",
                    "transfer_fee": "0",
                    "other_fees": "0",
                    "total_fee": "6.5",
                }
            ),
            settled_at="2026-08-27T16:00:00+08:00",
            settlement_source="broker_statement",
            settlement_source_ref="broker-fill-600519-1",
        )


def test_settlement_rejects_stale_expected_state_before_claim(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    appended = database.append_ledger_entry_sync(
        _append_command("ledger-request-1", source_ref="manual-ledger-1")
    )
    command = _settlement_command(
        request_id="ledger-settlement-stale",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint="0" * 64,
    )

    with pytest.raises(LedgerMutationConflict, match="changed after review"):
        database.settle_ledger_trade_sync(command)

    current = database.get_ledger_entry_sync(int(appended.entry["id"]))
    assert current is not None
    assert current["settlement_status"] is None
    assert _count(database, "ledger_mutation_claims") == 1


def test_settlement_publication_failure_rolls_back_cas_event_and_claim(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    appended = database.append_ledger_entry_sync(
        _append_command("ledger-request-1", source_ref="manual-ledger-1")
    )
    before = database.get_ledger_entry_sync(int(appended.entry["id"]))
    original_writer = database._financial_facts._valuation_transaction_writer

    def fail_after_publication(conn, **kwargs):
        original_writer(conn, **kwargs)
        raise RuntimeError("settlement publication failure")

    database._financial_facts._valuation_transaction_writer = fail_after_publication
    command = _settlement_command(
        request_id="ledger-settlement-fault",
        entry_id=int(appended.entry["id"]),
        expected_entry_fingerprint=appended.entry_fingerprint,
    )

    with pytest.raises(RuntimeError, match="settlement publication failure"):
        database.settle_ledger_trade_sync(command)

    assert database.get_ledger_entry_sync(int(appended.entry["id"])) == before
    events = database.list_events_sync(
        event_type="portfolio.trade_settlement.confirmed",
        entity_type="ledger_entry",
        entity_id=str(appended.entry["id"]),
    )
    assert events == []
    with sqlite3.connect(database.path) as conn:
        claim = conn.execute(
            "SELECT 1 FROM ledger_mutation_claims WHERE request_id = ?",
            (command.request_id,),
        ).fetchone()
    assert claim is None
