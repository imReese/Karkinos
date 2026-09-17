"""Architecture guard for authoritative SQLite transaction owners."""

from __future__ import annotations

from pathlib import Path

PERSISTENCE = Path(__file__).resolve().parents[2] / "server" / "persistence"

CRITICAL_REPOSITORIES = (
    "financial_facts_ledger.py",
    "execution_reconciliation.py",
    "controlled_session_authority_queries.py",
    "controlled_ledger_queries.py",
    "controlled_broker_cancellations.py",
    "controlled_broker_intents.py",
    "controlled_broker_write_releases.py",
    "controlled_session_budgets.py",
    "controlled_session_gate_snapshots.py",
    "event_log.py",
    "financial_facts_portfolio.py",
    "financial_facts_quote_runs.py",
    "financial_facts_quotes.py",
    "financial_facts_valuation.py",
    "jobs.py",
    "oms.py",
    "paper_trading.py",
    "runtime_controls.py",
    "signal_journal.py",
)


def test_uow_modules_never_open_raw_sqlite_connections() -> None:
    offenders = [
        path.name
        for path in sorted(PERSISTENCE.glob("*_uow.py"))
        if "sqlite3.connect(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_critical_financial_repositories_use_shared_connection_policy() -> None:
    offenders = [
        name
        for name in CRITICAL_REPOSITORIES
        if "sqlite3.connect(" in (PERSISTENCE / name).read_text(encoding="utf-8")
    ]
    assert offenders == []
