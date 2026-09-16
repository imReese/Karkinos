"""把固定 Dataset 转成现有回测引擎的输入，不接触远程数据源或 Serving。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.handler import DataHandler
from data.storage.objects import ContentAddressedObjectStore
from domain.instrument import make_etf, make_stock
from server.services.research_datasets import (
    ResearchDatasetError,
    require_supported_snapshot,
)


def load_dataset_backtest_inputs(root: Path, request):
    store = ContentAddressedObjectStore(root / "objects")
    try:
        ref = DatasetRef(store.resolve_ref(request.dataset_id))
        restored = read_daily_bar_dataset(store, ref)
    except Exception:
        raise ResearchDatasetError("dataset_unreadable_no_remote_fallback") from None
    snapshot = restored.snapshot
    require_supported_snapshot(snapshot)
    try:
        dates = (
            date.fromisoformat(request.start_date),
            date.fromisoformat(request.end_date),
        )
    except (TypeError, ValueError):
        raise ResearchDatasetError("dataset_request_date_invalid") from None
    if dates != (snapshot.start_date, snapshot.end_date):
        raise ResearchDatasetError("dataset_request_date_mismatch")
    # 第一条正式消费链只接股票和 ETF，不能用代码启发式混淆身份。
    if any(
        item.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
        for item in snapshot.instruments
    ):
        raise ResearchDatasetError("dataset_instrument_type_unsupported")
    if len({item.symbol for item in snapshot.instruments}) != len(snapshot.instruments):
        raise ResearchDatasetError("dataset_engine_symbol_collision")
    if request.assets:
        try:
            requested = tuple(
                sorted(
                    (
                        InstrumentKey(
                            item["symbol"],
                            InstrumentType(
                                item.get("instrument_type") or item["asset_class"]
                            ),
                        )
                        for item in request.assets
                    ),
                    key=lambda item: (item.instrument_type.value, item.symbol),
                )
            )
        except (ValueError, KeyError, TypeError):
            raise ResearchDatasetError("dataset_request_instrument_invalid") from None
        if requested != snapshot.instruments:
            raise ResearchDatasetError("dataset_request_universe_mismatch")
    instruments, handlers = {}, {}
    for key in snapshot.instruments:
        symbol = Symbol(key.symbol)
        factory = (
            make_stock if key.instrument_type is InstrumentType.STOCK else make_etf
        )
        instruments[symbol] = factory(key.symbol, key.symbol)
        frame = pd.DataFrame(
            [
                {
                    "timestamp": bar.event_time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "amount": bar.amount,
                    "available_at": bar.available_at,
                    "captured_at": bar.captured_at,
                }
                for bar in restored.bars
                if bar.instrument == key
            ]
        )
        if frame.empty:
            raise ResearchDatasetError("dataset_instrument_has_no_rows")
        frame.attrs.update(
            provider_name="tdx",
            data_source="tdx",
            adjustment_mode="none",
            dataset_id=ref.dataset_id,
        )
        handlers[symbol] = DataHandler(
            frame,
            symbol,
            asset_class=instruments[symbol].asset_class,
            instrument_type=key.instrument_type,
        )
    binding = {
        "dataset_id": ref.dataset_id,
        "cutoff": snapshot.cutoff.isoformat(),
        "price_basis": "unadjusted",
        "offline_replay": True,
        "point_in_time_verified": False,
        "limitations": [
            "Historical backfill is a frozen research snapshot, not proof of historical availability.",
            "Unadjusted prices do not model corporate-action cash flows or total returns.",
        ],
    }
    return instruments, handlers, binding
