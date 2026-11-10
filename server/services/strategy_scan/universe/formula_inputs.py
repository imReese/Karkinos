"""Read exact formula inputs from a promoted final's immutable Dataset lineage."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import read_daily_bar_dataset_manifest
from data.dataset.model import DatasetRef
from data.dataset.reader import (
    dataset_cross_section_memberships,
    read_daily_bar_dataset,
)
from data.storage.objects import ContentAddressedObjectStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import formula_uses_exact_close_ratio
from server.ai_runtime.formula_portfolio import FormulaCrossSectionInputs
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_master_buy_instruments,
)
from server.services.research.research_observation_inputs import (
    read_research_observation_dataset,
    require_observation_dataset_prefix,
)


def load_exact_formula_market_inputs(
    db, promoted, *, market_date, decision_at, saved_bindings=None
):
    """Discover once, then reopen the exact saved ref; never reconstruct floats.

    The already verified promotion supplies the final anchor. Catalog metadata
    only rejects irrelevant candidates; the strict Reader and existing prefix,
    calendar, availability and full-scope owners decide whether inputs are usable.
    """
    frames, contexts, bindings, blockers = {}, {}, {}, []
    for item in promoted:
        ast = (item.get("strategy") or {}).get("formula_ast") or {}
        if not formula_uses_exact_close_ratio(ast):
            continue
        strategy_id = str(item["strategy_id"])
        try:
            anchor = item["formula_dataset_anchor"]
            scope = anchor["deployment_scope"]
            if anchor["formula_fingerprint"] != "sha256:" + content_fingerprint(ast):
                raise ValueError("formula_dataset_anchor_formula_changed")
            cutoff = decision_at
            saved = (saved_bindings or {}).get(strategy_id)
            if saved_bindings is not None:
                if (
                    not saved
                    or saved["anchor"] != anchor
                    or saved["market_date"] != market_date
                ):
                    raise ValueError("formula_dataset_saved_binding_changed")
                cutoff = datetime.fromisoformat(saved["as_of"])
            if cutoff is None or cutoff.utcoffset() is None or cutoff > decision_at:
                raise ValueError("formula_dataset_decision_clock_invalid")
            root = Path(db.path).resolve().parent / "research"
            objects = ContentAddressedObjectStore(root / "objects")
            original = read_daily_bar_dataset(
                objects, DatasetRef(objects.resolve_ref(anchor["dataset_id"]))
            )
            start = original.snapshot.start_date
            if (
                start.isoformat() != item["history_start"]
                or original.snapshot.universe_policy_id
                != scope["deployment_scope_fingerprint"]
                or not original.snapshot.verification_bound
                or set(item["strategy"]["selected_universe"])
                - {key.symbol for key in original.snapshot.instruments}
            ):
                raise ValueError("formula_dataset_anchor_scope_changed")
            source = {
                "forward_input": {
                    "dataset_id": anchor["dataset_id"],
                    "start_date": start.isoformat(),
                    "end_date": original.snapshot.end_date.isoformat(),
                },
                "source_selection": {
                    "portfolio_policy_id": scope["portfolio_policy_id"],
                    "deployment_scope": scope,
                },
            }
            if saved is not None:
                identity = saved["dataset_id"]
            else:
                identity = None
                entries = DatasetCatalog(root).list_daily_bar_datasets(
                    start_date=start,
                    end_date=date.fromisoformat(market_date),
                    cutoff_lte=cutoff,
                    resolver_policy_id=original.snapshot.resolver_policy_id,
                )
                for entry in entries:
                    if (
                        entry.start_date != start
                        or entry.end_date.isoformat() != market_date
                    ):
                        continue
                    candidate = read_daily_bar_dataset_manifest(objects, entry.ref)
                    if (
                        candidate.universe_policy_id
                        != scope["deployment_scope_fingerprint"]
                    ):
                        continue
                    # First deterministic matching scope must verify. Corruption
                    # or incompatible history is a blocker, never a fallback.
                    identity = entry.ref.dataset_id
                    break
                if identity is None:
                    raise ValueError("formula_dataset_complete_prefix_unavailable")
            calendar = [
                row
                for year in range(start.year, decision_at.year + 2)
                if (
                    row := db.get_market_calendar_snapshot_sync(
                        exchange="SSE", year=year
                    )
                )
                is not None
            ]
            result = read_research_observation_dataset(
                objects,
                identity,
                instruments=original.snapshot.instruments,
                start_date=start,
                now=cutoff,
                calendar_rows=calendar,
                minimum_bars=int(scope["universe_policy"]["minimum_history_rows"]),
                deployment_scope=scope,
                membership_after=original.snapshot.end_date + timedelta(days=1),
            )
            if result.snapshot.end_date.isoformat() != market_date:
                raise ValueError("formula_dataset_market_date_changed")
            require_observation_dataset_prefix(
                objects, source, result.snapshot, verified_source=original
            )
            policy = MarketUniversePolicy.from_dict(scope["universe_policy"])
            for membership in result.snapshot.session_memberships:
                if membership.partition_date < original.snapshot.end_date:
                    continue
                expected = []
                for identity_ref in membership.source_observation_ids:
                    master = json.loads(objects.read_bytes_by_id(identity_ref))
                    expected.append(set(market_master_buy_instruments(master, policy)))
                if (
                    not expected
                    or any(members != expected[0] for members in expected)
                    or set(membership.instruments) != expected[0]
                ):
                    raise ValueError("formula_dataset_full_scope_members_missing")
            context = formula_dataset_cross_section(
                objects,
                result.snapshot,
                minimum_history_rows=policy.minimum_history_rows,
                as_of=cutoff,
            )
            binding = {
                "anchor": anchor,
                "dataset_id": result.ref.dataset_id,
                "market_date": market_date,
                "as_of": cutoff.isoformat(),
            }
            if saved is not None and binding != saved:
                raise ValueError("formula_dataset_saved_binding_changed")
            frames[strategy_id] = exact_formula_frames(result)
            contexts[strategy_id] = context
            bindings[strategy_id] = binding
        except (
            KeyError,
            LookupError,
            OSError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            blockers.append(
                "strategy_cross_section_inputs:"
                + json.dumps(strategy_id, ensure_ascii=False)
                + f":exact_dataset:{type(exc).__name__}:{exc}"
            )
    return frames, contexts, bindings, blockers


def formula_dataset_cross_section(objects, snapshot, *, minimum_history_rows, as_of):
    memberships = dataset_cross_section_memberships(objects, snapshot, as_of=as_of)
    return FormulaCrossSectionInputs(
        declared_symbols=tuple(key.symbol for key in snapshot.instruments),
        session_memberships={
            day: tuple(key.symbol for key in members)
            for day, members in memberships.items()
        },
        minimum_history_rows=minimum_history_rows,
        as_of=as_of,
    )


def exact_formula_frames(result):
    """Preserve native decimal observations and both availability clocks for formula evaluation."""
    rows = {}
    for bar in result.bars:
        rows.setdefault(bar.instrument.symbol, []).append(
            {
                "timestamp": bar.event_time,
                "available_at": bar.available_at,
                "captured_at": bar.captured_at,
                **{
                    name: getattr(bar, name)
                    for name in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                    )
                },
            }
        )
    return {symbol: pd.DataFrame(values) for symbol, values in rows.items()}
