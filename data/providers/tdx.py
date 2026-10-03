"""通达信 TdxAiData 日线适配与专用 SDK 运行时准备。

本模块把通达信 tdxaidata 的外部数据转换为 Karkinos Provider Contract：

    tdxaidata.tqs.get_market_data(...)
                ↓
          TDX response
                ↓
      ProviderDailyBarBatch
                ↓
       Market Data ingestion

行情适配部分只负责 Provider 边界转换，不负责：

- 创建 Capture；
- canonical MarketRevision；
- Quality Gate；
- Dataset；
- 自动重试；
- Provider fallback。

第一版能力明确限制为：

- 日线；
- 单个 session_date；
- A 股股票和 ETF；
- 不复权；
- 不自动填充缺失 K 线。

正式 canonical Market Data 必须使用 raw/unadjusted OHLC。
运行时准备只在父进程生成私有临时配置；导入本模块不会加载原生 SDK。
"""

from __future__ import annotations

import configparser
import importlib
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from importlib import metadata
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import (
    DailyBarCapability,
    DailyBarProviderUnavailableError,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
    ProviderDailyBarRow,
)

logger = logging.getLogger(__name__)


TDX_PROVIDER_NAME = "tdx"

TDX_DAILY_BAR_ADAPTER_VERSION = "karkinos.tdx.daily_bar.v1"

TDX_DAILY_BAR_PAYLOAD_FORMAT = "tdx.get_market_data.dataframe.v1"

TDX_PROVIDER_DESCRIPTOR = MarketDataProviderDescriptor(
    provider=TDX_PROVIDER_NAME,
    upstream_group="tdx",
    adapter_version=TDX_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="tdxaidata.tqs.get_market_data",
            instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
            price_basis="unadjusted",
        ),
    ),
)


_TDX_DAILY_FIELDS = (
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Amount",
)

_TDX_AMOUNT_TO_YUAN = Decimal("10000")

_SHANGHAI = ZoneInfo("Asia/Shanghai")

_SIX_DIGIT_SYMBOL = re.compile(r"^[0-9]{6}$")

_SH_STOCK_PREFIXES = (
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
)

_SZ_STOCK_PREFIXES = (
    "000",
    "001",
    "002",
    "003",
    "300",
    "301",
)


class TdxProviderError(RuntimeError):
    """TDX Provider 基础异常。"""


class TdxProviderUnavailableError(
    TdxProviderError,
    DailyBarProviderUnavailableError,
):
    """TDX SDK or native runtime is currently unavailable."""


class TdxProviderTransportError(
    TdxProviderError,
    DailyBarProviderUnavailableError,
):
    """TDX data-service request I/O failed after the SDK was available."""


class TdxProviderRequestError(TdxProviderError):
    """请求超出当前 TDX Adapter 支持范围。"""


class TdxProviderResponseError(TdxProviderError):
    """TDX 返回值无法安全转换为 Provider Contract。"""


class _TdxClient(Protocol):
    def get_market_data(
        self,
        *,
        field_list: list[str],
        stock_list: list[str],
        period: str,
        start_time: str,
        end_time: str,
        count: int,
        dividend_type: str,
        fill_data: bool,
    ) -> object: ...


