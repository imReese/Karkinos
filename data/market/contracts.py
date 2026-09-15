"""Market Data Provider 边界契约。

本模块定义 Market Data domain 对外部 Provider Adapter 的最小要求。

依赖方向必须保持：

    data.market.contracts
              ↑
              │ implements
              │
    data.providers.*

Market Data domain 不依赖 TDX、TuShare、AKShare 等具体实现。

本文件只定义能力契约和 Provider 边界值，不执行网络请求、
数据持久化、canonical normalization 或质量判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol, runtime_checkable

from core.types import InstrumentKey

ProviderNumber = Decimal | int | float | str


@dataclass(frozen=True, slots=True)
class DailyBarRequest:
    """一次 canonical 日线数据请求。

    请求使用 Karkinos 的 InstrumentKey，而不是 Provider 自己的代码格式。
    Provider Adapter 负责将 InstrumentKey 映射为 TDX、TuShare、AKShare
    各自要求的标的表示。

    instruments 是一个明确的研究/采集范围，不使用空集合表示“全市场”，
    避免请求语义产生歧义。
    """

    instruments: tuple[InstrumentKey, ...]
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if not isinstance(self.start_date, date) or isinstance(
            self.start_date,
            datetime,
        ):
            raise TypeError("daily_bar_request_start_date_must_be_date")

        if not isinstance(self.end_date, date) or isinstance(
            self.end_date,
            datetime,
        ):
            raise TypeError("daily_bar_request_end_date_must_be_date")

        if self.end_date < self.start_date:
            raise ValueError("daily_bar_request_end_before_start")

        if not isinstance(self.instruments, tuple):
            raise TypeError("daily_bar_request_instruments_must_be_tuple")

        if not self.instruments:
            raise ValueError("daily_bar_request_instruments_empty")

        seen: set[tuple[str, str]] = set()

        for instrument in self.instruments:
            if not isinstance(instrument, InstrumentKey):
                raise TypeError("daily_bar_request_instrument_invalid")

            key = instrument.storage_tuple()

            if key in seen:
                raise ValueError("daily_bar_request_duplicate_instrument")

            seen.add(key)

        # instruments 在请求语义上是集合，因此统一排序。
        # 调用方传入顺序不能影响请求身份或 Provider 调用语义。
        canonical = tuple(
            sorted(
                self.instruments,
                key=lambda instrument: (
                    instrument.instrument_type.value,
                    instrument.symbol,
                ),
            )
        )

        object.__setattr__(
            self,
            "instruments",
            canonical,
        )

    def to_capture_request(self) -> dict[str, object]:
        """生成可安全写入 Provider Capture 的请求描述。

        这里只包含数据请求本身，不包含 Token、API Key 等认证信息。
        """
        return {
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "instruments": [
                {
                    "symbol": instrument.symbol,
                    "instrument_type": (instrument.instrument_type.value),
                }
                for instrument in self.instruments
            ],
        }


@dataclass(frozen=True, slots=True)
class ProviderDailyBarRow:
    """Provider Adapter 提取出的单条日线记录。

    这是 Provider 边界值，不是 canonical Market Data。

    Provider Adapter 在这里已经完成供应商格式解释，例如：

    - 将 TDX 的字段名映射成 open_value / close_value；
    - 将 TuShare 的 ts_code 映射成 InstrumentKey；
    - 将 AKShare 的中文列名解释成统一字段；
    - 明确交易日和市场事件时间。

    数值暂时允许 Decimal / int / float / str，后续由
    ``market.normalize`` 转换成严格的 canonical Decimal。

    ``available_at`` 可以为 None，表示 Provider 没有提供更强的
    信息可用时间证据。Ingestion 必须显式使用 Capture 完成时间作为
    保守的可用时间，不能由本对象自行猜测。
    """

    instrument: InstrumentKey
    session_date: date | str

    event_time: datetime
    available_at: datetime | None

    open_value: ProviderNumber
    high_value: ProviderNumber
    low_value: ProviderNumber
    close_value: ProviderNumber

    volume: ProviderNumber
    amount: ProviderNumber

    suspended: bool

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, InstrumentKey):
            raise TypeError("provider_daily_bar_instrument_invalid")

        if not isinstance(
            self.session_date,
            (date, str),
        ) or isinstance(
            self.session_date,
            datetime,
        ):
            raise TypeError("provider_daily_bar_session_date_invalid")

        _require_aware_datetime(
            self.event_time,
            field="event_time",
        )

        if self.available_at is not None:
            _require_aware_datetime(
                self.available_at,
                field="available_at",
            )

        if not isinstance(self.suspended, bool):
            raise TypeError("provider_daily_bar_suspended_must_be_bool")


@dataclass(frozen=True, slots=True)
class ProviderDailyBarBatch:
    """一次 Provider 日线调用的完整返回结果。

    raw_payload 保存 Provider 原始响应的稳定字节表示；
    rows 保存 Adapter 从该响应中提取出的 provider-neutral 字段。

    两者必须来自同一次 Provider 调用：

        Provider response
             │
             ├── raw_payload  → ProviderCapture
             │
             └── rows         → canonical normalization

    Provider Adapter 不负责把这些 rows 持久化成 MarketRevision。
    """

    provider: str
    adapter_version: str
    payload_format: str

    started_at: datetime
    completed_at: datetime

    raw_payload: bytes
    rows: tuple[ProviderDailyBarRow, ...]

    def __post_init__(self) -> None:
        provider = _require_non_empty_text(
            self.provider,
            field="provider",
        )
        adapter_version = _require_non_empty_text(
            self.adapter_version,
            field="adapter_version",
        )
        payload_format = _require_non_empty_text(
            self.payload_format,
            field="payload_format",
        )

        started_at = _utc_instant(
            self.started_at,
            field="started_at",
        )
        completed_at = _utc_instant(
            self.completed_at,
            field="completed_at",
        )

        if completed_at < started_at:
            raise ValueError("provider_daily_bar_completed_before_started")

        if not isinstance(self.raw_payload, bytes):
            raise TypeError("provider_daily_bar_raw_payload_must_be_bytes")

        if not isinstance(self.rows, tuple):
            raise TypeError("provider_daily_bar_rows_must_be_tuple")

        for row in self.rows:
            if not isinstance(row, ProviderDailyBarRow):
                raise TypeError("provider_daily_bar_rows_contains_invalid_value")

        object.__setattr__(
            self,
            "provider",
            provider,
        )
        object.__setattr__(
            self,
            "adapter_version",
            adapter_version,
        )
        object.__setattr__(
            self,
            "payload_format",
            payload_format,
        )
        object.__setattr__(
            self,
            "started_at",
            started_at,
        )
        object.__setattr__(
            self,
            "completed_at",
            completed_at,
        )

    @property
    def record_count(self) -> int:
        """Adapter 成功提取出的日线记录数。"""
        return len(self.rows)

    @property
    def elapsed_ms(self) -> int:
        """本次 Provider 调用耗时，单位毫秒。"""
        duration = self.completed_at - self.started_at
        return int(duration.total_seconds() * 1000)


@runtime_checkable
class DailyBarProvider(Protocol):
    """日线数据 Provider 能力契约。

    Provider Adapter 只负责：

    1. 根据 canonical request 调用外部 Provider；
    2. 保存可用于 Capture 的原始响应字节；
    3. 解释 Provider 自己的字段和标的编码；
    4. 返回 provider-neutral 的 ProviderDailyBarRow。

    Provider Adapter 不负责：

    - 写入 ObjectStore；
    - 创建 ProviderCapture；
    - 创建 MarketRevision；
    - PIT Dataset 选择；
    - Quality Gate；
    - Backtest。

    canonical ingestion 的日线价格必须使用未复权/raw 市场事实。
    前复权、后复权等价格视图属于后续 Dataset / corporate-action
    派生语义，不能成为底层 Market Data 唯一事实。
    """

    def fetch_daily_bars(
        self,
        request: DailyBarRequest,
    ) -> ProviderDailyBarBatch:
        """获取一批未复权日线数据。"""
        ...


def _require_aware_datetime(
    value: datetime,
    *,
    field: str,
) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"provider_daily_bar_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"provider_daily_bar_{field}_must_be_timezone_aware")


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    _require_aware_datetime(
        value,
        field=field,
    )

    return value.astimezone(timezone.utc)


def _require_non_empty_text(
    value: str,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"provider_daily_bar_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"provider_daily_bar_{field}_missing")

    return normalized
