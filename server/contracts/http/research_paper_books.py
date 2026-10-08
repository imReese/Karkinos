"""Explicit commands for an isolated research paper book."""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from server.contracts.http.strategy_models import BacktestCostAssumptions


class StartResearchPaperBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    initial_cash: Decimal = Field(gt=0, allow_inf_nan=False)
    cost_assumptions: BacktestCostAssumptions | None = None
    corporate_action_mode: (
        Literal["price_only", "reported_distributions_gross"] | None
    ) = None
    health_policy: dict[str, Any] | None = None


class SettleResearchPaperBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0)
    dataset_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class PauseResearchPaperBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_version: int = Field(ge=0)
