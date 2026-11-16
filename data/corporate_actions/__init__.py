"""A-Share Corporate Actions & Price Adjustment Engine.

Provides unified models, normalizers, mathematical factor calculations,
CAS persistence, and OHLCV price series adjustments.
"""

from data.corporate_actions.adjustment_engine import (
    CorporateActionAdjustmentEngine,
    compute_daily_alpha,
    compute_ex_reference_price,
)
from data.corporate_actions.factor_store import (
    deserialize_factor_series,
    load_factor_series,
    save_factor_series,
    serialize_factor_series,
)
from data.corporate_actions.models import (
    AdjustmentFactor,
    AdjustmentFactorSeries,
    CorporateActionEvent,
    CorporateActionType,
    PriceBasis,
)
from data.corporate_actions.normalization import (
    generate_event_id,
    normalize_facts_record,
    normalize_observation_evidence,
)
from data.corporate_actions.price_series import (
    adjust_ohlcv_dataframe,
    verify_ohlcv_invariants,
)

__all__ = [
    "CorporateActionAdjustmentEngine",
    "compute_daily_alpha",
    "compute_ex_reference_price",
    "deserialize_factor_series",
    "load_factor_series",
    "save_factor_series",
    "serialize_factor_series",
    "AdjustmentFactor",
    "AdjustmentFactorSeries",
    "CorporateActionEvent",
    "CorporateActionType",
    "PriceBasis",
    "generate_event_id",
    "normalize_facts_record",
    "normalize_observation_evidence",
    "adjust_ohlcv_dataframe",
    "verify_ohlcv_invariants",
]
