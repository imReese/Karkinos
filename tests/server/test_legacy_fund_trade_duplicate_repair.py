from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from server import legacy_fund_trade_duplicate_repair_cli as repair_cli
from server.ledger.models import LedgerEntry
from server.persistence.financial_facts_ledger import insert_ledger_entry_on_connection
from server.persistence.initializer import initialize_database
from server.projections.legacy_fund_trade_duplicate_correction import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    LegacyFundTradeDuplicateCorrectionError,
    legacy_fund_trade_duplicate_group_fingerprint,
    resolve_legacy_fund_trade_duplicate_exclusions,
)
from server.projections.service import build_portfolio_projection
from server.services.legacy_fund_trade_duplicate_repair import (
    LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION,
    LegacyFundTradeDuplicateRepairBlocked,
    LegacyFundTradeDuplicateRepairCommand,
    LegacyFundTradeDuplicateRepairService,
)

pytestmark = pytest.mark.unit

NOW = "2026-08-30T20:00:00+08:00"


def _fixture_database(
    path: Path,
    *,
    group_sizes: tuple[int, ...] = (5, 2, 2),
    asset_class: str = "fund",
    direction: str = "buy",
    live_offset_shape: bool = False,
    high_precision: bool = False,
) -> None:
    initialize_database(path)
    with sqlite3.connect(path) as conn:
        for group_index, pair_count in enumerate(group_sizes, start=1):
            symbol = f"FIXTURE-{group_index}"
            for pair_index in range(1, pair_count + 1):
                timestamp = (
                    f"2026-04-{group_index * 7 + pair_index:02d}" "T13:22:58+08:00"
                )
                created_at = timestamp
                quantity = (
                    float(pair_index) + 0.12345678901234567
                    if high_precision
                    else float(pair_index * 10)
                )
                price = (
                    float(group_index) + 0.9876543210987654
                    if high_precision
                    else float(group_index + 1)
                )
                commission = 0.0 if high_precision else float(group_index) / 10
                gross = quantity * price
                net = (
                    -(gross + commission) if direction == "buy" else gross - commission
                )
                note = "migration fixture"
                trade_id = int(
                    conn.execute(
                        """
                        INSERT INTO trades (
                            timestamp, symbol, direction, quantity, price,
                            commission, asset_class, note, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            timestamp,
                            symbol,
                            direction,
                            quantity,
                            price,
                            commission,
                            asset_class,
                            note,
                            created_at,
                        ),
                    ).lastrowid
                )
                insert_ledger_entry_on_connection(
                    conn,
                    entry_type=f"trade_{direction}",
                    timestamp=timestamp,
                    amount=gross,
                    symbol=symbol,
                    direction=direction,
                    quantity=quantity,
                    price=price,
                    commission=commission,
                    gross_amount=gross,
                    net_cash_impact=net,
                    fee_breakdown_json=json.dumps(
                        {
                            "commission": str(commission),
                            "subscription_fee": "0",
                        },
                        sort_keys=True,
                    ),
                    fee_rule_id="legacy_manual_input",
                    fee_rule_version="legacy_manual_input",
                    asset_class=asset_class,
                    note=note,
                    source="manual",
                    source_ref=None,
                    created_at=created_at,
                )
                canonical_id = insert_ledger_entry_on_connection(
                    conn,
                    entry_type=f"trade_{direction}",
                    timestamp=timestamp,
                    amount=gross,
                    symbol=symbol,
                    direction=direction,
                    quantity=quantity,
                    price=price,
                    commission=commission,
                    gross_amount=gross,
                    net_cash_impact=net,
                    fee_rule_id="legacy_manual_trade",
                    fee_rule_version="legacy_manual_trade",
                    cost_basis_method="moving_average_buy_cost",
                    asset_class=asset_class,
                    note=note,
                    source="portfolio_trade",
                    source_ref=f"trade:{trade_id}",
                    created_at=created_at,
                )
                if live_offset_shape:
                    conn.execute(
                        "UPDATE ledger_entries SET timestamp = ? WHERE id = ?",
                        (timestamp, canonical_id),
                    )
        conn.commit()


def _counts(path: Path) -> tuple[int, int, int]:
    with sqlite3.connect(path) as conn:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("ledger_entries", "event_log", "trades")
        )


def _rows(path: Path) -> list[dict[str, object]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ledger_entries ORDER BY timestamp, id"
            ).fetchall()
        ]


def _writer(calls: list[list[dict[str, object]]]):
    def write(conn: sqlite3.Connection, **kwargs) -> dict[str, object]:
        candidates = [dict(row) for row in kwargs["candidate_ledger_rows"]]
        calls.append(candidates)
        assert conn.in_transaction
        return {"snapshot_id": "fixture-valuation", "status": "complete"}

    return write


def _command(preview: dict[str, object], *, command_id: str = "repair-1"):
    return LegacyFundTradeDuplicateRepairCommand(
        command_id=command_id,
        operator_id="fixture-owner",
        preview_fingerprint=str(preview["preview_fingerprint"]),
        confirmation=LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION,
    )


def test_preview_is_zero_write_private_and_finds_generic_live_shape(tmp_path) -> None:
    path = tmp_path / "repair-preview.db"
    _fixture_database(path)
    before = _counts(path)

    report = LegacyFundTradeDuplicateRepairService(path).preview()

    assert report["status"] == "ready"
    assert report["pair_count"] == 9
    assert report["affected_fund_count"] == 3
    assert report["group_pair_counts"] == [5, 2, 2]
    assert report["database_writes_performed"] is False
    assert report["provider_contact_performed"] is False
    assert _counts(path) == before
    encoded = json.dumps(report)
    assert "FIXTURE-" not in encoded
    assert "fixture-owner" not in encoded


def test_apply_appends_one_correction_per_fund_and_is_exactly_idempotent(
    tmp_path,
) -> None:
    path = tmp_path / "repair-apply.db"
    _fixture_database(path)
    calls: list[list[dict[str, object]]] = []
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer(calls),
    )
    preview = service.preview()
    originals_before = [
        row for row in _rows(path) if row["source"] in {"manual", "portfolio_trade"}
    ]

    result = service.apply(_command(preview))

    assert result.status == "applied"
    assert result.correction_count == 3
    assert result.pair_count == 9
    assert len(calls) == 1 and len(calls[0]) == 3
    rows = _rows(path)
    assert [
        row for row in rows if row["source"] in {"manual", "portfolio_trade"}
    ] == originals_before
    corrections = [
        row
        for row in rows
        if row["source"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    assert len(corrections) == 3
    assert {row["entry_type"] for row in corrections} == {
        LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
    }
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(rows)
    assert resolution.valid
    assert len(resolution.excluded_manual_entry_ids) == 9

    counts_after = _counts(path)
    replay = service.apply(_command(preview))
    assert replay.status == "already_applied"
    assert replay.replayed is True
    assert _counts(path) == counts_after
    with pytest.raises(
        LegacyFundTradeDuplicateRepairBlocked,
        match="existing_correction",
    ):
        service.apply(_command(preview, command_id="another-command"))
    assert _counts(path) == counts_after


@pytest.mark.parametrize("group_sizes", ((1, 1), (5, 2, 2)))
def test_apply_orders_live_shaped_plus08_rows_by_instant(
    tmp_path,
    group_sizes: tuple[int, ...],
) -> None:
    path = tmp_path / "repair-live-offset.db"
    _fixture_database(
        path,
        group_sizes=group_sizes,
        live_offset_shape=True,
        high_precision=True,
    )
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()

    assert preview["status"] == "ready"
    result = service.apply(_command(preview))
    assert result.status == "applied"
    rows = _rows(path)
    assert resolve_legacy_fund_trade_duplicate_exclusions(rows).valid
    payloads = [
        json.loads(str(row["correction_payload_json"]))
        for row in sorted(rows, key=lambda item: int(item["id"]))
        if row["source"] == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    assert all(
        payload["cash_allocation"] == "ordered_batch_absolute_cash_state_v1"
        for payload in payloads
    )
    assert all(
        left["cash_after"] == right["cash_before"]
        for left, right in zip(payloads, payloads[1:], strict=False)
    )


def test_default_writer_publishes_valuation_in_same_database(tmp_path) -> None:
    path = tmp_path / "repair-default-writer.db"
    _fixture_database(path, group_sizes=(1,), live_offset_shape=True)
    service = LegacyFundTradeDuplicateRepairService(path, now=lambda: NOW)
    preview = service.preview()

    result = service.apply(_command(preview))

    assert result.status == "applied"
    assert result.valuation_snapshot_id
    with sqlite3.connect(path) as conn:
        persisted = conn.execute(
            "SELECT status FROM valuation_snapshots WHERE snapshot_id = ?",
            (result.valuation_snapshot_id,),
        ).fetchone()
    assert persisted is not None


def test_apply_requires_exact_confirmation_and_current_preview(tmp_path) -> None:
    path = tmp_path / "repair-confirmation.db"
    _fixture_database(path)
    service = LegacyFundTradeDuplicateRepairService(
        path,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    before = _counts(path)
    bad = LegacyFundTradeDuplicateRepairCommand(
        command_id="repair-1",
        operator_id="fixture-owner",
        preview_fingerprint=str(preview["preview_fingerprint"]),
        confirmation="yes",
    )
    with pytest.raises(ValueError, match="exact repair confirmation"):
        service.apply(bad)
    assert _counts(path) == before

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ledger_entries SET amount = amount + 0.000000001 "
            "WHERE source = 'manual' AND id = ("
            "SELECT min(id) FROM ledger_entries WHERE source = 'manual')"
        )
        conn.commit()
    with pytest.raises(
        LegacyFundTradeDuplicateRepairBlocked,
        match="economic_pair_drifted",
    ):
        service.apply(_command(preview))


def test_stock_pairs_and_ambiguous_pairs_fail_closed(tmp_path) -> None:
    stock_path = tmp_path / "stock.db"
    _fixture_database(stock_path, group_sizes=(1,), asset_class="stock")
    stock = LegacyFundTradeDuplicateRepairService(stock_path).preview()
    assert stock["status"] == "blocked"
    assert "legacy_fund_trade_duplicate_stock_pair_detected" in stock["blockers"]

    ambiguous_path = tmp_path / "ambiguous.db"
    _fixture_database(ambiguous_path, group_sizes=(1,))
    with sqlite3.connect(ambiguous_path) as conn:
        row = conn.execute(
            "SELECT * FROM ledger_entries WHERE source = 'manual' LIMIT 1"
        ).fetchone()
        columns = [
            item[1] for item in conn.execute("PRAGMA table_info(ledger_entries)")
        ]
        values = dict(zip(columns, row, strict=True))
        values.pop("id")
        names = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO ledger_entries ({names}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        conn.commit()
    ambiguous = LegacyFundTradeDuplicateRepairService(ambiguous_path).preview()
    assert ambiguous["status"] == "blocked"
    assert "legacy_fund_trade_duplicate_pair_ambiguous" in ambiguous["blockers"]


def test_group_fingerprint_rejects_canonical_id_reuse(tmp_path) -> None:
    path = tmp_path / "canonical-reuse.db"
    _fixture_database(path, group_sizes=(2,))
    rows = _rows(path)
    manual_ids = [int(row["id"]) for row in rows if row["source"] == "manual"]
    canonical_id = next(
        int(row["id"]) for row in rows if row["source"] == "portfolio_trade"
    )

    with pytest.raises(
        LegacyFundTradeDuplicateCorrectionError,
        match="canonical_scope_overlapped",
    ):
        legacy_fund_trade_duplicate_group_fingerprint(
            ledger_rows=rows,
            pair_entry_ids=(
                (manual_ids[0], canonical_id),
                (manual_ids[1], canonical_id),
            ),
        )


def test_failure_after_first_append_rolls_back_entire_batch(tmp_path) -> None:
    path = tmp_path / "repair-rollback.db"
    _fixture_database(path)
    before = _counts(path)
    calls: list[list[dict[str, object]]] = []

    def fail(stage: str) -> None:
        if stage == "after_correction_entry_1":
            raise RuntimeError("injected")

    service = LegacyFundTradeDuplicateRepairService(
        path,
        valuation_transaction_writer=_writer(calls),
        failure_injector=fail,
    )
    preview = service.preview()
    with pytest.raises(RuntimeError, match="injected"):
        service.apply(_command(preview))
    assert _counts(path) == before
    assert calls == []


def test_resolver_uses_repair_cutoff_and_rejects_pre_cutoff_tampering(
    tmp_path,
) -> None:
    path = tmp_path / "repair-cutoff.db"
    _fixture_database(path, group_sizes=(2,))
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    service.apply(_command(preview))

    # A normal later fact is outside the repair-time cutoff and must not revoke
    # the already-validated historical repair.
    with sqlite3.connect(path) as conn:
        insert_ledger_entry_on_connection(
            conn,
            entry_type="cash_deposit",
            timestamp="2026-09-01T09:00:00+08:00",
            amount=100.0,
            asset_class="cash",
            source="manual",
            source_ref="later-cash",
            created_at="2026-09-01T09:00:00+08:00",
        )
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-09-02T09:00:00+08:00",
            amount=3.0,
            symbol="LATER-STOCK",
            direction="buy",
            quantity=1.0,
            price=3.0,
            commission=0.0,
            gross_amount=3.0,
            net_cash_impact=-3.0,
            asset_class="stock",
            source="manual",
            source_ref="later-stock",
            created_at="2026-09-02T09:00:00+08:00",
        )
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-09-03T09:00:00+08:00",
            amount=4.0,
            symbol="FIXTURE-1",
            direction="buy",
            quantity=1.0,
            price=4.0,
            commission=0.0,
            gross_amount=4.0,
            net_cash_impact=-4.0,
            asset_class="fund",
            source="manual",
            source_ref="later-fund",
            created_at="2026-09-03T09:00:00+08:00",
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert resolution.valid
    assert len(resolution.excluded_manual_entry_ids) == 2
    build_portfolio_projection([LedgerEntry.from_row(row) for row in _rows(path)])

    # A post-cutoff row backfilled before the correction remains outside the
    # historical fingerprint, but protected projection replay rejects its
    # changed position-before state.
    with sqlite3.connect(path) as conn:
        insert_ledger_entry_on_connection(
            conn,
            entry_type="trade_buy",
            timestamp="2026-04-08T06:00:00+00:00",
            amount=1.0,
            symbol="FIXTURE-1",
            direction="buy",
            quantity=1.0,
            price=1.0,
            commission=0.0,
            gross_amount=1.0,
            net_cash_impact=-1.0,
            asset_class="fund",
            source="manual",
            source_ref="backfilled-fund",
            created_at="2026-09-04T09:00:00+08:00",
        )
        conn.commit()
    assert resolve_legacy_fund_trade_duplicate_exclusions(_rows(path)).valid
    with pytest.raises(ValueError, match="position evidence drifted"):
        build_portfolio_projection([LedgerEntry.from_row(row) for row in _rows(path)])

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ledger_entries SET note = 'tampered' "
            "WHERE id = (SELECT min(id) FROM ledger_entries)"
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert not resolution.valid
    assert not resolution.excluded_manual_entry_ids


def test_resolver_rejects_tampered_fingerprint_and_returns_no_exclusions(
    tmp_path,
) -> None:
    path = tmp_path / "repair-tamper.db"
    _fixture_database(path, group_sizes=(1,))
    service = LegacyFundTradeDuplicateRepairService(
        path,
        now=lambda: NOW,
        valuation_transaction_writer=_writer([]),
    )
    preview = service.preview()
    service.apply(_command(preview))
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT id, correction_payload_json FROM ledger_entries "
            "WHERE source = ?",
            (LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,),
        ).fetchone()
        payload = json.loads(row[1])
        payload["repair_fingerprint"] = "a" * 64
        conn.execute(
            "UPDATE ledger_entries SET correction_payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )
        conn.commit()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(_rows(path))
    assert not resolution.valid
    assert not resolution.excluded_manual_entry_ids


def test_cli_defaults_to_read_only_preview(tmp_path) -> None:
    path = tmp_path / "repair-cli.db"
    _fixture_database(path, group_sizes=(2,))
    before = _counts(path)
    output = io.StringIO()

    code = repair_cli.main(
        ["--database", str(path)],
        stdout=output,
    )

    report = json.loads(output.getvalue())
    assert code == 0
    assert report["status"] == "ready"
    assert report["database_writes_performed"] is False
    assert _counts(path) == before
