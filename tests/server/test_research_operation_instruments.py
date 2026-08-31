from __future__ import annotations

from copy import deepcopy

from server.services.research_operation_instruments import (
    build_research_operation_instruments,
)


class _BatchMetadataDb:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def get_instrument_metadata_batch_sync(self, symbols, asset_type="stock"):
        self.calls.append((list(symbols), asset_type))
        return [
            {
                "symbol": "000155",
                "asset_type": "stock",
                "display_name": "川能动力",
                "source": "stock_master",
                "fetched_at": "2026-08-28T16:00:00+08:00",
            },
            {
                "symbol": "600001",
                "asset_type": "stock",
                "display_name": "600001",
                "source": "fallback",
                "fetched_at": None,
            },
        ]


def _operation(symbol: str, operation: str) -> dict[str, str]:
    return {"symbol": symbol, "operation": operation}


def test_research_operation_names_are_one_bounded_persisted_batch_read() -> None:
    preview = {
        "status": "available",
        "operations": [
            _operation("600001", "exit_if_held_candidate"),
            _operation("000155", "buy_candidate"),
            _operation("301136", "buy_candidate"),
        ],
    }
    original = deepcopy(preview)
    db = _BatchMetadataDb()

    result = build_research_operation_instruments(db, preview)

    assert preview == original
    assert db.calls == [(["000155", "301136", "600001"], "stock")]
    assert result == {
        "schema_version": "karkinos.decision.research_operation_instruments.v1",
        "requested_count": 3,
        "lookup_count": 3,
        "resolved_count": 1,
        "items": [
            {
                "symbol": "000155",
                "display_name": "川能动力",
                "asset_class": "stock",
                "source": "stock_master",
                "fetched_at": "2026-08-28T16:00:00+08:00",
            }
        ],
        "missing_symbols": ["301136", "600001"],
        "lookup_truncated": False,
        "metadata_source": "persisted_instrument_metadata",
        "provider_contacted": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "authority_effect": "none",
    }


def test_research_operation_name_lookup_prioritizes_buys_and_caps_at_40() -> None:
    exits = [
        _operation(f"6{index:05d}", "exit_if_held_candidate")
        for index in range(45)
    ]
    preview = {
        "status": "available",
        "operations": exits + [_operation("000155", "buy_candidate")],
    }
    db = _BatchMetadataDb()

    result = build_research_operation_instruments(db, preview)

    assert len(db.calls) == 1
    assert len(db.calls[0][0]) == 40
    assert db.calls[0][0][0] == "000155"
    assert result["lookup_truncated"] is True
    assert result["requested_count"] == 46
    assert result["lookup_count"] == 40


def test_unavailable_research_preview_does_not_read_metadata() -> None:
    db = _BatchMetadataDb()

    result = build_research_operation_instruments(
        db,
        {"status": "unavailable", "operations": [_operation("000155", "buy_candidate")]},
    )

    assert db.calls == []
    assert result["requested_count"] == 0
    assert result["items"] == []
