"""Market Data 的可重建 Serving Projection。

Serving Store 为 UI、查询和日常读取提供快速的 mutable projection：

    immutable MarketRevision
            ↓
    validated materialization
            ↓
       Serving Store

它不是 Market Data truth。

真正的历史事实仍然来自：

    Capture
    → MarketRevision
    → Materialization
    → ObjectStore

Serving Store 可以删除并从 immutable history 重建。

Research / Backtest 不得依赖 Serving Store，而应显式绑定 DatasetRef。
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation
from data.market.revision import (
    MARKET_DATA_KIND_DAILY_BARS,
    MarketRevision,
    MarketRevisionError,
    MarketRevisionMaterialization,
    validate_daily_bar_materialization,
)
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    daily_bars_from_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectStoreError,
)
from data.storage.parquet import (
    ParquetStorageError,
    read_parquet,
)

logger = logging.getLogger(__name__)


_MARKET_SERVING_SCHEMA_VERSION = 1


class MarketServingError(RuntimeError):
    """Serving Store 基础异常。"""


class MarketServingIntegrityError(MarketServingError):
    """Serving Store 或输入 lineage 不可信。"""


class MarketServingConflictError(MarketServingError):
    """无法确定两个同时间候选的覆盖关系。"""


@dataclass(frozen=True, slots=True)
class DailyBarServingApplyResult:
    """一次 Revision 投影结果。"""

    provider: str
    revision_id: str
    materialization_id: str

    inserted_count: int
    updated_count: int
    unchanged_count: int
    stale_skipped_count: int

    @property
    def affected_count(self) -> int:
        return self.inserted_count + self.updated_count


class MarketServingStore:
    """本地可重建 Market Data Serving Projection。"""

    def __init__(
        self,
        root: str | Path,
    ) -> None:
        self._root = Path(root)

        self._path = self._root / "serving" / "market.sqlite3"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    def apply_daily_bar_revision(
        self,
        store: ContentAddressedObjectStore,
        *,
        revision: MarketRevision,
        materialization: MarketRevisionMaterialization,
    ) -> DailyBarServingApplyResult:
        """把一份 validated MarketRevision 投影到 Serving Store。

        覆盖顺序只依据 captured_at：

            newer captured_at
                → replace

            older captured_at
                → ignore

            same captured_at + same lineage
                → idempotent

            same captured_at + different lineage
                → ambiguous / fail closed

        不允许使用 revision hash 大小决定谁更新。
        """
        if not isinstance(
            store,
            ContentAddressedObjectStore,
        ):
            raise TypeError("market_serving_store_invalid")

        if not isinstance(
            revision,
            MarketRevision,
        ):
            raise TypeError("market_serving_revision_invalid")

        if not isinstance(
            materialization,
            MarketRevisionMaterialization,
        ):
            raise TypeError("market_serving_materialization_invalid")

        if revision.kind != MARKET_DATA_KIND_DAILY_BARS:
            raise ValueError("market_serving_revision_kind_unsupported")

        if materialization.revision_ref != revision.ref:
            raise MarketServingIntegrityError(
                "market_serving_materialization_revision_mismatch"
            )

        try:
            validate_daily_bar_materialization(
                store,
                revision=revision,
                materialization=materialization,
            )

            table = read_parquet(
                store,
                materialization.artifact,
                expected_schema=DAILY_BAR_SCHEMA,
            )

            bars = daily_bars_from_table(table)

        except (
            ObjectStoreError,
            ParquetStorageError,
            MarketRevisionError,
        ) as exc:
            raise MarketServingIntegrityError(
                "market_serving_revision_unreadable"
            ) from exc

        self._ensure_schema()

        inserted = 0
        updated = 0
        unchanged = 0
        stale_skipped = 0

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")

            for bar in bars:
                state = _apply_bar(
                    connection,
                    bar=bar,
                    provider=revision.provider,
                    revision_id=(revision.ref.revision_id),
                    materialization_id=(materialization.materialization_id),
                )

                if state == "inserted":
                    inserted += 1
                elif state == "updated":
                    updated += 1
                elif state == "unchanged":
                    unchanged += 1
                elif state == "stale":
                    stale_skipped += 1
                else:
                    raise AssertionError("market_serving_apply_state_unknown")

            connection.commit()

        result = DailyBarServingApplyResult(
            provider=revision.provider,
            revision_id=(revision.ref.revision_id),
            materialization_id=(materialization.materialization_id),
            inserted_count=inserted,
            updated_count=updated,
            unchanged_count=unchanged,
            stale_skipped_count=stale_skipped,
        )

        logger.info(
            "Market Serving 投影完成 "
            "provider=%s revision_id=%s "
            "inserted=%d updated=%d "
            "unchanged=%d stale=%d",
            result.provider,
            result.revision_id,
            result.inserted_count,
            result.updated_count,
            result.unchanged_count,
            result.stale_skipped_count,
        )

        return result

    def read_daily_bars(
        self,
        *,
        provider: str,
        start_date: date,
        end_date: date,
        instruments: (
            tuple[
                InstrumentKey,
                ...,
            ]
            | None
        ) = None,
    ) -> tuple[
        DailyBarObservation,
        ...,
    ]:
        """读取 Serving Projection 中的 canonical 日线数据。

        instruments=None 明确表示读取该 Provider / 日期范围内全部记录。

        返回顺序固定为：

            session_date
            → instrument_type
            → symbol
        """
        provider = _require_non_empty_text(
            provider,
            field="provider",
        )

        start_date = _require_date(
            start_date,
            field="start_date",
        )

        end_date = _require_date(
            end_date,
            field="end_date",
        )

        if start_date > end_date:
            raise ValueError("market_serving_date_range_invalid")

        instruments = (
            None if instruments is None else _canonical_instruments(instruments)
        )

        if not self._path.exists():
            return ()

        self._require_schema()

        clauses = [
            "provider = ?",
            "session_date >= ?",
            "session_date <= ?",
        ]

        parameters: list[object] = [
            provider,
            start_date.isoformat(),
            end_date.isoformat(),
        ]

        if instruments is not None:
            if not instruments:
                return ()

            identity_clauses = []

            for instrument in instruments:
                identity_clauses.append("(instrument_type = ? AND symbol = ?)")

                parameters.extend(
                    (
                        instrument.instrument_type.value,
                        instrument.symbol,
                    )
                )

            clauses.append("(" + " OR ".join(identity_clauses) + ")")

        sql = f"""
            SELECT
                instrument_type,
                symbol,
                session_date,
                event_time,
                available_at,
                captured_at,
                open,
                high,
                low,
                close,
                volume,
                amount,
                suspended
            FROM daily_bar_projection
            WHERE {" AND ".join(clauses)}
            ORDER BY
                session_date ASC,
                instrument_type ASC,
                symbol ASC
        """

        with closing(self._connect(read_only=True)) as connection:
            rows = connection.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        try:
            return tuple(_bar_from_row(row) for row in rows)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise MarketServingIntegrityError(
                "market_serving_projection_invalid"
            ) from exc

    def _ensure_schema(
        self,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with closing(self._connect()) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS serving_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS daily_bar_projection (
                    provider TEXT NOT NULL,

                    instrument_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session_date TEXT NOT NULL,

                    event_time TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,

                    open TEXT NOT NULL,
                    high TEXT NOT NULL,
                    low TEXT NOT NULL,
                    close TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    amount TEXT NOT NULL,

                    suspended INTEGER NOT NULL,

                    revision_id TEXT NOT NULL,
                    materialization_id TEXT NOT NULL,

                    PRIMARY KEY (
                        provider,
                        instrument_type,
                        symbol,
                        session_date
                    )
                )
                """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_daily_bar_projection_provider_date
                ON daily_bar_projection (
                    provider,
                    session_date
                )
                """)

            existing = connection.execute("""
                SELECT value
                FROM serving_metadata
                WHERE key = 'schema_version'
                """).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO serving_metadata (
                        key,
                        value
                    )
                    VALUES (
                        'schema_version',
                        ?
                    )
                    """,
                    (str(_MARKET_SERVING_SCHEMA_VERSION),),
                )

            elif existing[0] != str(_MARKET_SERVING_SCHEMA_VERSION):
                raise MarketServingIntegrityError("market_serving_schema_unsupported")

            connection.commit()

    def _require_schema(
        self,
    ) -> None:
        with closing(self._connect(read_only=True)) as connection:
            try:
                row = connection.execute("""
                    SELECT value
                    FROM serving_metadata
                    WHERE key = 'schema_version'
                    """).fetchone()
            except sqlite3.DatabaseError as exc:
                raise MarketServingIntegrityError(
                    "market_serving_store_invalid"
                ) from exc

        if row is None:
            raise MarketServingIntegrityError("market_serving_schema_missing")

        if row[0] != str(_MARKET_SERVING_SCHEMA_VERSION):
            raise MarketServingIntegrityError("market_serving_schema_unsupported")

    def _connect(
        self,
        *,
        read_only: bool = False,
    ) -> sqlite3.Connection:
        if read_only:
            uri = self._path.resolve().as_uri() + "?mode=ro"

            return sqlite3.connect(
                uri,
                uri=True,
            )

        return sqlite3.connect(self._path)