class TdxDailyBarProvider:
    """基于独立 tdxaidata 包的 TDX 日线 Provider。"""

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return TDX_PROVIDER_DESCRIPTOR

    def __init__(
        self,
        client: _TdxClient | None = None,
        *,
        clock: Callable[
            [],
            datetime,
        ]
        | None = None,
    ) -> None:
        self._client = client
        self._clock = clock if clock is not None else _utc_now

    def fetch_daily_bars(
        self,
        request: DailyBarRequest,
    ) -> ProviderDailyBarBatch:
        """获取一份单交易日、不复权的 TDX 日线批次。"""
        if not isinstance(
            request,
            DailyBarRequest,
        ):
            raise TypeError("tdx_daily_bar_request_invalid")

        if request.start_date != request.end_date:
            raise TdxProviderRequestError(
                "tdx_daily_bar_request_must_be_single_session"
            )

        started_at = _require_aware_utc(
            self._clock(),
            field="started_at",
        )

        session_close = _session_close_utc(request.start_date)

        if started_at < session_close:
            raise TdxProviderRequestError("tdx_daily_bar_session_not_closed")

        (
            stock_list,
            code_to_instrument,
        ) = _build_tdx_symbols(request.instruments)

        client = self._resolve_client()

        logger.debug(
            "开始请求 TDX 日线 session=%s instruments=%d",
            request.start_date.isoformat(),
            len(stock_list),
        )

        try:
            response = client.get_market_data(
                field_list=list(_TDX_DAILY_FIELDS),
                stock_list=list(stock_list),
                period="1d",
                start_time=(request.start_date.strftime("%Y%m%d")),
                end_time=(request.end_date.strftime("%Y%m%d")),
                count=-1,
                dividend_type="none",
                fill_data=False,
            )
        except Exception as exc:
            raise TdxProviderTransportError("tdx_get_market_data_failed") from exc

        completed_at = _require_aware_utc(
            self._clock(),
            field="completed_at",
        )

        if completed_at < started_at:
            raise TdxProviderError("tdx_provider_clock_moved_backwards")

        rows = _response_to_rows(
            response,
            code_to_instrument=(code_to_instrument),
            expected_session=(request.start_date),
        )

        raw_payload = _serialize_response(response)

        logger.debug(
            "TDX 日线请求完成 session=%s instruments=%d rows=%d",
            request.start_date.isoformat(),
            len(stock_list),
            len(rows),
        )

        return ProviderDailyBarBatch(
            provider=TDX_PROVIDER_NAME,
            adapter_version=(TDX_DAILY_BAR_ADAPTER_VERSION),
            payload_format=(TDX_DAILY_BAR_PAYLOAD_FORMAT),
            started_at=started_at,
            completed_at=completed_at,
            raw_payload=raw_payload,
            rows=rows,
        )

    def _resolve_client(
        self,
    ) -> _TdxClient:
        if self._client is not None:
            return self._client

        try:
            # 独立安装包公开的是 tdxaidata.tqs，不是客户端目录中的 tqserver。
            module = importlib.import_module("tdxaidata")
        except ModuleNotFoundError as exc:
            code = (
                "tdx_sdk_not_installed"
                if exc.name == "tdxaidata"
                else "tdx_sdk_dependency_missing"
            )
            raise TdxProviderUnavailableError(code) from exc
        except (ImportError, OSError) as exc:
            raise TdxProviderUnavailableError("tdx_sdk_load_failed") from exc

        client = getattr(
            module,
            "tqs",
            None,
        )

        if client is None or not callable(
            getattr(
                client,
                "get_market_data",
                None,
            )
        ):
            raise TdxProviderUnavailableError("tdx_sdk_client_unavailable")

        self._client = client

        return client


def _build_tdx_symbols(
    instruments: tuple[
        InstrumentKey,
        ...,
    ],
) -> tuple[
    tuple[str, ...],
    dict[
        str,
        InstrumentKey,
    ],
]:
    codes: list[str] = []

    code_to_instrument: dict[
        str,
        InstrumentKey,
    ] = {}

    for instrument in instruments:
        if not isinstance(
            instrument,
            InstrumentKey,
        ):
            raise TypeError("tdx_instrument_invalid")

        code = _tdx_code(instrument)

        if code in code_to_instrument:
            raise TdxProviderRequestError("tdx_instrument_mapping_collision")

        codes.append(code)
        code_to_instrument[code] = instrument

    return (
        tuple(codes),
        code_to_instrument,
    )


def _tdx_code(
    instrument: InstrumentKey,
) -> str:
    """把 canonical InstrumentKey 转换为 TDX 标准代码。"""
    symbol = instrument.symbol.strip()

    if _SIX_DIGIT_SYMBOL.fullmatch(symbol) is None:
        raise TdxProviderRequestError(f"tdx_symbol_must_be_six_digits:{symbol}")

    if instrument.instrument_type is InstrumentType.STOCK:
        exchange = _stock_exchange(symbol)

    elif instrument.instrument_type is InstrumentType.ETF:
        exchange = _etf_exchange(symbol)

    else:
        raise TdxProviderRequestError(
            f"tdx_instrument_type_unsupported:{instrument.instrument_type.value}"
        )

    return f"{symbol}.{exchange}"


