"""Contracts and Pydantic request models for manual trading endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ManualTicketRequest(BaseModel):
    actor: str | None = None


class ManualExecutionPreviewRequest(BaseModel):
    actor: str | None = None
    fill_price: str
    quantity: str
    fee: str | None = None
    tax: str | None = None
    transfer_fee: str | None = None


class ManualExecutionRecordRequest(ManualExecutionPreviewRequest):
    preview_fingerprint: str
    operator_note: str | None = None


__all__ = [
    "ManualExecutionPreviewRequest",
    "ManualExecutionRecordRequest",
    "ManualTicketRequest",
]
