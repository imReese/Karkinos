"""SQLite repository for persisted backtest results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

V25_BACKTEST_INVALIDATIONS = (
    """CREATE TABLE backtest_result_invalidations (
        result_id INTEGER PRIMARY KEY REFERENCES backtest_results(id),
        row_fingerprint TEXT NOT NULL,
        actor TEXT NOT NULL CHECK(length(trim(actor)) > 0),
        reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
        idempotency_key TEXT NOT NULL UNIQUE CHECK(length(trim(idempotency_key)) > 0),
        created_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER backtest_result_invalidations_no_update
        BEFORE UPDATE ON backtest_result_invalidations
        BEGIN SELECT RAISE(ABORT, 'backtest invalidations are immutable'); END""",
    """CREATE TRIGGER backtest_result_invalidations_no_delete
        BEFORE DELETE ON backtest_result_invalidations
        BEGIN SELECT RAISE(ABORT, 'backtest invalidations are immutable'); END""",
    """CREATE TRIGGER backtest_result_invalidations_no_replace
        BEFORE INSERT ON backtest_result_invalidations
        WHEN EXISTS (SELECT 1 FROM backtest_result_invalidations
          WHERE result_id=NEW.result_id OR idempotency_key=NEW.idempotency_key)
        BEGIN SELECT RAISE(ABORT, 'backtest invalidations are immutable'); END""",
)
V25_SCHEMA_OBJECTS = (
    ("table", "backtest_result_invalidations"),
    ("trigger", "backtest_result_invalidations_no_update"),
    ("trigger", "backtest_result_invalidations_no_delete"),
    ("trigger", "backtest_result_invalidations_no_replace"),
)


def backtest_row_fingerprint(row: Mapping[str, Any]) -> str:
    """Identify exact saved columns, retaining original JSON strings as stored."""
    raw = {key: value for key, value in row.items() if key != "evidence_invalidation"}
    encoded = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def backtest_invalidation_for_result(
    conn: sqlite3.Connection, result_id: int
) -> dict[str, Any] | None:
    """Read validity without creating schema or changing the original result."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='backtest_result_invalidations'"
    ).fetchone()
    if exists is None:
        return {"status": "unavailable", "result_id": result_id}
    cursor = conn.execute(
        "SELECT * FROM backtest_result_invalidations WHERE result_id=?",
        (result_id,),
    )
    found = cursor.fetchone()
    if found is None:
        return None
    assert cursor.description is not None
    fact = dict(zip((col[0] for col in cursor.description), found, strict=True))
    source = conn.execute("SELECT * FROM backtest_results WHERE id=?", (result_id,))
    saved = source.fetchone()
    assert source.description is not None
    current = (
        backtest_row_fingerprint(
            dict(zip((col[0] for col in source.description), saved, strict=True))
        )
        if saved is not None
        else None
    )
    return {
        **fact,
        "status": (
            "invalidated"
            if current == fact["row_fingerprint"]
            else "fingerprint_mismatch"
        ),
        "current_row_fingerprint": current,
    }


def with_backtest_invalidation(
    conn: sqlite3.Connection, row: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **row,
        "evidence_invalidation": backtest_invalidation_for_result(conn, int(row["id"])),
    }


def backtest_evidence_blocker(row: Mapping[str, Any]) -> str | None:
    fact = row.get("evidence_invalidation")
    if fact is None:
        return None
    status = fact.get("status") if isinstance(fact, Mapping) else "unavailable"
    return "backtest_evidence_" + str(status or "unavailable")


