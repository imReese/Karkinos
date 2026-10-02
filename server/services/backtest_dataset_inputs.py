"""把固定 Dataset 转成现有回测引擎的输入，不接触远程数据源或 Serving。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.handler import DataHandler
from data.market.verification_evidence import read_market_verification_evidence
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
        decision_availability = _decision_availability_summary(store, restored)
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
    source_names = sorted({partition.provider for partition in snapshot.partitions})
    single_source = source_names[0] if len(source_names) == 1 else None
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
            provider_name=single_source,
            data_source=single_source,
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
        "source_names": source_names,
        "cross_source_verified": snapshot.verification_bound,
        "offline_replay": True,
        "point_in_time_verified": False,
        "decision_availability": decision_availability,
        "limitations": [
            "Historical backfill is a frozen research snapshot, not proof of historical availability.",
            "Unadjusted prices do not model corporate-action cash flows or total returns.",
        ],
        **(
            {"corporate_action_evidence": restored.corporate_action_evidence}
            if restored.corporate_action_evidence is not None
            else {}
        ),
    }
    return instruments, handlers, binding


def _decision_availability_summary(store, restored) -> dict:
    """Audit information at the snapshot's modeled bar-close decision time.

    A later simulated fill does not make information available at this earlier
    decision time. Keep this input audit separate from execution timing.
    """
    verification_times = {}
    for partition in restored.snapshot.partitions:
        if partition.verification_id is not None:
            verification = read_market_verification_evidence(
                store, store.resolve_ref(partition.verification_id)
            )
            verification_times[partition.partition_date] = verification.checked_at

    late_bar_count = 0
    late_verification_count = 0
    first_late_bar = None
    first_late_verification = None
    for bar in restored.bars:
        decision_at = bar.event_time
        if bar.available_at > decision_at:
            late_bar_count += 1
            if first_late_bar is None:
                first_late_bar = {
                    "instrument_type": bar.instrument.instrument_type.value,
                    "symbol": bar.instrument.symbol,
                    "session_date": bar.session_date.isoformat(),
                    "decision_at": decision_at.isoformat(),
                    "available_at": bar.available_at.isoformat(),
                }
        checked_at = verification_times.get(bar.session_date)
        if checked_at is not None and checked_at > decision_at:
            late_verification_count += 1
            if first_late_verification is None:
                first_late_verification = {
                    "instrument_type": bar.instrument.instrument_type.value,
                    "symbol": bar.instrument.symbol,
                    "session_date": bar.session_date.isoformat(),
                    "decision_at": decision_at.isoformat(),
                    "checked_at": checked_at.isoformat(),
                }

    return {
        "schema_version": "karkinos.dataset_decision_availability.v1",
        "decision_time_basis": "bar_event_time",
        "covers": "bound_bar_and_verification_availability_at_replay_event_time",
        "does_not_validate": [
            "execution_timing",
            "historical_universe",
            "corporate_action_returns",
        ],
        "status": "blocked" if late_bar_count or late_verification_count else "pass",
        "checked_bar_count": len(restored.bars),
        "late_bar_count": late_bar_count,
        "late_verification_count": late_verification_count,
        "first_late_bar": first_late_bar,
        "first_late_verification": first_late_verification,
    }
