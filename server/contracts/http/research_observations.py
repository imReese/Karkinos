"""Explicit human commands for independent research target observations."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class StartResearchObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    source_backtest_result_id: int = Field(gt=0)
    horizon_sessions: int = Field(default=5, ge=1, le=60)
    max_symbol_weight: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    max_gross_weight: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    health_policy: dict[str, Any] | None = None


class AdvanceResearchObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0)
    dataset_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PauseResearchObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0)


class ConfigureResearchObservationAutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    expected_generation: UUID | None = None