class BacktestResultsRepository:
    """Own backtest result persistence without running backtests."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def append_invalidation_sync(
        self,
        *,
        result_id: int,
        expected_row_fingerprint: str,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Withdraw one exact saved result; keep its original financial row intact."""
        if type(result_id) is not int or result_id <= 0:
            raise ValueError("invalid backtest result ID")
        actor, reason, idempotency_key = (
            str(value).strip() for value in (actor, reason, idempotency_key)
        )
        if not all((actor, reason, idempotency_key)):
            raise ValueError("invalidation actor, reason and idempotency key required")
        from server.persistence.connection import connect_sqlite

        with closing(connect_sqlite(self._database_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT * FROM backtest_result_invalidations "
                "WHERE idempotency_key=? OR result_id=?",
                (idempotency_key, result_id),
            ).fetchall()
            expected = {
                "result_id": result_id,
                "row_fingerprint": expected_row_fingerprint,
                "actor": actor,
                "reason": reason,
                "idempotency_key": idempotency_key,
            }
            if previous:
                if len(previous) != 1 or any(
                    previous[0][key] != value for key, value in expected.items()
                ):
                    raise ValueError("backtest invalidation idempotency conflict")
                return dict(previous[0])
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id=?", (result_id,)
            ).fetchone()
            if (
                row is None
                or backtest_row_fingerprint(dict(row)) != expected_row_fingerprint
            ):
                raise ValueError("backtest invalidation source fingerprint changed")
            fact = {**expected, "created_at": datetime.now(timezone.utc).isoformat()}
            conn.execute(
                """INSERT INTO backtest_result_invalidations
                   (result_id,row_fingerprint,actor,reason,idempotency_key,created_at)
                   VALUES (:result_id,:row_fingerprint,:actor,:reason,:idempotency_key,:created_at)""",
                fact,
            )
            return fact

    async def save(
        self,
        config_json: str,
        initial_cash: float,
        final_equity: float,
        total_return: float,
        sharpe: float,
        max_dd: float,
        equity_curve_json: str,
        annual_return: float = 0.0,
        sortino: float = 0.0,
        win_rate: float = 0.0,
        duration_days: int = 0,
        metrics_json: str = "{}",
        cost_summary_json: str = "{}",
    ) -> int:
        with sqlite3.connect(self._database_path) as conn:
            result_id = insert_backtest_result(
                conn,
                created_at=datetime.now().isoformat(),
                config_json=config_json,
                initial_cash=initial_cash,
                final_equity=final_equity,
                total_return=total_return,
                sharpe=sharpe,
                max_dd=max_dd,
                equity_curve_json=equity_curve_json,
                annual_return=annual_return,
                sortino=sortino,
                win_rate=win_rate,
                duration_days=duration_days,
                metrics_json=metrics_json,
                cost_summary_json=cost_summary_json,
            )
            conn.commit()
            return result_id

    async def list_results(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""SELECT id, created_at, config_json, initial_cash,
                          final_equity, total_return, sharpe, max_drawdown,
                          equity_curve_json, metrics_json, cost_summary_json
                   FROM backtest_results ORDER BY id DESC""").fetchall()
            return [with_backtest_invalidation(conn, dict(row)) for row in rows]

    async def get_result(self, result_id: int) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
            ).fetchone()
            return with_backtest_invalidation(conn, dict(row)) if row else None

    def read_recent_historical_comparison_anchors(
        self, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Discover explicit persisted comparison anchors without selecting a winner."""
        from server.persistence.connection import connect_sqlite

        if type(limit) is not int or limit <= 0:
            return []
        with closing(connect_sqlite(self._database_path, readonly=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, json_extract(metrics_json,
                          '$.formula_binding.formula_ast') AS formula_ast_json
                   FROM backtest_results
                   WHERE CASE WHEN json_valid(metrics_json) THEN
                     json_extract(metrics_json, '$.historical_comparison.role')
                       = 'candidate2'
                     AND json_type(metrics_json,
                       '$.historical_comparison.historical_formula_source_result_id')
                       = 'integer'
                     AND json_extract(metrics_json,
                       '$.historical_comparison.historical_formula_source_result_id') > 0
                     AND json_type(metrics_json,
                       '$.historical_comparison.actual_comparison_baseline_result_id')
                       = 'integer'
                     AND json_extract(metrics_json,
                       '$.historical_comparison.actual_comparison_baseline_result_id') > 0
                   ELSE 0 END
                   ORDER BY id DESC LIMIT ?""",
                (min(limit, 20),),
            ).fetchall()
            return [with_backtest_invalidation(conn, dict(row)) for row in rows]

    def read_historical_comparison_rows(
        self, source_result_id: int
    ) -> list[dict[str, Any]]:
        """Read an exact source or comparison anchor and its source family."""
        from server.persistence.connection import connect_sqlite

        if type(source_result_id) is not int or source_result_id <= 0:
            return []
        with closing(connect_sqlite(self._database_path, readonly=True)) as conn:
            conn.row_factory = sqlite3.Row
            anchor = conn.execute(
                """SELECT CASE WHEN json_valid(metrics_json) THEN
                       CASE WHEN json_type(metrics_json,
                         '$.historical_comparison.historical_formula_source_result_id')
                         = 'integer' AND json_extract(metrics_json,
                         '$.historical_comparison.historical_formula_source_result_id') > 0
                       THEN json_extract(metrics_json,
                         '$.historical_comparison.historical_formula_source_result_id')
                       END END AS source_id
                   FROM backtest_results WHERE id = ?""",
                (source_result_id,),
            ).fetchone()
            if anchor is None:
                return []
            family_id = anchor["source_id"]
            if type(family_id) is not int or family_id <= 0:
                family_id = source_result_id
            rows = conn.execute(
                """SELECT id, config_json, metrics_json, total_return,
                          sharpe, max_drawdown FROM backtest_results
                   WHERE id IN (?, ?) OR CASE WHEN json_valid(metrics_json) THEN
                     json_extract(metrics_json,
                       '$.historical_comparison.historical_formula_source_result_id')
                   END = ?
                   ORDER BY id DESC""",
                (source_result_id, family_id, family_id),
            ).fetchall()
            return [with_backtest_invalidation(conn, dict(row)) for row in rows]


def insert_backtest_result(
    conn: sqlite3.Connection,
    *,
    created_at: str,
    config_json: str,
    initial_cash: float,
    final_equity: float,
    total_return: float,
    sharpe: float,
    max_dd: float,
    equity_curve_json: str,
    annual_return: float = 0.0,
    sortino: float = 0.0,
    win_rate: float = 0.0,
    duration_days: int = 0,
    metrics_json: str = "{}",
    cost_summary_json: str = "{}",
) -> int:
    """Insert one canonical backtest row on the caller-owned transaction."""

    cursor = conn.execute(
        """INSERT INTO backtest_results
           (created_at, config_json, initial_cash, final_equity, total_return,
            sharpe, sortino, max_drawdown, win_rate, duration_days,
            equity_curve_json, metrics_json, cost_summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            created_at,
            config_json,
            initial_cash,
            final_equity,
            total_return,
            sharpe,
            sortino,
            max_dd,
            win_rate,
            duration_days,
            equity_curve_json,
            metrics_json,
            cost_summary_json,
        ),
    )
    return int(cursor.lastrowid or 0)


def resolve_etf_backtest_record(
    database_path: str | Path,
    *,
    bound_result_id: int | None = None,
    expected_symbols: Sequence[str] | set[str] | None = None,
    expected_params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve the target ETF rotation backtest row and its forward paper book summary."""
    import json
    from contextlib import closing
    from datetime import timezone
    from decimal import Decimal

    from server.persistence.connection import connect_sqlite
    from server.persistence.research_paper_books import ResearchPaperBooksRepository

    resolved_path = Path(database_path)
    if not resolved_path.exists():
        return None, None

    core_symbols = (
        set(expected_symbols)
        if expected_symbols is not None
        else {
            "510300",
            "510500",
            "159915",
            "513100",
            "513500",
            "512890",
            "518880",
            "511010",
        }
    )

    def _matches_plan(cfg: dict[str, Any]) -> bool:
        strategy_name = cfg.get("strategy") or cfg.get("strategy_kind")
        if strategy_name != "etf_rotation":
            return False

        extracted_symbols: set[str] = set()
        if isinstance(cfg.get("assets"), list):
            for item in cfg["assets"]:
                if isinstance(item, dict) and item.get("symbol"):
                    extracted_symbols.add(str(item["symbol"]))
                elif isinstance(item, str):
                    extracted_symbols.add(item)
        if isinstance(cfg.get("symbols"), list):
            for s in cfg["symbols"]:
                extracted_symbols.add(str(s))
        params = cfg.get("params")
        if isinstance(params, dict) and isinstance(params.get("symbols"), list):
            for s in params["symbols"]:
                extracted_symbols.add(str(s))

        # If symbols are explicitly declared, they must match the plan universe
        if extracted_symbols and extracted_symbols != core_symbols:
            return False

        params_val = cfg.get("params")
        cfg_params: dict[str, Any] = params_val if isinstance(params_val, dict) else cfg
        if expected_params:
            for k in (
                "top_k",
                "lookback_period",
                "volatility_window",
                "rebalance_interval",
            ):
                if k in expected_params and k in cfg_params:
                    if str(expected_params[k]) != str(cfg_params[k]):
                        return False
        return True

    try:
        with closing(connect_sqlite(resolved_path, readonly=True)) as conn:
            conn.row_factory = sqlite3.Row
            has_bt_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_results'"
            ).fetchone()
            if not has_bt_table:
                return None, None

            target_row = None
            if bound_result_id is not None:
                row = conn.execute(
                    "SELECT * FROM backtest_results WHERE id = ?",
                    (bound_result_id,),
                ).fetchone()
                if row:
                    candidate = dict(row)
                    cfg = (
                        json.loads(candidate["config_json"])
                        if candidate.get("config_json")
                        else {}
                    )
                    if _matches_plan(cfg):
                        target_row = candidate
            else:
                rows = conn.execute(
                    "SELECT * FROM backtest_results ORDER BY id DESC"
                ).fetchall()
                for r in rows:
                    try:
                        cfg = json.loads(r["config_json"]) if r["config_json"] else {}
                        if not _matches_plan(cfg):
                            continue
                        # Skip unexecuted seed placeholders
                        curve = (
                            r["equity_curve_json"]
                            if "equity_curve_json" in r.keys()
                            else ""
                        )
                        duration = (
                            int(r["duration_days"] or 0)
                            if "duration_days" in r.keys()
                            else 0
                        )
                        tot_ret = (
                            float(r["total_return"] or 0.0)
                            if "total_return" in r.keys()
                            else 0.0
                        )
                        if (
                            curve in ("[]", "", None)
                            and duration == 0
                            and tot_ret == 0.0
                        ):
                            continue
                        target_row = dict(r)
                        break
                    except Exception:
                        continue

            if target_row is None:
                return None, None

            result_id = int(target_row["id"])
            paper_book_summary: dict[str, Any] | None = None

            has_obs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_observations'"
            ).fetchone()
            has_paper = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_paper_books'"
            ).fetchone()

            if has_obs and has_paper:
                obs_row = conn.execute(
                    """
                    SELECT o.id AS id
                    FROM research_observations o
                    JOIN research_paper_books p ON p.observation_id = o.id
                    WHERE o.source_backtest_result_id = ?
                    ORDER BY COALESCE(p.started_at, o.started_at, '') DESC
                    LIMIT 1
                    """,
                    (result_id,),
                ).fetchone()
                if obs_row:
                    obs_id = obs_row["id"]
                    paper_repo = ResearchPaperBooksRepository(
                        resolved_path,
                        clock=lambda: datetime.now(timezone.utc),
                    )
                    paper_detail = paper_repo.get(obs_id)
                    if paper_detail:
                        perf = paper_detail.get("performance", {})
                        health = paper_detail.get("health", {})
                        net_ret = Decimal(str(perf.get("net_return", "0")))
                        mdd_paper = Decimal(str(perf.get("max_drawdown", "0")))
                        paper_book_summary = {
                            "book_id": paper_detail["id"],
                            "observation_id": obs_id,
                            "settled_sessions": perf.get("settled_sessions", 0),
                            "equity": perf.get(
                                "equity",
                                str(paper_detail.get("initial_cash", "0")),
                            ),
                            "net_return": perf.get("net_return", "0"),
                            "net_return_pct": round(float(net_ret) * 100, 2),
                            "max_drawdown": perf.get("max_drawdown", "0"),
                            "max_drawdown_pct": round(float(mdd_paper) * 100, 2),
                            "fees_paid": perf.get("fees_paid", "0"),
                            "slippage_cost": perf.get("slippage_cost", "0"),
                            "health_status": health.get("status", "not_configured"),
                            "through_session": perf.get("through_session"),
                            "evaluation_start": paper_detail.get("evaluation_start"),
                        }

            return target_row, paper_book_summary
    except Exception:
        return None, None
