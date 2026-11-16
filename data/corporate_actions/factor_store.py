"""CAS persistence and serialization for adjustment factor series.

Schema: karkinos.adjustment_factors.v1
Immutable and content-addressed via ContentAddressedObjectStore.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from core.types import Symbol
from data.corporate_actions.models import (
    AdjustmentFactor,
    AdjustmentFactorSeries,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
    ObjectStoreError,
)

SCHEMA_VERSION = "karkinos.adjustment_factors.v1"


def serialize_factor_series(series: AdjustmentFactorSeries) -> dict[str, Any]:
    """Serialize AdjustmentFactorSeries to a deterministic JSON-compatible dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": str(series.symbol),
        "cutoff_date": series.cutoff_date.isoformat(),
        "factor_count": len(series.factors),
        "factors": [
            {
                "trade_date": f.trade_date.isoformat(),
                "pre_close": str(f.pre_close) if f.pre_close is not None else None,
                "ex_price": str(f.ex_price) if f.ex_price is not None else None,
                "alpha": str(f.alpha),
                "qfq_factor": str(f.qfq_factor),
                "hfq_factor": str(f.hfq_factor),
                "volume_factor": str(f.volume_factor),
                "event_ids": list(f.event_ids),
            }
            for f in series.factors
        ],
    }


def deserialize_factor_series(
    payload: Mapping[str, Any],
    manifest_id: str = "",
) -> AdjustmentFactorSeries:
    """Deserialize JSON mapping to an immutable AdjustmentFactorSeries."""
    schema = payload.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise ValueError(f"unsupported_factor_series_schema: {schema}")

    sym = Symbol(str(payload["symbol"]))
    cutoff = date.fromisoformat(payload["cutoff_date"])

    factors: list[AdjustmentFactor] = []
    for row in payload.get("factors", []):
        factors.append(
            AdjustmentFactor(
                trade_date=date.fromisoformat(row["trade_date"]),
                pre_close=Decimal(row["pre_close"])
                if row.get("pre_close") is not None
                else None,
                ex_price=Decimal(row["ex_price"])
                if row.get("ex_price") is not None
                else None,
                alpha=Decimal(row["alpha"]),
                qfq_factor=Decimal(row["qfq_factor"]),
                hfq_factor=Decimal(row["hfq_factor"]),
                volume_factor=Decimal(row["volume_factor"]),
                event_ids=tuple(row.get("event_ids", ())),
            )
        )

    return AdjustmentFactorSeries(
        symbol=sym,
        cutoff_date=cutoff,
        factors=tuple(factors),
        manifest_id=manifest_id,
    )


def save_factor_series(
    store: ContentAddressedObjectStore,
    series: AdjustmentFactorSeries,
) -> ObjectRef:
    """Persist factor series to CAS storage and return immutable ObjectRef."""
    payload = serialize_factor_series(series)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ref = store.put_bytes(raw)
    return ref


def load_factor_series(
    store: ContentAddressedObjectStore,
    ref: ObjectRef,
) -> AdjustmentFactorSeries:
    """Retrieve and deserialize factor series from CAS storage by ObjectRef."""
    try:
        raw = store.read_bytes(ref)
        payload = json.loads(raw.decode("utf-8"))
        return deserialize_factor_series(payload, manifest_id=ref.object_id)
    except (KeyError, ValueError, ObjectStoreError) as exc:
        raise ValueError(f"factor_series_unreadable: {ref.object_id}") from exc
