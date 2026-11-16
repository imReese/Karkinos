"""A-Share Corporate Actions & Price Adjustment Engine.

Provides unified models, normalizers, and event representations.
"""

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

__all__ = [
    "AdjustmentFactor",
    "AdjustmentFactorSeries",
    "CorporateActionEvent",
    "CorporateActionType",
    "PriceBasis",
    "generate_event_id",
    "normalize_facts_record",
    "normalize_observation_evidence",
]
