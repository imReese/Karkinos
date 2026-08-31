"""Shared HTTP payloads for human review of external AI analyses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExternalAnalysisQualityRubricPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_grounding: int = Field(ge=1, le=5)
    contradiction_handling: int = Field(ge=1, le=5)
    uncertainty_calibration: int = Field(ge=1, le=5)
    decision_usefulness: int = Field(ge=1, le=5)


class ProviderPricingSnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3)
    prompt_price_per_million_tokens: str = Field(min_length=1, max_length=64)
    completion_price_per_million_tokens: str = Field(
        min_length=1,
        max_length=64,
    )
    source: str = Field(min_length=1, max_length=500)
    effective_at: str = Field(min_length=1, max_length=128)