def _stock_exchange(
    symbol: str,
) -> str:
    if symbol.startswith(_SH_STOCK_PREFIXES):
        return "SH"

    if symbol.startswith(_SZ_STOCK_PREFIXES):
        return "SZ"

    # 北交所历史代码主要分布在 4/8 段，
    # 新代码也存在 920xxx。
    if symbol.startswith("4") or symbol.startswith("8") or symbol.startswith("920"):
        return "BJ"

    raise TdxProviderRequestError(f"tdx_stock_exchange_unknown:{symbol}")


def _etf_exchange(
    symbol: str,
) -> str:
    # 沪市 ETF 主要位于 5xxxxx，
    # 深市 ETF / 部分场内基金主要位于 1xxxxx。
    if symbol.startswith("5"):
        return "SH"

    if symbol.startswith("1"):
        return "SZ"

    raise TdxProviderRequestError(f"tdx_etf_exchange_unknown:{symbol}")


def _response_to_rows(
    response: object,
    *,
    code_to_instrument: dict[
        str,
        InstrumentKey,
    ],
    expected_session: date,
) -> tuple[
    ProviderDailyBarRow,
    ...,
]:
    if not isinstance(
        response,
        dict,
    ):
        raise TdxProviderResponseError("tdx_response_must_be_dict")

    if not response:
        # SDK 在没有任何可用时间索引时返回 {}，原因可能是无数据或底层失败。
        # 不能补零、假定认证成功，或把它混淆为 Open 的拼写错误。
        raise TdxProviderResponseError("tdx_response_empty")

    requested_codes = tuple(code_to_instrument)

    field_values: dict[
        str,
        dict[
            tuple[str, date],
            object,
        ],
    ] = {}

    for field in _TDX_DAILY_FIELDS:
        if field not in response:
            raise TdxProviderResponseError(f"tdx_response_field_missing:{field}")

        field_values[field] = _dataframe_points(
            response[field],
            requested_codes=(requested_codes),
            field=field,
        )

    keys: set[tuple[str, date]] = set()

    for points in field_values.values():
        keys.update(points)

    rows: list[ProviderDailyBarRow] = []

    for code, session_date in sorted(
        keys,
        key=lambda item: (
            item[1],
            item[0],
        ),
    ):
        if code not in code_to_instrument:
            raise TdxProviderResponseError(f"tdx_response_instrument_unexpected:{code}")

        if session_date != expected_session:
            raise TdxProviderResponseError(
                f"tdx_response_session_unexpected:{session_date.isoformat()}"
            )

        values: dict[
            str,
            object,
        ] = {}

        for field in _TDX_DAILY_FIELDS:
            key = (
                code,
                session_date,
            )

            if key not in field_values[field]:
                raise TdxProviderResponseError(
                    "tdx_response_row_incomplete:"
                    f"{code}:"
                    f"{session_date.isoformat()}:"
                    f"{field}"
                )

            values[field] = field_values[field][key]

        amount_wan_yuan = _decimal(
            values["Amount"],
            field="Amount",
        )

        rows.append(
            ProviderDailyBarRow(
                instrument=(code_to_instrument[code]),
                session_date=(session_date),
                event_time=(_daily_event_time(session_date)),
                # tqserver get_market_data 没有为每根日线提供
                # 可证明的 provider publication timestamp。
                # ingestion 会保守 fallback 到 batch.completed_at。
                available_at=None,
                open_value=_decimal(
                    values["Open"],
                    field="Open",
                ),
                high_value=_decimal(
                    values["High"],
                    field="High",
                ),
                low_value=_decimal(
                    values["Low"],
                    field="Low",
                ),
                close_value=_decimal(
                    values["Close"],
                    field="Close",
                ),
                volume=_decimal(
                    values["Volume"],
                    field="Volume",
                ),
                # TDX 官方接口的 Amount 单位为万元；
                # canonical Market Data 统一使用元。
                amount=(amount_wan_yuan * _TDX_AMOUNT_TO_YUAN),
                # fill_data=False 时只把实际返回 K 线作为事实。
                # 第一版不根据缺失记录猜测“停牌”。
                suspended=False,
            )
        )

    return tuple(rows)