def _apply_bar(
    connection: sqlite3.Connection,
    *,
    bar: DailyBarObservation,
    provider: str,
    revision_id: str,
    materialization_id: str,
) -> str:
    """应用单条 projection，并返回状态。"""
    existing = connection.execute(
        """
        SELECT
            captured_at,
            revision_id,
            materialization_id
        FROM daily_bar_projection
        WHERE
            provider = ?
            AND instrument_type = ?
            AND symbol = ?
            AND session_date = ?
        """,
        (
            provider,
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
            bar.session_date.isoformat(),
        ),
    ).fetchone()

    if existing is not None:
        (
            existing_captured_at,
            existing_revision_id,
            existing_materialization_id,
        ) = existing

        existing_capture = _parse_utc_instant(
            existing_captured_at,
            field="captured_at",
        )

        if existing_capture > bar.captured_at:
            return "stale"

        if existing_capture == bar.captured_at:
            if (
                existing_revision_id == revision_id
                and existing_materialization_id == materialization_id
            ):
                return "unchanged"

            raise MarketServingConflictError(
                "market_serving_same_capture_conflict:"
                f"{provider}:"
                f"{bar.instrument.instrument_type.value}:"
                f"{bar.instrument.symbol}:"
                f"{bar.session_date.isoformat()}"
            )

        state = "updated"

    else:
        state = "inserted"

    connection.execute(
        """
        INSERT INTO daily_bar_projection (
            provider,
            instrument_type,
            symbol,
            session_date,

            event_time,
            available_at,
            captured_at,

            open,
            high,
            low,
            close,
            volume,
            amount,

            suspended,

            revision_id,
            materialization_id
        )
        VALUES (
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?,
            ?, ?
        )
        ON CONFLICT (
            provider,
            instrument_type,
            symbol,
            session_date
        )
        DO UPDATE SET
            event_time = excluded.event_time,
            available_at = excluded.available_at,
            captured_at = excluded.captured_at,

            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            amount = excluded.amount,

            suspended = excluded.suspended,

            revision_id = excluded.revision_id,
            materialization_id = excluded.materialization_id
        """,
        (
            provider,
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
            bar.session_date.isoformat(),
            _format_utc_instant(bar.event_time),
            _format_utc_instant(bar.available_at),
            _format_utc_instant(bar.captured_at),
            _format_decimal(bar.open),
            _format_decimal(bar.high),
            _format_decimal(bar.low),
            _format_decimal(bar.close),
            _format_decimal(bar.volume),
            _format_decimal(bar.amount),
            int(bar.suspended),
            revision_id,
            materialization_id,
        ),
    )

    return state


