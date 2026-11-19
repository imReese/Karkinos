"""Admit immutable research Datasets and prepare their engine inputs offline."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from core.types import InstrumentKey, InstrumentType, Symbol
from data.dataset.model import DatasetRef
from data.dataset.reader import (
    read_daily_bar_dataset,
    read_dataset_membership_evidence,
)
from data.handler import DataHandler
from data.market.verification_evidence import read_market_verification_evidence
from data.storage.objects import ContentAddressedObjectStore
from domain.instrument import make_etf, make_stock
from server.contracts.http.strategy_models import BacktestRequest
from server.services.research.dataset_policy import (
    ResearchDatasetError,
    require_supported_snapshot,
)


def parse_is_st(val: Any) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int) and val in (0, 1):
        return bool(val)
    if isinstance(val, str):
        s = val.strip()
        if s == "1":
            return True
        if s == "0":
            return False
        if s.lower() in ("true", "yes"):
            return True
        if s.lower() in ("false", "no"):
            return False
        return None
    return None


def compute_execution_context_id(payload: dict[str, Any]) -> tuple[str, str]:
    canonical_dict = {
        k: v
        for k, v in payload.items()
        if k not in ("execution_context_id", "content_hash")
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, ensure_ascii=False)
    content_hash = (
        f"sha256:{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()}"
    )
    return f"ctx-{content_hash}", content_hash


def _resolve_trading_calendar_payload(
    snapshot,
    request,
    db,
    strict_status: bool,
) -> dict[str, Any] | None:
    calendar_snapshots = []
    years_needed = list(range(snapshot.start_date.year, snapshot.end_date.year + 1))
    if db is not None and hasattr(db, "get_market_calendar_snapshot_sync"):
        for y in years_needed:
            row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=y)
            if row is not None:
                from data.market_calendar import (
                    market_calendar_snapshot_from_payload,
                )

                calendar_snapshots.append(market_calendar_snapshot_from_payload(row))
    elif hasattr(request, "trading_calendar") and request.trading_calendar is not None:
        tc = request.trading_calendar
        if hasattr(tc, "snapshots"):
            calendar_snapshots.extend(tc.snapshots)
        elif hasattr(tc, "year"):
            calendar_snapshots.append(tc)

    if calendar_snapshots:
        covered_years = {s.year for s in calendar_snapshots}
        if set(years_needed) <= covered_years:
            if len(calendar_snapshots) == 1:
                return calendar_snapshots[0].to_payload()
            from data.market_calendar import MultiYearMarketCalendar

            multi_cal = MultiYearMarketCalendar(tuple(calendar_snapshots))
            return {
                "schema_version": "karkinos.market_calendar.multi_year.v1",
                "source_fingerprint": multi_cal.source_fingerprint,
                "snapshots": [s.to_payload() for s in multi_cal.snapshots],
            }
        if strict_status:
            raise ResearchDatasetError("dataset_calendar_coverage_incomplete")
    elif strict_status:
        raise ResearchDatasetError("dataset_calendar_evidence_unverified")
    return None


def _resolve_security_status_and_nontrading(
    store,
    snapshot,
    strict_status: bool,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]] | None]:
    from data.dataset.reader import dataset_session_nontrading_instruments

    nontrading_map_iso: dict[str, list[str]] = {}
    try:
        raw_nontrading = dataset_session_nontrading_instruments(store, snapshot)
        for s_date, keys in raw_nontrading.items():
            nontrading_map_iso[s_date.isoformat()] = [k.symbol for k in keys]
    except Exception as exc:
        if strict_status:
            raise ResearchDatasetError(
                f"dataset_nontrading_evidence_unreadable:{exc}"
            ) from exc

    security_status_payload = None
    if getattr(snapshot, "session_memberships", ()):
        evidence: dict[
            date,
            tuple[
                tuple[dict[str, Any], ...],
                dict[InstrumentKey, str],
                dict[InstrumentKey, str],
            ],
        ] = {}
        try:
            nontrading_evidence = read_dataset_membership_evidence(
                store, snapshot, cross_section_evidence=evidence
            )
        except Exception as exc:
            if strict_status:
                raise ResearchDatasetError(
                    f"dataset_security_status_evidence_unreadable:{exc}"
                ) from exc
            evidence = {}
            nontrading_evidence = {}

        if evidence:
            sec_status_map: dict[str, dict[str, Any]] = {}
            for s_date, (
                masters,
                hist_status,
                special_treatment,
            ) in evidence.items():
                s_date_str = s_date.isoformat()
                day_map: dict[str, Any] = {}
                session_meta_by_sym: dict[str, dict[str, Any]] = {}
                static_meta_by_sym: dict[str, dict[str, Any]] = {}
                src_caps: list[str] = []
                for master in masters:
                    if master.get("source_capture_ids"):
                        src_caps.extend(master["source_capture_ids"])
                    master_date = master.get("trade_date")
                    if master_date is not None:
                        master_date = str(master_date).strip()
                    for m in master.get("member_metadata", ()):
                        sym = str(m.get("symbol") or "")
                        if not sym:
                            continue
                        if sym not in static_meta_by_sym:
                            static_meta_by_sym[sym] = m
                        m_sess = m.get("status_session_date")
                        effective_date = (
                            str(m_sess).strip() if m_sess is not None else master_date
                        )
                        if (
                            effective_date == s_date_str
                            and sym not in session_meta_by_sym
                        ):
                            session_meta_by_sym[sym] = m

                for inst_key in snapshot.instruments:
                    sym = inst_key.symbol
                    session_meta = session_meta_by_sym.get(sym)
                    static_meta = session_meta or static_meta_by_sym.get(sym)

                    # A1: Verified trading status for s_date:
                    is_susp = (
                        inst_key in nontrading_evidence.get(s_date, ())
                        or hist_status.get(inst_key) == "0"
                        or (
                            session_meta is not None
                            and session_meta.get("trade_status") == "0"
                        )
                    )
                    trade_status: str | None = None
                    if is_susp:
                        trade_status = "0"
                    elif hist_status.get(inst_key) == "1":
                        trade_status = "1"
                    elif (
                        session_meta is not None
                        and session_meta.get("trade_status") == "1"
                    ):
                        trade_status = "1"

                    # A2 & A3: Parse ST status preserving True/False/None 3-state
                    is_st: bool | None = None
                    if inst_key in special_treatment:
                        is_st = parse_is_st(special_treatment[inst_key])
                    elif session_meta is not None and "is_st" in session_meta:
                        is_st = parse_is_st(session_meta.get("is_st"))

                    list_date = static_meta.get("list_date") if static_meta else None
                    delist_date = (
                        static_meta.get("delist_date") if static_meta else None
                    )
                    disp_name = static_meta.get("display_name") if static_meta else None
                    src_ref = src_caps[0] if src_caps else None

                    day_map[sym] = {
                        "trade_status": trade_status,
                        "is_suspended": is_susp if trade_status is not None else None,
                        "is_st": is_st,
                        "listing_date": list_date,
                        "delist_date": delist_date,
                        "display_name": disp_name,
                        "source_ref": src_ref,
                    }
                if day_map:
                    sec_status_map[s_date_str] = day_map
            if sec_status_map:
                security_status_payload = sec_status_map
    elif strict_status:
        raise ResearchDatasetError("dataset_security_status_evidence_missing")

    return nontrading_map_iso, security_status_payload


def load_dataset_backtest_inputs(root: Path, request, db=None):
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
    bars_by_instrument = {}
    for bar in restored.bars:
        bars_by_instrument.setdefault(bar.instrument, []).append(bar)
    instruments, handlers = {}, {}
    price_basis = getattr(request, "price_basis", "unadjusted") or "unadjusted"
    if price_basis not in {"unadjusted", "forward", "backward", "point_in_time"}:
        raise ResearchDatasetError("dataset_request_price_basis_unsupported")

    events = []
    if price_basis != "unadjusted" and restored.corporate_action_evidence:
        from data.corporate_actions.normalization import normalize_observation_evidence

        events = normalize_observation_evidence(restored.corporate_action_evidence)

    for key in snapshot.instruments:
        symbol = Symbol(key.symbol)
        factory = (
            make_stock if key.instrument_type is InstrumentType.STOCK else make_etf
        )
        instruments[symbol] = factory(key.symbol, key.symbol)
        instrument_bars = bars_by_instrument.get(key, ())
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
                for bar in instrument_bars
            ]
        )
        if frame.empty:
            raise ResearchDatasetError("dataset_instrument_has_no_rows")

        adjustment_mode = "none"
        if price_basis != "unadjusted" and events:
            from data.corporate_actions.adjustment_engine import (
                CorporateActionAdjustmentEngine,
            )
            from data.corporate_actions.models import PriceBasis
            from data.corporate_actions.price_series import adjust_ohlcv_dataframe

            basis_enum = PriceBasis(price_basis)
            trading_dates = [b.session_date for b in instrument_bars]
            closing_prices = [b.close for b in instrument_bars]
            as_of = snapshot.cutoff if basis_enum == PriceBasis.POINT_IN_TIME else None
            factor_series = CorporateActionAdjustmentEngine.calculate_factors(
                key.symbol,
                trading_dates,
                closing_prices,
                events,
                cutoff_date=snapshot.cutoff.date(),
                as_of_time=as_of,
            )
            frame = adjust_ohlcv_dataframe(frame, factor_series, basis=basis_enum)
            adjustment_mode = price_basis

        frame.attrs.update(
            provider_name=single_source,
            data_source=single_source,
            adjustment_mode=adjustment_mode,
            dataset_id=ref.dataset_id,
        )
        handlers[symbol] = DataHandler(
            frame,
            symbol,
            asset_class=instruments[symbol].asset_class,
            instrument_type=key.instrument_type,
        )

    from data.dataset.reader import dataset_session_nontrading_instruments

    req_ctx_id = getattr(request, "execution_context_id", None)
    if req_ctx_id is not None and str(req_ctx_id).strip():
        req_ctx_id_str = str(req_ctx_id).strip()
        obj_id = req_ctx_id_str.removeprefix("ctx-")
        try:
            pinned_ref = store.resolve_ref(obj_id)
        except Exception as exc:
            raise ResearchDatasetError(
                f"execution_context_not_found:{req_ctx_id_str}"
            ) from exc
        try:
            pinned_bytes = store.read_bytes(pinned_ref)
        except Exception as exc:
            raise ResearchDatasetError(
                f"execution_context_unreadable:{req_ctx_id_str}"
            ) from exc
        try:
            pinned_context_payload = json.loads(pinned_bytes.decode("utf-8"))
        except Exception as exc:
            raise ResearchDatasetError(
                f"execution_context_corrupted:{req_ctx_id_str}"
            ) from exc

        if pinned_context_payload is None or not isinstance(
            pinned_context_payload, dict
        ):
            raise ResearchDatasetError(
                f"execution_context_invalid_payload:{req_ctx_id_str}"
            )

        ctx_id, c_hash = compute_execution_context_id(pinned_context_payload)
        if req_ctx_id_str not in (ctx_id, c_hash):
            raise ResearchDatasetError(
                f"execution_context_content_hash_mismatch:expected_{req_ctx_id_str}_got_{ctx_id}"
            )
        pinned_dataset_id = pinned_context_payload.get("dataset_id")
        if not pinned_dataset_id or not isinstance(pinned_dataset_id, str):
            raise ResearchDatasetError(
                f"execution_context_dataset_unverified:missing_dataset_scope_{req_ctx_id_str}"
            )
        if pinned_dataset_id != ref.dataset_id:
            raise ResearchDatasetError(
                f"execution_context_dataset_incompatible:context_for_{pinned_dataset_id}_cannot_apply_to_{ref.dataset_id}"
            )
        ctx_strict = bool(pinned_context_payload.get("strict_security_status", False))
        req_strict = getattr(request, "strict_security_status", None)
        if req_strict is not None and req_strict != ctx_strict:
            raise ResearchDatasetError(
                f"execution_context_strict_mode_conflict:request_{req_strict}_vs_context_{ctx_strict}"
            )
        strict_status = ctx_strict
        trading_calendar_payload = pinned_context_payload.get("trading_calendar")
        security_status_payload = pinned_context_payload.get("security_status")
        nontrading_map_iso = pinned_context_payload.get("nontrading_instruments") or {}
        execution_context_payload = dict(pinned_context_payload)
        execution_context_payload["execution_context_id"] = ctx_id
        execution_context_payload["content_hash"] = c_hash
    else:
        req_strict = getattr(request, "strict_security_status", None)
        strict_status = bool(req_strict)
        trading_calendar_payload = _resolve_trading_calendar_payload(
            snapshot, request, db, strict_status
        )
        (
            nontrading_map_iso,
            security_status_payload,
        ) = _resolve_security_status_and_nontrading(store, snapshot, strict_status)

        research_mode = "strict_research" if strict_status else "exploratory_compatible"
        execution_context_payload = {
            "dataset_id": ref.dataset_id,
            "trading_calendar": trading_calendar_payload,
            "nontrading_instruments": nontrading_map_iso
            if nontrading_map_iso
            else None,
            "security_status": security_status_payload,
            "strict_security_status": strict_status,
            "research_mode": research_mode,
            "limitations": [
                (
                    "Strict research mode: unverified security status, missing status evidence, or unclassified instruments block trading."
                    if strict_status
                    else "Exploratory mode: unverified status evidence defaults to ordinary session permissions."
                ),
            ],
        }

        ctx_id, c_hash = compute_execution_context_id(execution_context_payload)
        canonical_dict = {
            k: v
            for k, v in execution_context_payload.items()
            if k not in ("execution_context_id", "content_hash")
        }
        raw_ctx_bytes = json.dumps(
            canonical_dict, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        try:
            store.put_bytes(raw_ctx_bytes)
            execution_context_payload["execution_context_id"] = ctx_id
            execution_context_payload["content_hash"] = c_hash
        except Exception as exc:
            raise ResearchDatasetError(
                f"execution_context_persistence_failed:{exc}"
            ) from exc

    research_mode = "strict_research" if strict_status else "exploratory_compatible"
    ctx_id = execution_context_payload.get("execution_context_id")
    binding = {
        "dataset_id": ref.dataset_id,
        "execution_context_id": ctx_id,
        "cutoff": snapshot.cutoff.isoformat(),
        "price_basis": price_basis,
        "source_names": source_names,
        "cross_source_verified": snapshot.verification_bound,
        "offline_replay": True,
        "point_in_time_verified": False,
        "decision_availability": decision_availability,
        "trading_rule_policy_id": "karkinos.a_share.trading_rules.v1",
        "strict_security_status": strict_status,
        "research_mode": research_mode,
        "execution_context": execution_context_payload,
        **(
            {"nontrading_instruments": nontrading_map_iso} if nontrading_map_iso else {}
        ),
        "limitations": [
            "Historical backfill is a frozen research snapshot, not proof of historical availability.",
            "Unadjusted prices do not model corporate-action cash flows or total returns."
            if price_basis == "unadjusted"
            else f"Adjusted price basis '{price_basis}' normalizes corporate actions for signals, but trades execute on unadjusted prices.",
            *execution_context_payload["limitations"],
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
            for instrument in partition.instruments or restored.snapshot.instruments:
                verification_times[(partition.partition_date, instrument)] = (
                    verification.checked_at
                )

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
        checked_at = verification_times.get((bar.session_date, bar.instrument))
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


def prepare_dataset_backtest_inputs(
    request: BacktestRequest, db=None
) -> tuple[dict, dict, dict, dict]:
    """Read and bind one full immutable source for repeated sequential runs."""
    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from server.runtime_paths import resolve_data_dir

    if not request.dataset_id:
        raise ResearchDatasetError("backtest_execution_window_dataset_required")
    root = (
        db.path.resolve().parent
        if db is not None
        else Path(resolve_data_dir()).resolve()
    ) / "research"
    instruments, handlers, binding = load_dataset_backtest_inputs(root, request, db=db)
    sources = binding["source_names"]
    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source=sources[0] if len(sources) == 1 else None,
        data_handlers=handlers,
        store=None,
        source_names=sources,
        research_dataset_binding=binding,
    )
    return instruments, handlers, binding, snapshot