def _dataframe_points(
    value: object,
    *,
    requested_codes: tuple[
        str,
        ...,
    ],
    field: str,
) -> dict[
    tuple[str, date],
    object,
]:
    """兼容 TDX 文档中出现过的两种 DataFrame 朝向。

    支持：

        日期 × 股票

    以及：

        股票 × 日期

    不通过猜测 transpose，而是根据明确请求的 TDX code 判断哪一轴是
    instrument axis。
    """
    if not isinstance(
        value,
        pd.DataFrame,
    ):
        raise TdxProviderResponseError(f"tdx_response_field_must_be_dataframe:{field}")

    if value.empty:
        return {}

    requested = set(requested_codes)

    column_labels = {str(label): label for label in value.columns}

    index_labels = {str(label): label for label in value.index}

    codes_in_columns = requested & set(column_labels)

    codes_in_index = requested & set(index_labels)

    if codes_in_columns and codes_in_index:
        raise TdxProviderResponseError(f"tdx_response_axes_ambiguous:{field}")

    result: dict[
        tuple[str, date],
        object,
    ] = {}

    if codes_in_columns:
        for code in requested_codes:
            original_column = column_labels.get(code)

            if original_column is None:
                continue

            series = value[original_column]

            for raw_date, raw_value in series.items():
                if _is_missing(raw_value):
                    continue

                _put_point(
                    result,
                    code=code,
                    session_date=(_session_date(raw_date)),
                    value=raw_value,
                    field=field,
                )

        return result

    if codes_in_index:
        for code in requested_codes:
            original_index = index_labels.get(code)

            if original_index is None:
                continue

            row = value.loc[original_index]

            if isinstance(
                row,
                pd.DataFrame,
            ):
                raise TdxProviderResponseError(
                    f"tdx_response_duplicate_code_axis:{field}:{code}"
                )

            for raw_date, raw_value in row.items():
                if _is_missing(raw_value):
                    continue

                _put_point(
                    result,
                    code=code,
                    session_date=(_session_date(raw_date)),
                    value=raw_value,
                    field=field,
                )

        return result

    raise TdxProviderResponseError(f"tdx_response_instrument_axis_missing:{field}")


def _put_point(
    result: dict[
        tuple[str, date],
        object,
    ],
    *,
    code: str,
    session_date: date,
    value: object,
    field: str,
) -> None:
    key = (
        code,
        session_date,
    )

    if key in result:
        raise TdxProviderResponseError(
            f"tdx_response_duplicate_point:{field}:{code}:{session_date.isoformat()}"
        )

    result[key] = value


