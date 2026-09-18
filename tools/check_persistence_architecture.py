"""Fail CI when authoritative persistence bypasses shared SQLite policy."""

from __future__ import annotations

import sys
from pathlib import Path

PERSISTENCE = Path("server/persistence")

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


def raw_connection_offenders(root: Path = PERSISTENCE) -> tuple[str, ...]:
    protected = {root / name for name in CRITICAL_REPOSITORIES}
    protected.update(root.glob("*_uow.py"))
    return tuple(
        path.as_posix()
        for path in sorted(protected)
        if path.is_file() and "sqlite3.connect(" in path.read_text(encoding="utf-8")
    )


def main() -> int:
    offenders = raw_connection_offenders()
    if not offenders:
        print("Persistence connection boundaries passed.")
        return 0
    for path in offenders:
        print(f"{path}: authoritative writes must use connect_sqlite()")
    return 1


if __name__ == "__main__":
    sys.exit(main())
