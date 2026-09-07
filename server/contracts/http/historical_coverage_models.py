"""Read-only daily historical price coverage contract."""

from typing import Literal

from pydantic import BaseModel, Field


class HistoricalCoverageItem(BaseModel):
    symbol: str
    instrument_type: str
    valuation_date: str
    requirement: Literal["required", "not_required", "unknown"]
    requirement_reason: str
    evidence_status: Literal["available", "missing", "unverified", "invalid"]
    evidence_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    calendar_evidence_ref: str | None = None
    gap_position: Literal["leading", "internal", "trailing"] | None = None


class HistoricalCoverageReport(BaseModel):
    rule_version: str = "historical-price-coverage-v1"
    range: Literal["all"] = "all"
    interval: Literal["daily"] = "daily"
    identity: dict[str, str | int]
    evidence_fingerprint: str
    calendar_evidence_refs: list[str]
    start_date: str | None
    end_date: str
    status: Literal["empty", "complete", "incomplete", "unknown"]
    confirmed_gap_dates: int
    confirmed_gap_instrument_dates: int
    unknown_requirement_instrument_dates: int
    unavailable_required_instrument_dates: int
    performance_blockers: list[str]
    # Only retained source observations and persisted publication incidents are read.
    conflict_scope: str = "retained_observations_and_publication_incidents"
    authorizes_execution: Literal[False] = False
    items: list[HistoricalCoverageItem]
