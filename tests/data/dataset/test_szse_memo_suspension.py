"""Real manifest/cold path binds alias PDF separately for every membership."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import (
    DatasetReaderIntegrityError,
    dataset_session_nontrading_instruments,
    read_daily_bar_dataset,
)
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from tests.data.providers.test_szse_memo_suspension import (
    AT,
    IDENTITY_TEXT,
    KEY,
    NEW,
    capture,
    identity,
    row,
)
from tests.server.test_verified_interval_dataset import _side

DAYS = (date(2020, 1, 14), date(2020, 1, 15), date(2020, 1, 16))
OTHER = InstrumentKey("300001", InstrumentType.STOCK)


def inputs(tmp_path, monkeypatch, *, alias=True, unknown=False, ambiguous=False):
    rows = [row("2020-01-15 开市", "2020-01-17 开市", "1天")]
    if unknown:
        rows = [row("2020-01-15 开市", period="未知")]
    objects, cap = capture(tmp_path, rows)
    target = NEW if alias else KEY
    keys = (target, OTHER, *((KEY,) if ambiguous else ()))
    master_at = AT - timedelta(days=1)
    master = objects.put_bytes(
        json.dumps(
            {
                "schema_version": "karkinos.market_universe_snapshot.v2",
                "trade_date": "2026-10-16",
                "membership_basis": "current_active_stock_master",
                "availability_basis": "capture_completed_at",
                "observation_basis": "adapter_response",
                "capture_started_at": master_at.isoformat(),
                "capture_completed_at": master_at.isoformat(),
                "available_at": master_at.isoformat(),
                "members": [{"symbol": k.symbol} for k in keys],
            }
        ).encode()
    )
    proof = (
        identity(
            objects,
            monkeypatch,
            started_at=AT + timedelta(seconds=1),
            completed_at=AT + timedelta(seconds=2),
        )
        if alias
        else None
    )
    available = proof.completed_at if proof else cap.completed_at
    sources = (
        master.object_id,
        cap.capture_id,
        *((proof.capture_id,) if proof else ()),
    )

    def traded_on(day):
        return keys if unknown or day == DAYS[0] else (OTHER,)

    partitions = []
    for day in DAYS:
        revision, materialization, _ = _side(
            objects, day, TDX_PROVIDER_DESCRIPTOR, instruments=traded_on(day)
        )
        partitions.append(
            DailyBarDatasetPartition(
                day,
                revision.provider,
                revision.ref.revision_id,
                materialization.materialization_id,
                instruments=traded_on(day),
            )
        )
    snapshot = DailyBarDatasetSnapshot(
        start_date=DAYS[0],
        end_date=DAYS[-1],
        cutoff=available,
        instruments=keys,
        resolver_policy_id="fixture.exploratory.v1",
        market_schema_version=revision.market_schema_version,
        partitions=tuple(partitions),
        session_memberships=tuple(
            DailyBarDatasetMembership(day, traded_on(day), available, sources)
            for day in DAYS
        ),
        universe_policy_id="fixture.current_survivor_ipo_minus_explicit_halt.v1",
    )
    return objects, snapshot, master, cap, proof


def cold(objects, snapshot):
    return read_daily_bar_dataset(
        objects, publish_daily_bar_dataset_manifest(objects, snapshot)
    )


def test_real_manifest_cold_alias_keeps_all_sources_and_uses_max_actual_availability(
    tmp_path, monkeypatch
):
    objects, snapshot, master, cap, proof = inputs(tmp_path, monkeypatch)
    before = [
        objects.read_bytes(x)
        for x in (master, cap.raw_object_ref, proof.raw_object_ref)
    ]
    restored = cold(objects, snapshot)
    assert restored.row_count == 4 and set(restored.snapshot.instruments) == {
        NEW,
        OTHER,
    }
    assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {
        d: (NEW,) for d in DAYS[1:]
    }
    assert restored.snapshot.membership_evidence_bound is False
    for membership in restored.snapshot.session_memberships:
        assert membership.available_at == proof.completed_at > cap.completed_at
        assert set(membership.source_observation_ids) == {
            master.object_id,
            cap.capture_id,
            proof.capture_id,
        }
    assert [
        objects.read_bytes(x)
        for x in (master, cap.raw_object_ref, proof.raw_object_ref)
    ] == before
    assert json.loads(cap.request_json)["params"]["txtDmorjc"] == KEY.symbol


def test_alias_first_day_cache_cannot_authorize_second_membership_missing_PDF(
    tmp_path, monkeypatch
):
    objects, snapshot, master, cap, _ = inputs(tmp_path, monkeypatch)
    last = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, cap.capture_id),
        available_at=cap.completed_at,
    )
    snapshot = replace(
        snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        cold(objects, snapshot)
    assert str(error.value.__cause__) == "szse_memo_consumer_identity_unbound"


def test_shared_master_header_is_verified_and_decoded_once_per_validation(
    tmp_path, monkeypatch
):
    objects, snapshot, master, _, _ = inputs(tmp_path, monkeypatch)
    snapshot = replace(
        snapshot,
        end_date=DAYS[1],
        partitions=snapshot.partitions[:2],
        session_memberships=snapshot.session_memberships[:2],
    )
    master_raw = objects.read_bytes(master)
    counts = Counter()
    original_read = objects.read_bytes
    original_resolve = objects.resolve_ref
    original_loads = json.loads

    def read(ref):
        if ref.object_id == master.object_id:
            counts["master_read"] += 1
        return original_read(ref)

    def resolve(identity):
        if identity == master.object_id:
            counts["master_resolve"] += 1
        return original_resolve(identity)

    def loads(raw, *args, **kwargs):
        if raw == master_raw:
            counts["master_decode"] += 1
        return original_loads(raw, *args, **kwargs)

    monkeypatch.setattr(objects, "read_bytes", read)
    monkeypatch.setattr(objects, "resolve_ref", resolve)
    monkeypatch.setattr(json, "loads", loads)
    for invocation in (1, 2):
        assert dataset_session_nontrading_instruments(objects, snapshot) == {
            DAYS[1]: (NEW,)
        }
        assert counts == {
            "master_read": invocation,
            "master_resolve": invocation,
            "master_decode": invocation,
        }

    path = objects.root / "sha256" / master.digest[:2] / master.digest[2:]
    path.chmod(0o600)
    path.write_bytes(b"tampered fixture master")
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        dataset_session_nontrading_instruments(objects, snapshot)


def test_later_membership_replacing_identity_cannot_reuse_prior_alias(
    tmp_path, monkeypatch
):
    objects, snapshot, master, cap, proof = inputs(tmp_path, monkeypatch)
    original_pdf = objects.read_bytes(proof.raw_object_ref)
    unrelated_pdf = b"%PDF-unrelated sanitized identity fixture"
    unrelated_text = IDENTITY_TEXT.replace("300000", "300777").replace(
        "302000", "302777"
    )
    unrelated = identity(
        objects,
        monkeypatch,
        unrelated_text,
        raw_payload=unrelated_pdf,
        started_at=proof.started_at,
        completed_at=proof.completed_at,
    )
    texts = {original_pdf: IDENTITY_TEXT, unrelated_pdf: unrelated_text}
    monkeypatch.setattr(
        "pypdf.PdfReader",
        lambda raw: SimpleNamespace(
            is_encrypted=False,
            pages=[SimpleNamespace(extract_text=lambda: texts[raw.getvalue()])],
        ),
    )
    last = replace(
        snapshot.session_memberships[-1],
        source_observation_ids=(master.object_id, cap.capture_id, unrelated.capture_id),
    )
    snapshot = replace(
        snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        cold(objects, snapshot)
    assert str(error.value.__cause__) == "szse_memo_consumer_identity_unbound"


@pytest.mark.parametrize(
    "case", ["availability_ignores_PDF", "missing_master", "after_cutoff", "decision"]
)
def test_actual_PDF_is_neither_master_nor_status_and_time_fences_remain(
    tmp_path, monkeypatch, case
):
    objects, snapshot, master, cap, proof = inputs(tmp_path, monkeypatch)
    last = snapshot.session_memberships[-1]
    with pytest.raises((DatasetReaderIntegrityError, ValueError)):
        if case == "availability_ignores_PDF":
            last = replace(last, available_at=cap.completed_at)
        elif case == "missing_master":
            last = replace(
                last, source_observation_ids=(cap.capture_id, proof.capture_id)
            )
        elif case == "decision":
            last = replace(last, decision_at=proof.completed_at)
        else:
            snapshot = replace(snapshot, cutoff=cap.completed_at)
        snapshot = replace(
            snapshot, session_memberships=(*snapshot.session_memberships[:-1], last)
        )
        cold(objects, snapshot)


def test_old_and_new_keys_simultaneously_in_frozen_roster_are_ambiguous(
    tmp_path, monkeypatch
):
    objects, snapshot, _, _, _ = inputs(tmp_path, monkeypatch, ambiguous=True)
    # Evidence-only public entry still receives the frozen full roster and must
    # reject ambiguity before any proposed full-day-halt projection is trusted.
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        dataset_session_nontrading_instruments(objects, snapshot)
    assert str(error.value.__cause__) == "szse_memo_alias_selection_ambiguous"


def test_real_manifest_unknown_source_cannot_be_hidden_by_other_zero_capture(
    tmp_path, monkeypatch
):
    objects, snapshot, master, cap, _ = inputs(tmp_path, monkeypatch, alias=False)
    _, uncertain = capture(tmp_path, [row("2020-01-15 开市", period="未知")])
    snapshot = replace(
        snapshot,
        session_memberships=tuple(
            replace(
                m,
                source_observation_ids=(
                    master.object_id,
                    cap.capture_id,
                    uncertain.capture_id,
                ),
            )
            for m in snapshot.session_memberships
        ),
    )
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        cold(objects, snapshot)
    assert str(error.value.__cause__) == "historical_status_sources_conflict"


def test_unknown_alone_does_not_synthesize_nontrading_or_active_state(
    tmp_path, monkeypatch
):
    objects, snapshot, _, _, _ = inputs(
        tmp_path, monkeypatch, alias=False, unknown=True
    )
    restored = cold(objects, snapshot)
    assert restored.row_count == 6
    assert dataset_session_nontrading_instruments(objects, restored.snapshot) == {}


@pytest.mark.parametrize(
    "extra",
    [
        "公司股票并未于2025年2月17日开市起启用变更后的证券简称及证券代码。",
        "公司法人主体已发生实质变化。",
        "投资者持有股份的证券类别和持有数量与代码变更完成前不一致。",
    ],
)
def test_independent_identity_counterexamples_fail_actual_manifest_cold(
    tmp_path, monkeypatch, extra
):
    objects, snapshot, master, cap, proof = inputs(tmp_path, monkeypatch)
    bad = identity(
        objects,
        monkeypatch,
        IDENTITY_TEXT + extra,
        started_at=proof.started_at,
        completed_at=proof.completed_at,
    )
    # The raw PDF bytes in this pure parser fixture are fixed sanitized bytes;
    # the mocked extractor is the only subject-controlled text, as in the
    # independent v1 exploit. Real native PDF is separately replayed unchanged.
    assert bad.capture_id == proof.capture_id
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        cold(objects, snapshot)
    assert "statement_unsupported" in str(error.value.__cause__)


@pytest.mark.parametrize(
    "before,after",
    [
        ("证券代码。", "证券代码，但实际未启用。"),
        ("实质变化。", "实质变化，但实际已经变化。"),
    ],
)
def test_independent_same_sentence_suffix_counterexamples_fail_full_Dataset_cold(
    tmp_path, monkeypatch, before, after
):
    objects, snapshot, _, _, proof = inputs(tmp_path, monkeypatch)
    bad = identity(
        objects,
        monkeypatch,
        IDENTITY_TEXT.replace(before, after),
        started_at=proof.started_at,
        completed_at=proof.completed_at,
    )
    assert bad.capture_id == proof.capture_id
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ) as error:
        cold(objects, snapshot)
    assert str(error.value.__cause__) == "szse_security_identity_statement_unsupported"
