from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from scripts.import_qmt_order_lifecycle import main as retired_main
from scripts.migrate_legacy_qmt_order_lifecycle import main as migrate_main


def _legacy_payload() -> dict:
    captured_at = datetime.now(UTC)
    return {
        "schema_version": "karkinos.qmt_order_lifecycle_export.v1",
        "provider": "qmt",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "legacy-qmt-fixture",
        "account_id": "private-legacy-fixture-account",
        "account_alias": "legacy-fixture-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": 1,
        "orders": [
            {
                "broker_order_id": "LEGACY-ORDER-1",
                "client_order_id": "KARK-legacy-client-order-1",
                "symbol": "600519",
                "side": "buy",
                "status": "open",
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": (captured_at - timedelta(seconds=2)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": [],
    }


def test_retired_import_entrypoint_refuses_implicit_legacy_ingestion(capsys) -> None:
    exit_code = retired_main([])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["blockers"] == ["legacy_qmt_import_entrypoint_retired"]
    assert output["qmt_runtime_supported"] is False
    assert output["provider_contacted"] is False


def test_explicit_legacy_migration_previews_canonical_contract(
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "legacy-qmt-lifecycle.json"
    source.write_text(json.dumps(_legacy_payload()), encoding="utf-8")
    db_path = tmp_path / "lifecycle.db"

    exit_code = migrate_main(["--file", str(source), "--db", str(db_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation_status"] == "pass"
    assert output["legacy_migration"]["compatibility_only"] is True
    assert output["legacy_migration"]["canonical_schema"] == (
        "karkinos.broker_order_lifecycle_export.v1"
    )
    assert output["legacy_migration"]["qmt_runtime_supported"] is False
    assert output["provider"] == "qmt"
    assert db_path.exists() is False