def _bar_from_row(
    row,
) -> DailyBarObservation:
    (
        instrument_type,
        symbol,
        session_date,
        event_time,
        available_at,
        captured_at,
        open_value,
        high_value,
        low_value,
        close_value,
        volume,
        amount,
        suspended,
    ) = row

    if suspended not in (
        0,
        1,
    ):
        raise ValueError("market_serving_suspended_invalid")

    return DailyBarObservation(
        instrument=InstrumentKey(
            symbol=symbol,
            instrument_type=InstrumentType(instrument_type),
        ),
        session_date=_parse_date(
            session_date,
            field="session_date",
        ),
        event_time=_parse_utc_instant(
            event_time,
            field="event_time",
        ),
        available_at=_parse_utc_instant(
            available_at,
            field="available_at",
        ),
        captured_at=_parse_utc_instant(
            captured_at,
            field="captured_at",
        ),
        open=Decimal(open_value),
        high=Decimal(high_value),
        low=Decimal(low_value),
        close=Decimal(close_value),
        volume=Decimal(volume),
        amount=Decimal(amount),
        suspended=bool(suspended),
    )


def _canonical_instruments(
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
) -> tuple[
    InstrumentKey,
    ...,
]:
    result = []
    seen = set()

    for instrument in instruments:
        if not isinstance(
            instrument,
            InstrumentKey,
        ):
            raise TypeError("market_serving_instrument_invalid")

        if instrument in seen:
            raise ValueError("market_serving_instrument_duplicate")

        seen.add(instrument)
        result.append(instrument)

    result.sort(
        key=lambda instrument: (
            instrument.instrument_type.value,
            instrument.symbol,
        )
    )

    return tuple(result)


def _format_decimal(
    value: Decimal,
) -> str:
    if not isinstance(
        value,
        Decimal,
    ):
        raise TypeError("market_serving_decimal_invalid")

    return format(
        value,
        "f",
    )


def _format_utc_instant(
    value: datetime,
) -> str:
    value = _utc_instant(
        value,
        field="timestamp",
    )

    return value.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _parse_utc_instant(
    value: object,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise ValueError(f"market_serving_{field}_invalid")

    if not value.endswith("Z"):
        raise ValueError(f"market_serving_{field}_invalid")

    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"market_serving_{field}_invalid") from exc

    result = result.astimezone(timezone.utc)

    if _format_utc_instant(result) != value:
        raise ValueError(f"market_serving_{field}_invalid")

    return result


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(f"market_serving_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"market_serving_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _parse_date(
    value: object,
    *,
    field: str,
) -> date:
    if not isinstance(
        value,
        str,
    ):
        raise ValueError(f"market_serving_{field}_invalid")

    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"market_serving_{field}_invalid") from exc

    if result.isoformat() != value:
        raise ValueError(f"market_serving_{field}_invalid")

    return result


def _require_date(
    value: date,
    *,
    field: str,
) -> date:
    if isinstance(
        value,
        datetime,
    ) or not isinstance(
        value,
        date,
    ):
        raise TypeError(f"market_serving_{field}_must_be_date")

    return value


def _require_non_empty_text(
    value: str,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(f"market_serving_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"market_serving_{field}_missing")

    return normalized
