"""Karkinos 核心类型定义。"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import NewType

# ---------- 唯一类型别名 ----------
Symbol = NewType("Symbol", str)  # 标的代码，如 "600519"
Money = NewType("Money", Decimal)  # 金额，全部用 Decimal


# ---------- 枚举 ----------
class AssetClass(Enum):
    """资产类别。"""

    STOCK = "stock"
    FUND = "fund"
    GOLD = "gold"
    BOND = "bond"
    INDEX = "index"


class InstrumentType(Enum):
    """Canonical instrument identity used by authoritative market facts.

    ``AssetClass.FUND`` remains a broad provider/portfolio grouping for backward
    compatibility.  It is not sufficient to identify how an instrument trades
    or how its market facts must be interpreted; ETF and open-end fund are
    deliberately separate here.
    """

    STOCK = "stock"
    ETF = "etf"
    OPEN_END_FUND = "open_end_fund"
    GOLD = "gold"
    BOND = "bond"
    INDEX = "index"
    UNKNOWN = "unknown"

    @classmethod
    def from_persisted(cls, value: object) -> "InstrumentType":
        """Parse a persisted identity without guessing from the symbol."""

        if isinstance(value, cls):
            return value
        persisted_value = getattr(value, "value", value)
        normalized = str(persisted_value or "").strip().lower().replace("-", "_")
        aliases = {
            "stock": cls.STOCK,
            "etf": cls.ETF,
            "fund": cls.OPEN_END_FUND,
            "open_end_fund": cls.OPEN_END_FUND,
            "openend_fund": cls.OPEN_END_FUND,
            "gold": cls.GOLD,
            "bond": cls.BOND,
            "index": cls.INDEX,
        }
        instrument_type = aliases.get(normalized)
        if instrument_type is None:
            raise ValueError(
                f"authoritative instrument type is unresolved: {normalized or 'missing'}"
            )
        return instrument_type


@dataclass(frozen=True, slots=True)
class InstrumentKey:
    """Exact persisted identity for one market instrument.

    Symbols are not globally unique across instrument namespaces.  Authoritative
    market facts therefore use this pair instead of passing a bare symbol or a
    broad ``AssetClass.FUND`` value between layers.
    """

    symbol: str
    instrument_type: InstrumentType

    def __post_init__(self) -> None:
        normalized_symbol = str(self.symbol).strip()
        if not normalized_symbol:
            raise ValueError("instrument symbol is missing")
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError("instrument_type must be InstrumentType")
        if self.instrument_type is InstrumentType.UNKNOWN:
            raise ValueError("authoritative instrument type is unresolved")
        object.__setattr__(self, "symbol", normalized_symbol)

    @classmethod
    def from_values(
        cls,
        symbol: object,
        instrument_type: object,
    ) -> "InstrumentKey":
        parsed_type = (
            instrument_type
            if isinstance(instrument_type, InstrumentType)
            else InstrumentType.from_persisted(instrument_type)
        )
        return cls(str(symbol), parsed_type)

    def storage_tuple(self) -> tuple[str, str]:
        return self.symbol, self.instrument_type.value


class BarFrequency(Enum):
    """K 线频率。"""

    TICK = "tick"
    MIN_1 = "1m"
    MIN_5 = "5m"
    DAILY = "1d"
    WEEKLY = "1w"


class OrderSide(Enum):
    """买卖方向。"""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型。"""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(Enum):
    """订单状态。"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Settlement(Enum):
    """结算规则。"""

    T_PLUS_0 = "T+0"
    T_PLUS_1 = "T+1"


class CommissionType(Enum):
    """佣金类型。"""

    STOCK_A = "stock_a"
    FUND_ETF = "fund_etf"
    FUND_OPENEND = "fund_openend"
    GOLD_SPOT = "gold_spot"
    BOND_EXCHANGE = "bond_exchange"


# ---------- 常量 ----------
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

# A股佣金率默认
DEFAULT_STOCK_COMMISSION_RATE = Decimal("0.0003")  # 万三
MIN_STOCK_COMMISSION = Decimal("5")  # 最低 5 元
STAMP_TAX_RATE = Decimal("0.0005")  # 印花税 卖出万五
TRANSFER_FEE_RATE = Decimal("0.00001")  # 过户费 万一

# ETF
DEFAULT_ETF_COMMISSION_RATE = Decimal("0.0003")
MIN_ETF_COMMISSION = Decimal("5")

# 黄金
GOLD_SPOT_COMMISSION_RATE = Decimal("0.0008")  # ~0.08%

# 债券
BOND_COMMISSION_RATE = Decimal("0.00004")  # 万0.4
MIN_BOND_COMMISSION = Decimal("1")

# 涨跌幅
MAIN_BOARD_LIMIT_PCT = Decimal("0.10")  # 主板 ±10%
GEM_LIMIT_PCT = Decimal("0.20")  # 创业板/科创板 ±20%