def _session_date(
    value: object,
) -> date:
    if isinstance(
        value,
        pd.Timestamp,
    ):
        return value.date()

    if isinstance(
        value,
        datetime,
    ):
        return value.date()

    if isinstance(
        value,
        date,
    ) and not isinstance(
        value,
        datetime,
    ):
        return value

    if isinstance(
        value,
        bool,
    ):
        raise TdxProviderResponseError("tdx_response_date_invalid")

    if isinstance(
        value,
        int,
    ):
        text = str(value)

    elif isinstance(
        value,
        float,
    ):
        if not math.isfinite(value) or not value.is_integer():
            raise TdxProviderResponseError("tdx_response_date_invalid")

        text = str(int(value))

    elif isinstance(
        value,
        str,
    ):
        text = value.strip()

    else:
        raise TdxProviderResponseError("tdx_response_date_invalid")

    for format_string in (
        "%Y-%m-%d",
        "%Y%m%d",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(
                text,
                format_string,
            ).date()
        except ValueError:
            continue

    raise TdxProviderResponseError(f"tdx_response_date_invalid:{text}")


def _decimal(
    value: object,
    *,
    field: str,
) -> Decimal:
    if isinstance(
        value,
        bool,
    ):
        raise TdxProviderResponseError(f"tdx_response_number_invalid:{field}")

    if isinstance(
        value,
        Decimal,
    ):
        result = value

    elif isinstance(
        value,
        int,
    ):
        result = Decimal(value)

    elif isinstance(
        value,
        float,
    ):
        if not math.isfinite(value):
            raise TdxProviderResponseError(f"tdx_response_number_invalid:{field}")

        result = Decimal(str(value))

    elif isinstance(
        value,
        str,
    ):
        text = value.strip()

        if not text:
            raise TdxProviderResponseError(f"tdx_response_number_invalid:{field}")

        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise TdxProviderResponseError(
                f"tdx_response_number_invalid:{field}"
            ) from exc

    else:
        scalar = _python_scalar(value)

        if scalar is value:
            raise TdxProviderResponseError(f"tdx_response_number_invalid:{field}")

        return _decimal(
            scalar,
            field=field,
        )

    if not result.is_finite():
        raise TdxProviderResponseError(f"tdx_response_number_invalid:{field}")

    return result


def _serialize_response(
    response: object,
) -> bytes:
    """把 TDX Python 返回对象固化成稳定 JSON bytes。

    tqserver 返回的是 Python dict + pandas.DataFrame，并不存在原始 HTTP
    response bytes，因此这里保存 Adapter 实际观察到的矩阵结构与数值。
    """
    if not isinstance(
        response,
        dict,
    ):
        raise TdxProviderResponseError("tdx_response_must_be_dict")

    fields: dict[
        str,
        object,
    ] = {}

    for key in sorted(
        response,
        key=str,
    ):
        if not isinstance(
            key,
            str,
        ):
            raise TdxProviderResponseError("tdx_response_key_invalid")

        value = response[key]

        if isinstance(
            value,
            pd.DataFrame,
        ):
            fields[key] = _serialize_dataframe(value)
        else:
            fields[key] = _json_scalar(value)

    payload = {
        "schema": (TDX_DAILY_BAR_PAYLOAD_FORMAT),
        "fields": fields,
    }

    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TdxProviderResponseError("tdx_response_serialization_failed") from exc

    return text.encode("utf-8")


def _serialize_dataframe(
    frame: pd.DataFrame,
) -> dict[
    str,
    object,
]:
    return {
        "index": [_json_scalar(value) for value in frame.index],
        "columns": [_json_scalar(value) for value in frame.columns],
        "data": [
            [_json_scalar(value) for value in row]
            for row in frame.itertuples(
                index=False,
                name=None,
            )
        ],
    }


def _json_scalar(
    value: object,
) -> object:
    if value is None:
        return None

    if isinstance(
        value,
        pd.Timestamp,
    ):
        return value.isoformat()

    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(timezone.utc)

        return value.isoformat()

    if isinstance(
        value,
        date,
    ):
        return value.isoformat()

    if isinstance(
        value,
        Decimal,
    ):
        return format(
            value,
            "f",
        )

    scalar = _python_scalar(value)

    if scalar is not value:
        return _json_scalar(scalar)

    if isinstance(
        value,
        bool | int | str,
    ):
        return value

    if isinstance(
        value,
        float,
    ):
        if math.isnan(value):
            return None

        if not math.isfinite(value):
            raise TdxProviderResponseError("tdx_response_non_finite_number")

        return value

    raise TdxProviderResponseError(
        f"tdx_response_scalar_unsupported:{type(value).__name__}"
    )


def _python_scalar(
    value: object,
) -> object:
    item = getattr(
        value,
        "item",
        None,
    )

    if not callable(item):
        return value

    try:
        return item()
    except (
        TypeError,
        ValueError,
    ):
        return value


def _is_missing(
    value: object,
) -> bool:
    try:
        result = pd.isna(value)
    except (
        TypeError,
        ValueError,
    ):
        return False

    return bool(result)


def _daily_event_time(
    session_date: date,
) -> datetime:
    """日线 canonical event time 使用 A 股正常收盘时点。"""
    local = datetime.combine(
        session_date,
        time(
            15,
            0,
        ),
        tzinfo=_SHANGHAI,
    )

    return local.astimezone(timezone.utc)


def _session_close_utc(
    session_date: date,
) -> datetime:
    return _daily_event_time(session_date)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware_utc(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(f"tdx_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"tdx_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


# Parent-process preparation for the same TDX upstream. The native SDK stays lazy.
TDX_KEY_ENV = "KARKINOS_TDX_DATA_SERVICE_KEY"
TDX_USER_ENV = "KARKINOS_TDX_USER"


class TdxRuntimeConfigurationError(ValueError):
    """启动配置不完整或 SDK 布局尚未验证；错误消息不包含秘密值。"""


@dataclass(frozen=True, slots=True)
class TdxRuntimeSettings:
    """从本次启动快照中提取的 TDX 配置，不包含其他服务的凭据。"""

    data_service_key: str = field(default="", repr=False)
    user: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        for name in ("data_service_key", "user"):
            value = getattr(self, name)
            # 原生 INI 只接收单行文本，禁止通过换行或控制字符注入新配置。
            if not isinstance(value, str) or any(
                ord(character) < 32 or ord(character) == 127 for character in value
            ):
                raise TdxRuntimeConfigurationError(f"tdx_{name}_invalid")
            object.__setattr__(self, name, value.strip())

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> TdxRuntimeSettings:
        """只解析调用方传入的映射，不自行读取进程全局变量或文件。"""
        return cls(
            data_service_key=values.get(TDX_KEY_ENV, ""),
            user=values.get(TDX_USER_ENV, ""),
        )

    @property
    def configured(self) -> bool:
        return bool(self.data_service_key)

    def require_credentials(self) -> None:
        if not self.configured:
            raise TdxRuntimeConfigurationError("tdx_data_service_key_missing")


def _sdk_library_directory() -> Path:
    """只读发行包元数据，不导入 SDK，也不加载动态库。"""
    try:
        distribution = metadata.distribution("tdxaidata")
    except metadata.PackageNotFoundError:
        raise TdxRuntimeConfigurationError("tdx_sdk_not_installed") from None
    if distribution.version != "1.0.2":
        raise TdxRuntimeConfigurationError("tdx_sdk_runtime_version_unsupported")
    return Path(str(distribution.locate_file("tdxaidata/lib"))).resolve()


class _CaseSensitiveConfigParser(configparser.ConfigParser):
    """Preserve the vendor configuration keys exactly."""

    def optionxform(self, optionstr: str) -> str:
        return str(optionstr)


@contextmanager
def prepare_tdx_runtime(
    settings: TdxRuntimeSettings,
) -> Iterator[Path]:
    """为一个受管子进程准备临时 SDK 目录，退出上下文后清理。

    返回应写入子进程 TDX_AI_DATA_LIB 的绝对路径，不修改 os.environ。
    不把秘密放在参数、返回报告、site-packages 或保留的数据输出目录中。
    Key 更新后下一次调用会生成新的配置，不共享 SDK 的进程内单例。
    """
    settings.require_credentials()
    source = _sdk_library_directory()
    names: tuple[str, ...]
    if os.name == "nt":
        names = ("TdxAiData.dll", "mfc100.dll", "msvcp100.dll", "msvcr100.dll")
    elif sys.platform == "darwin":
        names = ("libTdxAiData.dylib",)
    elif sys.platform.startswith("linux"):
        names = ("libTdxAiData.so",)
    else:
        raise TdxRuntimeConfigurationError("tdx_sdk_platform_unsupported")
    template = source / "TdxAiData.ini"
    if not template.is_file() or any(not (source / name).is_file() for name in names):
        raise TdxRuntimeConfigurationError("tdx_sdk_runtime_files_missing")

    config = _CaseSensitiveConfigParser(interpolation=None)
    try:
        with template.open(encoding="utf-8-sig") as input_file:
            config.read_file(input_file)
        # 仅接受已核对版本的模板结构，不能把安装目录中未知配置带入运行环境。
        if config.defaults() or set(config.sections()) != {
            "TcHqHost",
            "TcDsHost",
            "Token",
        }:
            raise TdxRuntimeConfigurationError("tdx_sdk_config_template_invalid")
    except (OSError, UnicodeError, configparser.Error):
        raise TdxRuntimeConfigurationError("tdx_sdk_config_template_invalid") from None
    config.remove_section("Token")
    config.add_section("Token")
    config.set("Token", "token", settings.data_service_key)
    if settings.user:
        config.set("Token", "user", settings.user)

    # 必须由父进程持有上下文，SDK 崩溃或请求超时也会执行目录清理。
    with tempfile.TemporaryDirectory(prefix="karkinos-tdx-runtime-") as temporary:
        runtime = Path(temporary).resolve()
        runtime.chmod(0o700)
        for name in names:
            shutil.copyfile(source / name, runtime / name)
            (runtime / name).chmod(0o700)
        path = runtime / "TdxAiData.ini"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            config.write(output, space_around_delimiters=False)
        yield runtime / names[0]
