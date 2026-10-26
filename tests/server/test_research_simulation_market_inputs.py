"""Current research previews consume bounded, newly replayed CAS evidence."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id
from core.types import InstrumentKey
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership
from data.dataset.reader import DailyBarDatasetReadResult
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.contracts.strategy_research import StrategyResearchSelection
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
    normalize_a_share_members,
)
from server.services.research.datasets import resolve_research_simulation_market_inputs
from server.services.strategy_scan.universe.evaluation import formula_history_rows
from tests.server.test_verified_interval_dataset import (
    STOCK,
    _calendar,
    _db,
    _verified_day,
)

DAYS = (date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21))


def _bind(source):
    source.pop("source_fingerprint", None)
    source["source_fingerprint"] = "sha256:" + content_fingerprint(source)
    return source


@pytest.fixture
def market_inputs(tmp_path, monkeypatch):
    root = tmp_path / "research"
    db = _db(tmp_path, trading_days=DAYS)
    objects = ContentAddressedObjectStore(root / "objects")
    refs = [_verified_day(root, day) for day in DAYS]
    snapshots = [read_daily_bar_dataset_manifest(objects, ref) for ref in refs]
    prefix = replace(
        snapshots[0],
        end_date=DAYS[1],
        cutoff=snapshots[1].cutoff,
        partitions=tuple(s.partitions[0] for s in snapshots[:2]),
    )
    prefix_ref = publish_daily_bar_dataset_manifest(objects, prefix)
    policy = MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=3)
    report = {
        "immutable_dataset_id": prefix_ref.dataset_id,
        "date_range": {"start": DAYS[0].isoformat(), "end": DAYS[1].isoformat()},
    }
    report["snapshot_id"] = backtest_dataset_snapshot_content_id(report)
    selection = StrategyResearchSelection(
        saved_backtest_result_id=183,
        universe=(STOCK.symbol,),
        asset_classes=("stock",),
        dataset_snapshot_id=report["snapshot_id"],
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[1].isoformat(),
        frequency="1d",
        initial_cash=1_000_000,
        deployment_scope=market_deployment_scope(policy),
        portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
    )
    field = {"op": "field", "name": "close"}
    source = _bind(
        {
            "status": "ready",
            "selection": selection.to_dict(),
            "dataset_snapshot": report,
            "formula_ast": {
                "schema_version": FORMULA_AST_CONTRACT,
                "entry": {
                    "op": "gt",
                    "left": field,
                    "right": {
                        "op": "lag",
                        "period": 1,
                        "input": {"op": "rolling_max", "window": 2, "input": field},
                    },
                },
                "exit": {
                    "op": "lt",
                    "left": field,
                    "right": {"op": "constant", "value": 0},
                },
                "position_size": {"op": "equal_weight"},
            },
        }
    )
    captured = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    store = DataStore(tmp_path)
    store.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol]),
        capture_started_at=captured,
        capture_completed_at=captured,
        source_metadata=[
            {
                "symbol": STOCK.symbol,
                "display_name": "合成公司",
                "list_status": "L",
                "list_date": "20100101",
            }
        ],
    )
    # Receipt-context fixtures are separate from prices: every price below still
    # replays real temporary revision/materialization/quality/verification CAS.
    monkeypatch.setattr(
        "data.research_market_data.resolve_daily_bar_receipts",
        lambda **_: [{"trade_date": day.isoformat()} for day in DAYS],
    )
    return SimpleNamespace(
        state=SimpleNamespace(
            db=db, config=None, ai_shadow_research_qualification_data_store=store
        ),
        source=source,
        session={
            "calendar_verified": True,
            "calendar_evidence_refs": ["fixture"],
            "latest_completed_trade_date": DAYS[-1].isoformat(),
            "next_trading_date": "2026-09-22",
            "market_date": "2026-09-21",
            "status": "after_close",
        },
        root=root,
        objects=objects,
        prefix_ref=prefix_ref,
        suffix_ref=refs[-1],
        snapshots=snapshots,
    )


def test_complete_suffix_composes_only_manifest_then_cold_reads_current_bytes(
    market_inputs,
):
    p = market_inputs
    before = p.objects.read_bytes(p.prefix_ref.manifest_ref)
    result = resolve_research_simulation_market_inputs(p.state, p.source, p.session)
    assert result["blockers"] == []
    values = result["kwargs"]
    read = values["verified_dataset_read"]
    assert isinstance(read, DailyBarDatasetReadResult)
    assert read.row_count == 3
    assert read.snapshot.start_date == DAYS[0] and read.snapshot.end_date == DAYS[-1]
    assert read.ref != p.prefix_ref
    assert read.snapshot.verification_bound
    assert all(
        not m.source_observation_ids and m.decision_at is None
        for m in read.snapshot.session_memberships
    )
    assert values["history_start"] == DAYS[0].isoformat()
    assert values["trading_dates"] == [day.isoformat() for day in DAYS]
    assert values["target_market_date"] == "2026-09-22"
    assert p.objects.read_bytes(p.prefix_ref.manifest_ref) == before
    assert not DatasetCatalog(p.root).contains(read.ref.dataset_id)
    # A later request must reopen raw evidence, not reuse a typed prior result.
    part = p.snapshots[-1].partitions[0]
    path = p.objects._path_for(part.materialization_id)
    path.chmod(0o644)
    path.write_bytes(b"corrupt")
    again = resolve_research_simulation_market_inputs(p.state, p.source, p.session)
    assert again["blockers"] == [
        "research_simulation_market_inputs_unreadable_or_invalid"
    ]
    assert again["kwargs"]["verified_dataset_read"] is None


def test_missing_latest_member_blocks_before_opening_giant_history(
    market_inputs, monkeypatch
):
    p = market_inputs
    source = deepcopy(p.source)
    instruments = (STOCK, InstrumentKey.from_values("600001", "stock"))
    prefix_parts = [
        read_daily_bar_dataset_manifest(
            p.objects, _verified_day(p.root, day, instruments=instruments)
        )
        for day in DAYS[:2]
    ]
    two_stock_prefix = publish_daily_bar_dataset_manifest(
        p.objects,
        replace(
            prefix_parts[0],
            end_date=DAYS[1],
            cutoff=prefix_parts[1].cutoff,
            partitions=tuple(s.partitions[0] for s in prefix_parts),
        ),
    )
    source["dataset_snapshot"]["immutable_dataset_id"] = two_stock_prefix.dataset_id
    source["dataset_snapshot"].pop("snapshot_id")
    source["dataset_snapshot"]["snapshot_id"] = backtest_dataset_snapshot_content_id(
        source["dataset_snapshot"]
    )
    source["selection"]["dataset_snapshot_id"] = source["dataset_snapshot"][
        "snapshot_id"
    ]
    source["selection"]["universe"].append("600001")
    source["selection"]["asset_classes"].append("stock")
    _bind(source)
    original = read_daily_bar_dataset_manifest
    opened = []

    def counted(store, ref):
        opened.append(ref.dataset_id)
        assert ref != two_stock_prefix
        return original(store, ref)

    monkeypatch.setattr(
        "server.services.research.datasets.read_daily_bar_dataset_manifest", counted
    )
    result = resolve_research_simulation_market_inputs(p.state, source, p.session)
    assert result["blockers"] == ["research_latest_cross_source_dataset_incomplete"]
    assert two_stock_prefix.dataset_id not in opened


def test_overlapping_different_verified_lineage_fails_without_picking_winner(
    market_inputs,
):
    p = market_inputs
    _verified_day(p.root, DAYS[-1], close="10.49")
    result = resolve_research_simulation_market_inputs(p.state, p.source, p.session)
    assert result["blockers"] == ["research_latest_cross_source_lineage_conflict"]
    assert result["kwargs"]["verified_dataset_read"] is None


def test_original_warmup_membership_observations_and_availability_remain_bound(
    market_inputs,
):
    p = market_inputs
    source = deepcopy(p.source)
    observed_at = datetime(2026, 9, 18, 7, tzinfo=timezone.utc)
    master = p.state.ai_shadow_research_qualification_data_store.save_market_universe_snapshot(
        trade_date=DAYS[1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol]),
        capture_started_at=observed_at,
        capture_completed_at=observed_at,
        source_metadata=[
            {
                "symbol": STOCK.symbol,
                "display_name": "合成公司",
                "list_status": "L",
                "list_date": "20100101",
            }
        ],
    )
    observation_id = bind_stock_master_observation(p.objects, master)
    memberships = tuple(
        DailyBarDatasetMembership(day, (STOCK,), observed_at, (observation_id,))
        for day in DAYS[:2]
    )
    prefix = read_daily_bar_dataset_manifest(p.objects, p.prefix_ref)
    prefix = replace(
        prefix,
        partitions=tuple(
            replace(part, instruments=(STOCK,)) for part in prefix.partitions
        ),
        session_memberships=memberships,
        universe_policy_id=source["selection"]["deployment_scope"][
            "deployment_scope_fingerprint"
        ],
    )
    ref = publish_daily_bar_dataset_manifest(p.objects, prefix)
    report = source["dataset_snapshot"]
    report["immutable_dataset_id"] = ref.dataset_id
    report.pop("snapshot_id")
    report["snapshot_id"] = backtest_dataset_snapshot_content_id(report)
    source["selection"]["dataset_snapshot_id"] = report["snapshot_id"]
    _bind(source)
    result = resolve_research_simulation_market_inputs(p.state, source, p.session)
    assert result["blockers"] == []
    actual = result["kwargs"]["verified_dataset_read"].snapshot.session_memberships
    assert actual[:2] == memberships
    assert not actual[-1].source_observation_ids and actual[-1].decision_at is None


def test_read_path_cannot_write_sql_or_create_an_account_artifact(
    market_inputs, monkeypatch
):
    p = market_inputs
    connect = sqlite3.connect
    writes = []

    def read_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)

        def authorize(operation, *details):
            if operation in {
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_CREATE_TABLE,
                sqlite3.SQLITE_ALTER_TABLE,
                sqlite3.SQLITE_DROP_TABLE,
            }:
                writes.append((operation, details[0]))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(sqlite3, "connect", read_connection)
    result = resolve_research_simulation_market_inputs(p.state, p.source, p.session)
    assert result["blockers"] == []
    assert writes == []


def test_explicit_recovery_source_keeps_its_policy_and_all_strict_cold_checks(
    market_inputs,
):
    p = market_inputs
    source = deepcopy(p.source)
    original = read_daily_bar_dataset_manifest(p.objects, p.prefix_ref)
    recovery_policy = "karkinos.dataset.gen7.explicit_history_recovery.v2:fixture"
    recovered = replace(original, resolver_policy_id=recovery_policy)
    ref = publish_daily_bar_dataset_manifest(p.objects, recovered)
    report = source["dataset_snapshot"]
    report["immutable_dataset_id"] = ref.dataset_id
    report.pop("snapshot_id")
    report["snapshot_id"] = backtest_dataset_snapshot_content_id(report)
    source["selection"]["dataset_snapshot_id"] = report["snapshot_id"]
    _bind(source)
    result = resolve_research_simulation_market_inputs(p.state, source, p.session)
    assert result["blockers"] == []
    read = result["kwargs"]["verified_dataset_read"]
    assert read.row_count == 3
    assert read.snapshot.resolver_policy_id == recovery_policy
    assert read.snapshot.verification_bound
    path = p.objects._path_for(original.partitions[0].materialization_id)
    path.chmod(0o644)
    path.write_bytes(b"corrupt")
    failed = resolve_research_simulation_market_inputs(p.state, source, p.session)
    assert failed["blockers"] == [
        "research_simulation_market_inputs_unreadable_or_invalid"
    ]
    assert failed["kwargs"]["verified_dataset_read"] is None


def test_canonical_managed_range_projection_preserves_each_days_availability(
    market_inputs,
    monkeypatch,
):
    p = market_inputs
    day22 = date(2026, 9, 22)
    last_ref = _verified_day(p.root, day22)
    latest = read_daily_bar_dataset_manifest(p.objects, last_ref)
    day21 = p.snapshots[-1]
    managed = replace(
        day21,
        end_date=day22,
        cutoff=latest.cutoff,
        partitions=tuple(
            replace(item.partitions[0], instruments=item.instruments)
            for item in (day21, latest)
        ),
        session_memberships=tuple(
            DailyBarDatasetMembership(item.start_date, item.instruments, item.cutoff)
            for item in (day21, latest)
        ),
        universe_policy_id="karkinos.dataset.verified_range_projection.v1",
    )
    managed_ref = publish_daily_bar_dataset_manifest(p.objects, managed)
    catalog = DatasetCatalog(p.root)
    catalog.register(p.objects, managed_ref)
    # Only the actual range-shaped Dataset is discoverable for these two days.
    # This changes the sanitized fixture catalog, never a runtime database.
    with sqlite3.connect(catalog.path) as connection:
        connection.executemany(
            "DELETE FROM dataset_catalog WHERE dataset_id = ?",
            [(p.suffix_ref.dataset_id,), (last_ref.dataset_id,)],
        )
    p.state.db.get_market_calendar_snapshot_sync = lambda **_: _calendar(
        trading_days=(*DAYS, day22)
    )
    captured = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    p.state.ai_shadow_research_qualification_data_store.save_market_universe_snapshot(
        trade_date=day22.isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members([STOCK.symbol]),
        capture_started_at=captured,
        capture_completed_at=captured,
        source_metadata=[
            {
                "symbol": STOCK.symbol,
                "display_name": "合成公司",
                "list_status": "L",
                "list_date": "20100101",
            }
        ],
    )
    monkeypatch.setattr(
        "data.research_market_data.resolve_daily_bar_receipts",
        lambda **_: [{"trade_date": day.isoformat()} for day in (*DAYS, day22)],
    )
    session = p.session | {
        "latest_completed_trade_date": day22.isoformat(),
        "next_trading_date": "2026-09-23",
    }
    result = resolve_research_simulation_market_inputs(p.state, p.source, session)
    assert result["blockers"] == []
    read = result["kwargs"]["verified_dataset_read"]
    assert read.row_count == 3
    actual = {item.partition_date: item for item in read.snapshot.session_memberships}
    assert actual[day21.start_date].available_at == day21.cutoff
    assert actual[day22].available_at == latest.cutoff
    assert actual[day21.start_date].available_at != actual[day22].available_at
    assert all(
        not item.source_observation_ids and item.decision_at is None
        for item in actual.values()
    )
    assert read.snapshot.partitions[-2:] == managed.partitions


@pytest.mark.parametrize(
    "member_change", ["source_observed", "decision_time", "other_policy"]
)
def test_observed_or_noncanonical_range_membership_is_never_erased(
    market_inputs,
    member_change,
):
    p = market_inputs
    snapshot = p.snapshots[-1]
    membership = DailyBarDatasetMembership(
        snapshot.start_date, snapshot.instruments, snapshot.cutoff
    )
    if member_change == "source_observed":
        master = p.state.ai_shadow_research_qualification_data_store.get_market_universe_snapshot(
            trade_date=snapshot.end_date.isoformat()
        )
        source_id = bind_stock_master_observation(p.objects, master)
        membership = replace(membership, source_observation_ids=(source_id,))
    elif member_change == "decision_time":
        membership = replace(membership, decision_at=snapshot.cutoff)
    candidate = replace(
        snapshot,
        partitions=tuple(
            replace(part, instruments=snapshot.instruments)
            for part in snapshot.partitions
        ),
        session_memberships=(membership,),
        universe_policy_id="other.actual.selection"
        if member_change == "other_policy"
        else "karkinos.dataset.verified_range_projection.v1",
    )
    ref = publish_daily_bar_dataset_manifest(p.objects, candidate)
    catalog = DatasetCatalog(p.root)
    catalog.register(p.objects, ref)
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "DELETE FROM dataset_catalog WHERE dataset_id = ?",
            (p.suffix_ref.dataset_id,),
        )
    result = resolve_research_simulation_market_inputs(p.state, p.source, p.session)
    assert result["blockers"] == ["research_latest_cross_source_dataset_incomplete"]
    assert result["kwargs"]["verified_dataset_read"] is None


@pytest.mark.parametrize("operator", ["ema", "rsi", "atr"])
def test_recursive_initialization_never_truncates_to_finite_warmup(
    market_inputs, operator
):
    p = market_inputs
    source = deepcopy(p.source)
    source["formula_ast"]["entry"]["right"] = {
        "op": operator,
        "window": 2,
        "input": {"op": "field", "name": "close"},
    }
    _bind(source)
    result = resolve_research_simulation_market_inputs(p.state, source, p.session)
    assert result["blockers"] == ["research_formula_recursive_warmup_unavailable"]


@pytest.mark.parametrize(
    "field,value,blocker",
    [
        (
            "source_fingerprint",
            "drift",
            "research_simulation_source_fingerprint_mismatch",
        ),
        ("status", "blocked", "research_simulation_source_not_ready"),
    ],
)
def test_untrusted_source_never_discovers_prices(market_inputs, field, value, blocker):
    p = market_inputs
    source = p.source | {field: value}
    assert resolve_research_simulation_market_inputs(p.state, source, p.session)[
        "blockers"
    ] == [blocker]


def test_c2_canonical_history_owner_counts_lagged_extrema():
    field = {"op": "field", "name": "close"}
    ast = {
        side: {
            "op": "lt",
            "left": field,
            "right": {
                "op": "lag",
                "period": 1,
                "input": {"op": op, "window": window, "input": field},
            },
        }
        for side, op, window in (
            ("entry", "rolling_max", 40),
            ("exit", "rolling_min", 20),
        )
    }
    assert formula_history_rows(ast) == 41


@pytest.mark.parametrize("listed", [None, "20100101", "20260918"])
def test_short_effective_bar_history_is_blocked_unless_original_master_proves_new_ipo(
    market_inputs,
    listed,
):
    p = market_inputs
    source = deepcopy(p.source)
    keys = (STOCK, InstrumentKey.from_values("600001", "stock"))
    first = p.snapshots[0]
    middle_ref = _verified_day(p.root, DAYS[1], instruments=keys)
    _verified_day(p.root, DAYS[2], instruments=keys)
    middle = read_daily_bar_dataset_manifest(p.objects, middle_ref)
    observed = datetime(2026, 9, 18, 7, tzinfo=timezone.utc)
    source_ids = ()
    if listed:
        master = p.state.ai_shadow_research_qualification_data_store.save_market_universe_snapshot(
            trade_date=DAYS[1].isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members([key.symbol for key in keys]),
            capture_started_at=observed,
            capture_completed_at=observed,
            source_metadata=[
                {
                    "symbol": key.symbol,
                    "display_name": "合成公司",
                    "list_status": "L",
                    "list_date": listed if key != STOCK else "20100101",
                }
                for key in keys
            ],
        )
        source_ids = (bind_stock_master_observation(p.objects, master),)
    memberships = tuple(
        DailyBarDatasetMembership(
            item.start_date,
            item.instruments,
            observed if listed else item.cutoff,
            source_ids,
        )
        for item in (first, middle)
    )
    prefix = replace(
        first,
        end_date=DAYS[1],
        cutoff=middle.cutoff,
        instruments=keys,
        partitions=tuple(
            replace(item.partitions[0], instruments=item.instruments)
            for item in (first, middle)
        ),
        session_memberships=memberships,
        universe_policy_id=source["selection"]["deployment_scope"][
            "deployment_scope_fingerprint"
        ],
    )
    ref = publish_daily_bar_dataset_manifest(p.objects, prefix)
    report = source["dataset_snapshot"]
    report["immutable_dataset_id"] = ref.dataset_id
    report.pop("snapshot_id")
    report["snapshot_id"] = backtest_dataset_snapshot_content_id(report)
    source["selection"]["dataset_snapshot_id"] = report["snapshot_id"]
    source["selection"]["universe"].append(keys[1].symbol)
    source["selection"]["asset_classes"].append("stock")
    _bind(source)
    catalog = DatasetCatalog(p.root)
    with sqlite3.connect(catalog.path) as connection:
        connection.execute(
            "DELETE FROM dataset_catalog WHERE dataset_id = ?",
            (p.suffix_ref.dataset_id,),
        )
    result = resolve_research_simulation_market_inputs(p.state, source, p.session)
    if listed == "20260918":
        assert result["blockers"] == []
    else:
        assert result["blockers"] == [
            "research_formula_effective_bar_warmup_incomplete"
        ]
    read = result["kwargs"]["verified_dataset_read"]
    assert sum(bar.instrument == keys[1] for bar in read.bars) == 2
