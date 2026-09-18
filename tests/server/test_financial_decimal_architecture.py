from __future__ import annotations

import re
from pathlib import Path

PERSISTENCE = Path(__file__).resolve().parents[2] / "server/persistence"
AUTHORITATIVE_TABLES = (
    "ledger_entries",
    "cash_flows",
    "trades",
    "pending_fund_orders",
    "orders",
    "manual_orders",
    "oms_orders",
    "fills",
    "portfolio_snapshots",
)
EXEMPT_HISTORY_MODULES = {
    "migrations.py",
    "migration_registry.py",
    "financial_decimal_migrations.py",
}


def _inserts(source: str, table: str) -> bool:
    return re.search(rf"INSERT\s+INTO\s+{table}\b", source, re.IGNORECASE) is not None


def test_authoritative_financial_inserts_use_exact_decimal_storage() -> None:
    offenders: list[str] = []
    for path in sorted(PERSISTENCE.glob("*.py")):
        if path.name in EXEMPT_HISTORY_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        touched = [table for table in AUTHORITATIVE_TABLES if _inserts(source, table)]
        if touched and "decimal_provenance" not in source:
            offenders.append(f"{path.name}:{','.join(touched)}")
    assert offenders == []


def test_market_and_research_real_values_are_outside_financial_fact_guard() -> None:
    guarded = set(AUTHORITATIVE_TABLES)
    assert "quote_snapshots" not in guarded
    assert "latest_quotes" not in guarded
    assert "signals" not in guarded
    assert "backtest_results" not in guarded
