"""Exchange candidates preserve typed history and require actual source content."""

import hashlib
import json
from dataclasses import replace

import pytest

from server.projections.instrument_exchange_evidence import (
    ExchangeSourceReference,
    InstrumentExchangeEvidenceRejected,
    build_instrument_exchange_targets,
    preview_instrument_exchange_evidence,
)
from tests.server.test_historical_coverage import _evidence, _snapshot, _trade


def _targets(*, kind="stock", rows=None, metadata=None):
    snapshot = _snapshot(rows if rows is not None else [_trade(1, kind=kind)])
    evidence = _evidence(
        snapshot,
        metadata=metadata
        or [
            dict(
                symbol="600001",
                asset_type=kind,
                display_name="Complete fixture name",
                exchange=None,
            )
        ],
    )
    return build_instrument_exchange_targets(snapshot, evidence)


def _record(**overrides):
    return dict(
        record_id="row-1",
        symbol="600001",
        instrument_type="stock",
        exchange="SSE",
        valid_from="2026-09-01",
        valid_to="2026-09-07",
        **overrides,
    )


def _source(records, *, ref="fixture", **extra):
    content = json.dumps(
        dict(
            schema_version="karkinos.instrument-exchange-source.v1",
            records=records,
            **extra,
        ),
        sort_keys=True,
    ).encode()
    reference = ExchangeSourceReference(
        content_ref=ref,
        source_locator=f"https://example.test/{ref}",
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
    return reference, content


def _preview(targets, *documents):
    return preview_instrument_exchange_evidence(
        targets,
        current_targets=targets,
        sources=tuple(ref for ref, _ in documents),
        source_contents={ref.content_ref: content for ref, content in documents},
    )


def test_complete_name_does_not_skip_exchange_unknown_or_mix_fund_rules():
    targets = _targets(rows=[_trade(1), _trade(1, kind="fund", symbol="FUND", id=2)])
    assert len(targets.targets) == 1
    assert targets.targets[0].instrument_key.storage_tuple() == ("600001", "stock")
    assert len(targets.targets[0].valuation_dates) == 7
    assert targets.targets[0].current_exchanges == (None,)


def test_closed_history_current_roster_and_partial_support_are_separate():
    targets = _targets(rows=[_trade(1), _trade(3, sell=True, id=2), _trade(7, id=3)])
    assert targets.targets[0].valuation_dates == (
        "2026-09-01",
        "2026-09-02",
        "2026-09-07",
    )
    source = _source([dict(_record(), valid_from="2026-09-07")])
    result = _preview(targets, source)
    assert result == _preview(targets, source)
    item = result.items[0]
    assert item.candidate_exchange == "SSE"
    assert item.record_matched_dates == ("2026-09-07",)
    assert item.record_unmatched_dates == ("2026-09-01", "2026-09-02")
    assert "source_date_coverage_incomplete" in item.blockers


def test_stock_record_cannot_support_same_symbol_etf():
    targets = _targets(kind="etf")
    result = _preview(targets, _source([_record()]))
    assert result.items[0].record_matched_dates == ()
    assert result.items[0].candidate_exchange is None
    assert "typed_source_record_missing" in result.items[0].blockers


def test_conflicting_material_keeps_original_records_and_blocks_dates():
    targets = _targets()
    result = _preview(
        targets,
        _source([_record()], ref="first"),
        _source([dict(_record(), exchange="SZSE")], ref="second"),
    )
    item = result.items[0]
    assert item.candidate_exchange is None
    assert item.record_matched_dates == ()
    assert "source_record_conflict" in item.blockers
    assert len(item.source_records) == 2


def test_unreadable_or_tampered_content_does_not_roll_expected_digest():
    targets = _targets()
    reference, content = _source([_record()])
    for bodies, reason in (
        ({}, "source_content_unavailable"),
        ({reference.content_ref: content + b" "}, "source_content_digest_mismatch"),
    ):
        result = preview_instrument_exchange_evidence(
            targets,
            current_targets=targets,
            sources=(reference,),
            source_contents=bodies,
        )
        assert reason in result.items[0].blockers
        assert result.items[0].candidate_exchange is None
        assert reference.content_sha256 == hashlib.sha256(content).hexdigest()


def test_caller_verified_flag_does_not_replace_content_contract():
    result = _preview(_targets(), _source([_record()], verified=True))
    assert "source_schema_invalid" in result.items[0].blockers
    assert result.items[0].candidate_exchange is None


@pytest.mark.parametrize(
    "extra", [{}, {"verified": True}, {"approved_by": "claimed reviewer"}]
)
def test_internally_consistent_material_and_official_url_never_grant_qualification(
    extra,
):
    reference, content = _source([_record()], **extra)
    reference = replace(
        reference, source_locator="https://www.sse.com.cn/claimed-official-material"
    )
    result = _preview(_targets(), (reference, content))
    item = result.items[0]
    assert item.status == "blocked"
    assert item.human_verification_status == "not_performed"
    assert item.verified_supported_dates == ()
    assert "source_authenticity_unverified" in item.blockers
    assert "human_review_required" in item.blockers
    assert result.authorizes_metadata_publication is False
    assert result.source_reviews[0].source == reference
    if not extra:
        assert item.candidate_exchange == "SSE"
        assert len(item.record_matched_dates) == 7


@pytest.mark.parametrize("symbol", ["600001.SH", "SH600001"])
def test_source_symbol_prefix_and_suffix_are_not_identity_proof(symbol):
    result = _preview(_targets(), _source([dict(_record(), symbol=symbol)]))
    assert result.items[0].candidate_exchange is None
    assert "typed_source_record_missing" in result.items[0].blockers


def test_record_locator_must_resolve_the_actual_typed_record():
    reference, content = _source(
        [dict(_record(), instrument_type="etf"), dict(_record(), record_id="stock-row")]
    )
    missing = replace(reference, record_locators=("/records/9",))
    assert (
        "source_record_locator_unavailable"
        in _preview(_targets(), (missing, content)).items[0].blockers
    )
    wrong = replace(reference, record_locators=("/records/0",))
    result = _preview(_targets(), (wrong, content))
    assert result.items[0].candidate_exchange is None
    assert "typed_source_record_missing" in result.items[0].blockers
    right = replace(reference, record_locators=("/records/1",))
    result = _preview(_targets(), (right, content))
    record = result.items[0].source_records[0]
    assert record.record_locator == "/records/1"
    assert json.loads(content)["records"][1]["record_id"] == record.record_id


def test_selecting_one_record_cannot_hide_a_known_conflict_in_the_same_material():
    reference, content = _source(
        [_record(), dict(_record(), record_id="conflict", exchange="SZSE")]
    )
    reference = replace(reference, record_locators=("/records/0",))
    result = _preview(_targets(), (reference, content))
    assert "source_record_conflict" in result.items[0].blockers
    assert result.items[0].record_matched_dates == ()
    assert len(result.source_reviews[0].records) == 2


def test_coverage_and_metadata_drift_are_rejected():
    targets = _targets()
    changed = _targets(
        metadata=[
            dict(
                symbol="600001",
                asset_type="stock",
                display_name="Changed fixture name",
                exchange=None,
            )
        ]
    )
    with pytest.raises(InstrumentExchangeEvidenceRejected, match="changed"):
        preview_instrument_exchange_evidence(
            targets, current_targets=changed, sources=(), source_contents={}
        )

    changed = replace(targets, coverage_evidence_fingerprint="changed")
    with pytest.raises(InstrumentExchangeEvidenceRejected, match="changed"):
        preview_instrument_exchange_evidence(
            targets, current_targets=changed, sources=(), source_contents={}
        )


def test_actual_bound_reader_does_not_write_fetch_or_reclassify_coverage(
    monkeypatch, tmp_path
):
    import socket
    from datetime import datetime

    from data.store import DataStore
    from server.persistence.instrument_metadata import InstrumentMetadataRepository
    from server.projections import historical_coverage_persistence as persistence
    from tests.server.test_historical_coverage_http import _checkpoint_bytes
    from tests.server.test_portfolio_endpoint_read_snapshot import _build_etf_state

    state = _build_etf_state(tmp_path)
    DataStore(tmp_path)
    evaluated_at = datetime.fromisoformat("2026-09-07T17:00:00+08:00")
    monkeypatch.setattr(persistence, "get_shanghai_now", lambda: evaluated_at)
    before = _checkpoint_bytes(tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("provider, initializer or metadata write called")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(state.db, "init_sync", fail)
    monkeypatch.setattr(InstrumentMetadataRepository, "upsert_metadata", fail)
    monkeypatch.setattr(InstrumentMetadataRepository, "upsert_metadata_batch", fail)
    original = persistence.read_historical_coverage(state)
    targets = persistence.read_instrument_exchange_targets(state)
    assert targets.coverage_evidence_fingerprint == original.evidence_fingerprint
    assert len(targets.targets) == 1
    source, content = _source([dict(_record(), symbol="510300", instrument_type="etf")])
    result = persistence.preview_instrument_exchange_from_state(
        state,
        expected_targets=targets,
        sources=(source,),
        source_contents={source.content_ref: content},
    )
    assert result.items[0].candidate_exchange == "SSE"
    assert result.database_writes_performed is False
    assert persistence.read_historical_coverage(state) == original
    assert before == {path: path.read_bytes() for path in before}


def test_reader_rejects_new_metadata_without_replacing_expected_identity(tmp_path):
    from data.store import DataStore
    from server.persistence.instrument_metadata import InstrumentMetadataRepository
    from server.projections import historical_coverage_persistence as persistence
    from tests.server.test_portfolio_endpoint_read_snapshot import _build_etf_state

    state = _build_etf_state(tmp_path)
    DataStore(tmp_path)
    targets = persistence.read_instrument_exchange_targets(state)
    expected = targets.coverage_evidence_fingerprint
    InstrumentMetadataRepository(state.db.path).upsert_metadata(
        symbol="510300", asset_type="etf", display_name="Changed complete fixture name"
    )
    with pytest.raises(InstrumentExchangeEvidenceRejected, match="changed"):
        persistence.preview_instrument_exchange_from_state(
            state, expected_targets=targets, sources=(), source_contents={}
        )
    assert targets.coverage_evidence_fingerprint == expected
