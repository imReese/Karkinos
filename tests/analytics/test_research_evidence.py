import pytest

from analytics.research_evidence import build_research_evidence_bundle


def test_research_evidence_bundle_blocks_when_dataset_has_no_rows():
    bundle = build_research_evidence_bundle(
        metrics_json={
            "dataset_snapshot": {
                "schema_version": "karkinos.dataset_snapshot.v1",
                "snapshot_id": "sha256:blocked",
                "row_count": 0,
                "data_quality": {
                    "status": "warning",
                    "issues": [
                        {
                            "code": "no_rows",
                            "message": "No bars were available.",
                        }
                    ],
                },
                "symbol_universe": [],
            },
            "evidence_bundle": {
                "total_cost": 1.5,
                "fill_count": 1,
                "limitations": ["after-cost evidence is synthetic"],
            },
        },
        cost_summary_json={
            "total_commission": 1.0,
            "total_slippage": 0.5,
            "gross_turnover": 1000.0,
        },
        evidence_json={
            "total_cost": 1.5,
            "fill_count": 1,
            "limitations": ["after-cost evidence is synthetic"],
        },
        strategy_metadata={
            "strategy_id": "fixture_strategy",
            "name": "fixture_strategy",
            "display_name": "Fixture Strategy",
            "params": {"window": 5},
        },
    )

    assert bundle["schema_version"] == "karkinos.research_evidence.v1"
    assert bundle["bundle_id"].startswith("sha256:")
    assert bundle["gate_status"] == "blocked"
    assert bundle["dataset_snapshot_id"] == "sha256:blocked"
    assert bundle["promotion_gate"] == {
        "status": "blocked",
        "manual_confirmation_required": True,
        "does_not_enable_execution": True,
        "next_review": "Fix blocking evidence gaps before further review.",
    }

    analyzers = {item["name"]: item for item in bundle["analyzers"]}
    assert analyzers["data_quality"]["status"] == "blocked"
    assert analyzers["data_quality"]["details"]["row_count"] == 0
    assert analyzers["after_cost"]["status"] == "pass"
    assert analyzers["after_cost"]["details"]["total_cost"] == 1.5
    assert analyzers["oos"]["status"] == "pass"
    assert "T+1" in bundle["china_market_assumptions"]["known_gaps"][0]
    assert bundle["promotion_gate"]["does_not_enable_execution"] is True


def test_research_evidence_bundle_summarizes_rolling_oos_details():
    bundle = build_research_evidence_bundle(
        metrics_json={
            "dataset_snapshot": {
                "schema_version": "karkinos.dataset_snapshot.v1",
                "snapshot_id": "sha256:rolling",
                "row_count": 12,
                "data_quality": {"status": "ok", "issues": []},
                "symbol_universe": [{"symbol": "FIXTURE", "row_count": 12}],
            },
            "oos_validation": {
                "validation_mode": "rolling",
                "fold_count": 3,
                "validation_status": "benchmark_passed",
                "aggregate": {
                    "mean_out_of_sample_return": 0.032,
                    "worst_out_of_sample_return": -0.01,
                    "pass_rate": 0.67,
                    "total_oos_cost": 8.5,
                },
                "limitations": [
                    "Rolling OOS evidence does not refit parameters per fold."
                ],
            },
        },
        cost_summary_json={"total_trades": 2},
        evidence_json={"total_cost": 8.5, "fill_count": 2},
        strategy_metadata={
            "strategy_id": "fixture_strategy",
            "name": "fixture_strategy",
            "display_name": "Fixture Strategy",
            "params": {"window": 5},
        },
    )

    analyzers = {item["name"]: item for item in bundle["analyzers"]}
    assert analyzers["oos"]["status"] == "pass"
    assert analyzers["oos"]["details"] == {
        "oos_available": True,
        "validation_mode": "rolling",
        "validation_status": "benchmark_passed",
        "split_timestamp": None,
        "fold_count": 3,
        "aggregate": {
            "mean_out_of_sample_return": 0.032,
            "worst_out_of_sample_return": -0.01,
            "pass_rate": 0.67,
            "total_oos_cost": 8.5,
        },
    }
    assert bundle["evidence_references"]["oos_evidence_available"] is True


def _chronological_metrics(role):
    source = {
        "source_dataset_id": "sha256:immutable-source",
        "source_snapshot_id": "sha256:full-snapshot",
        "exploratory": True,
        "independent_final": False,
    }
    return {
        "dataset_snapshot": {
            "snapshot_id": source["source_snapshot_id"],
            "immutable_dataset_id": source["source_dataset_id"],
            "row_count": 10,
            "data_quality": {"status": "ok", "issues": []},
            "symbol_universe": [{"symbol": "600001", "row_count": 10}],
            "date_range": {"start": "2026-09-01", "end": "2026-09-14"},
        },
        "chronological_validation": {
            **source,
            "schema_version": "karkinos.chronological_sweep.v1",
            "role": role,
            "selection_basis": "training_only",
            "test_start_date": "2026-09-08",
        },
        "execution_window": {
            **source,
            "schema_version": "karkinos.backtest_execution_window.v1",
            "source_start_date": "2026-09-01",
            "source_end_date": "2026-09-14",
            "evaluation_start_date": "2026-09-01"
            if role == "training"
            else "2026-09-08",
            "metric_start_date": "2026-09-01" if role == "training" else "2026-09-08",
            "evaluation_end_date": "2026-09-07" if role == "training" else "2026-09-14",
            "metric_end_date": "2026-09-07" if role == "training" else "2026-09-14",
            "history_end_date": "2026-09-07" if role == "training" else "2026-09-14",
            "warmup_policy": "strategy_state_only_no_orders_or_book_carry",
            "independent_initial_cash": True,
        },
    }


