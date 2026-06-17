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
