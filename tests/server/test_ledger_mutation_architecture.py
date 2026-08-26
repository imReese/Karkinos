"""Static ownership guards for canonical ledger mutation boundaries."""

from __future__ import annotations

import inspect

from server.contracts.http.ledger_models import (
    LedgerAdjustmentCreate,
    LedgerCashFlowCreate,
    LedgerDividendCreate,
    LedgerTradeCreate,
    LedgerTradeSettlementCreate,
)
from server.ledger import repository as ledger_repository
from server.persistence import financial_facts_ledger, ledger_mutation_uow
from server.routes import ledger as ledger_routes


def test_ledger_routes_only_call_typed_repository_commands() -> None:
    source = inspect.getsource(ledger_routes)

    assert ".append_entry(" in source
    assert ".settle_trade(" in source
    assert ".insert_entry(" not in source
    assert "confirm_ledger_trade_settlement_sync" not in source


def test_legacy_ledger_helpers_delegate_without_post_commit_publication() -> None:
    source = inspect.getsource(financial_facts_ledger)

    assert "LedgerAppendCommand(" in source
    assert "LedgerTradeSettlementCommand(" in source
    assert "_ledger_mutation_uow().append(command)" in source
    assert "_valuation_publisher" not in source
    assert "logger.exception" not in source


def test_ledger_uow_owns_lock_full_candidate_set_and_commit() -> None:
    source = inspect.getsource(ledger_mutation_uow)

    assert source.count('conn.execute("BEGIN IMMEDIATE")') == 2
    assert source.count("candidate_ledger_rows=_load_all_ledger_entries(conn)") == 2
    assert (
        "except Exception:\n                conn.rollback()\n                raise"
        in source
    )


def test_ledger_http_mutations_require_operator_and_request_identity() -> None:
    for model in (
        LedgerTradeCreate,
        LedgerTradeSettlementCreate,
        LedgerCashFlowCreate,
        LedgerDividendCreate,
        LedgerAdjustmentCreate,
    ):
        assert model.model_fields["operator_id"].is_required()
        assert model.model_fields["request_id"].is_required()

    assert LedgerTradeSettlementCreate.model_fields[
        "expected_entry_fingerprint"
    ].is_required()


def test_ledger_repository_legacy_adapters_delegate_to_atomic_database_uow() -> None:
    source = inspect.getsource(ledger_repository.LedgerRepository)

    assert "self._db.insert_ledger_entry_sync(" in source
    assert "self._db.confirm_ledger_trade_settlement_sync(" in source
    assert "sqlite3" not in source
    assert "commit(" not in source
