"""Read-only SQLite facts used to verify frozen candidate price outcomes."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from data.market_daily_store import verify_market_daily_receipt_on_connection
from data.meta_store_connection import connect_meta_sqlite


class CandidateOutcomeStoreUnavailable(Exception):
    """A persisted fact could not be read without losing verification."""


@contextmanager
def read_candidate_outcome_receipts(
    market_path: Path,
) -> Iterator[CandidateOutcomeReceiptReader]:
    """Hold one read transaction across receipt and bar verification."""
    try:
        with closing(connect_meta_sqlite(market_path, readonly=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            yield CandidateOutcomeReceiptReader(conn)
    except (OSError, sqlite3.Error) as exc:
        raise CandidateOutcomeStoreUnavailable from exc


def read_research_candidate_payloads(
    app_path: Path, *, run_id: str, candidate_id: str
) -> tuple[str, str] | None:
    """Read the exact candidate comparison and backtest payload as stored."""
    try:
        with closing(
            sqlite3.connect(app_path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as conn:
            row = conn.execute(
                """SELECT c.comparison_json, r.metrics_json
                   FROM ai_shadow_research_candidates AS c
                   JOIN backtest_results AS r ON r.id = c.candidate_result_id
                   WHERE c.run_id = ? AND c.candidate_id = ?""",
                (run_id, candidate_id),
            ).fetchone()
    except (OSError, sqlite3.Error) as exc:
        raise CandidateOutcomeStoreUnavailable from exc
    return (str(row[0]), str(row[1])) if row is not None else None


def replay_research_dataset_snapshot(
    snapshot: dict[str, Any], *, market_root: Path
) -> dict[str, Any]:
    """Translate storage read errors from the existing dataset verifier."""
    try:
        return verify_backtest_dataset_snapshot_replay(snapshot, store_root=market_root)
    except sqlite3.Error as exc:
        raise CandidateOutcomeStoreUnavailable from exc


class CandidateOutcomeReceiptReader:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._receipts: dict[
            tuple[str, str], tuple[dict[str, Any] | None, str | None]
        ] = {}
        self._bars: dict[
            tuple[str, str, str], tuple[dict[str, Any] | None, str | None]
        ] = {}

    def anchor(
        self,
        day: date,
        *,
        symbol: str,
        allowed_fingerprints: set[str],
    ) -> tuple[dict[str, Any] | None, str | None]:
        rows = self._conn.execute(
            """SELECT provider_name, receipt_json FROM market_daily_ingestion_receipts
               WHERE trade_date = ?""",
            (day.isoformat(),),
        ).fetchall()
        matches = []
        for row in rows:
            try:
                receipt = json.loads(str(row["receipt_json"]))
            except (TypeError, ValueError):
                continue
            if (
                isinstance(receipt, dict)
                and receipt.get("receipt_fingerprint") in allowed_fingerprints
            ):
                matches.append(str(row["provider_name"]))
        if len(matches) != 1:
            return None, "anchor_receipt_missing_or_ambiguous"
        return self.bar(day, symbol=symbol, provider=matches[0])

    def bar(
        self, day: date, *, symbol: str, provider: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        key = (day.isoformat(), provider, symbol)
        if key in self._bars:
            return self._bars[key]
        receipt, reason = self._receipt(day, provider)
        if receipt is None:
            result = (None, reason)
        elif symbol not in receipt["symbols"]:
            result = (None, "symbol_absent_from_verified_receipt")
        else:
            table = (
                "market_bars"
                if receipt["schema_version"]
                == "karkinos.market_daily_ingestion_receipt.v1"
                else "market_bars_v2"
            )
            stock_filter = (
                "" if table == "market_bars" else "instrument_type='stock' AND"
            )
            rows = self._conn.execute(
                f"""SELECT open, close, volume FROM {table}
                   WHERE {stock_filter} symbol=? AND frequency='1d'
                   AND substr(timestamp,1,10)=?""",
                (symbol, day.isoformat()),
            ).fetchall()
            if len(rows) != 1:
                result = (None, "symbol_bar_missing_or_ambiguous")
            elif _positive_decimal(rows[0]["volume"]) is None:
                result = (None, "symbol_session_not_traded")
            else:
                result = (
                    {
                        "session_date": day.isoformat(),
                        "symbol": symbol,
                        "provider": provider,
                        "open": str(rows[0]["open"]),
                        "close": str(rows[0]["close"]),
                        "receipt_fingerprint": receipt["receipt_fingerprint"],
                        "ingested_at_local": receipt["ingested_at_local"],
                        "available_at": None,
                        "available_at_verified": False,
                    },
                    None,
                )
        self._bars[key] = result
        return result

    def _receipt(
        self, day: date, provider: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        key = (day.isoformat(), provider)
        if key in self._receipts:
            return self._receipts[key]
        row = self._conn.execute(
            """SELECT receipt_json, created_at
               FROM market_daily_ingestion_receipts
               WHERE trade_date=? AND provider_name=?""",
            key,
        ).fetchone()
        if row is None:
            result = (None, "horizon_receipt_missing")
        else:
            try:
                receipt = json.loads(str(row["receipt_json"]))
                valid = (
                    isinstance(receipt, dict)
                    and receipt.get("provider_name") == provider
                    and receipt.get("trade_date") == day.isoformat()
                    and verify_market_daily_receipt_on_connection(self._conn, receipt)
                )
            except (KeyError, TypeError, ValueError, sqlite3.Error):
                valid = False
            if not valid:
                result = (None, "daily_receipt_unverified")
            elif receipt.get("schema_version") in {
                "karkinos.market_daily_ingestion_receipt.v1",
                "karkinos.market_daily_ingestion_receipt.v2",
            }:
                result = (None, "historical_price_basis_unverified")
            elif (
                receipt.get("schema_version")
                != "karkinos.market_daily_ingestion_receipt.v3"
                or receipt.get("price_basis") != "unadjusted"
            ):
                result = (None, "daily_receipt_unverified")
            else:
                result = (
                    {
                        **receipt,
                        "ingested_at_local": str(row["created_at"]),
                    },
                    None,
                )
        self._receipts[key] = result
        return result


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None