def _chronological_bundle(metrics):
    return build_research_evidence_bundle(
        metrics_json=metrics,
        cost_summary_json={"total_trades": 1},
        evidence_json={"total_cost": 5, "fill_count": 1},
        strategy_metadata={"strategy_id": "dual_ma"},
    )


@pytest.mark.parametrize("role", ["training", "test"])
def test_chronological_evidence_reports_exploratory_role_without_upgrading_admission(
    role,
):
    bundle = _chronological_bundle(_chronological_metrics(role))

    oos = next(item for item in bundle["analyzers"] if item["name"] == "oos")
    assert oos["status"] == "degraded"
    assert oos["details"] == {
        "oos_available": role == "test",
        "required_for_current_run": True,
        "validation_mode": "chronological_train_select_test",
        "validation_status": "exploratory",
        "role": role,
        "split_timestamp": "2026-09-08",
        "independent_final": False,
    }
    if role == "training":
        assert "no heldout outcomes" in oos["summary"]
    else:
        assert "independent-book" in oos["summary"]
    assert bundle["evidence_references"]["oos_evidence_available"] is (role == "test")
    assert bundle["promotion_gate"]["status"] == "blocked"
    assert bundle["promotion_gate"]["does_not_enable_execution"] is True
    assert any("not a sealed" in item for item in oos["limitations"])


@pytest.mark.parametrize(
    "field, changes",
    [
        ("chronological_validation", None),
        ("execution_window", None),
        ("chronological_validation", {"schema_version": "unknown"}),
        ("chronological_validation", {"role": "final"}),
        ("chronological_validation", {"independent_final": True}),
        ("chronological_validation", {"test_start_date": "not-a-date"}),
        ("chronological_validation", {"role": "training"}),
        ("execution_window", {"metric_start_date": "2026-09-07"}),
        ("execution_window", {"source_snapshot_id": "sha256:different"}),
        ("execution_window", {"independent_initial_cash": False}),
        (
            "dataset_snapshot",
            {"date_range": {"start": "2026-09-08", "end": "2026-09-14"}},
        ),
    ],
)
def test_incomplete_chronological_metadata_is_unavailable_even_with_legacy_oos(
    field, changes
):
    metrics = _chronological_metrics("test")
    if changes is None:
        del metrics[field]
    else:
        metrics[field].update(changes)
    metrics["oos_validation"] = {"validation_status": "benchmark_passed"}

    bundle = _chronological_bundle(metrics)

    oos = next(item for item in bundle["analyzers"] if item["name"] == "oos")
    assert oos["status"] == "blocked"
    assert "incomplete or inconsistent" in oos["summary"]
    assert oos["details"]["validation_status"] == "unavailable"
    assert oos["details"]["oos_available"] is False
    assert bundle["evidence_references"]["oos_evidence_available"] is False
    assert bundle["promotion_gate"]["status"] == "blocked"


@pytest.mark.parametrize("legacy_receipt", [False, True])
def test_immutable_dataset_keeps_bar_quality_distinct_from_research_admission(
    legacy_receipt,
):
    admission = (
        {"market_data_binding": {"schema_version": "karkinos.market_data_binding.v1"}}
        if legacy_receipt
        else {
            "immutable_dataset_id": "sha256:dataset",
            "research_use": "exploratory_backtest",
        }
    )
    bundle = build_research_evidence_bundle(
        metrics_json={
            "dataset_snapshot": {
                "snapshot_id": "sha256:exploratory",
                **admission,
                "row_count": 5,
                "symbol_universe": [{"symbol": "600000", "row_count": 5}],
                "data_quality": {"status": "ok", "issues": []},
                "point_in_time_verified": False,
                "price_basis": "unadjusted",
                "cross_source_verified": False,
                "research_limitations": [
                    {
                        "code": "historical_availability_unverified",
                        "message": "Historical availability has not been verified.",
                    },
                    {
                        "code": "unadjusted_corporate_actions_unmodeled",
                        "message": "Corporate actions are not modeled in returns.",
                    },
                ],
            },
            "evidence_bundle": {"total_cost": 1, "fill_count": 1},
        },
        cost_summary_json={"total_commission": 1},
        evidence_json={},
        strategy_metadata={"strategy_id": "fixture_strategy"},
    )

    analyzers = {item["name"]: item for item in bundle["analyzers"]}
    assert analyzers["data_quality"]["status"] == "pass"
    assert analyzers["research_admission"]["status"] == "blocked"
    assert analyzers["research_admission"]["details"]["research_use"] == (
        "exploratory_backtest"
    )
    assert analyzers["research_admission"]["details"]["decision_availability"] == {
        "status": "not_evaluated"
    }
    assert bundle["promotion_gate"]["status"] == "blocked"
    assert "Historical availability has not been verified." in bundle["limitations"]
    assert "Corporate actions are not modeled in returns." in bundle["limitations"]
