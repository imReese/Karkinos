"""Native input indexes preserve cell validation and raw integrity boundaries."""

import copy
import json
from dataclasses import fields, replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from data.market import reconciliation as candidate
from data.market.capture import read_provider_capture
from data.storage.objects import ContentAddressedObjectStore
from tests.data.market import test_tencent_tushare_reported_amount as legacy


def prepared(tmp_path, provider="tushare", mutate=None):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    tx, tu = legacy._payloads()
    payload = tx if provider == "akshare_tencent" else tu
    bar = legacy._bar("100000" if provider == "akshare_tencent" else "100046")
    if mutate:
        mutate(payload)
    revision, materialization = legacy._publish(store, provider, payload, bar)
    return store, materialization, bar


@pytest.mark.parametrize("provider", ["tushare", "akshare_tencent"])
def test_reuses_index_but_replays_each_selected_cell_and_new_scope(
    tmp_path, monkeypatch, provider
):
    store, mat, bar = prepared(tmp_path, provider)
    counts = dict(index=0, capture=0, raw=0, adapter=0)
    for name, label in [
        ("_tencent_tushare_native_index", "index"),
        ("read_provider_capture", "capture"),
        ("read_provider_raw_payload", "raw"),
    ]:
        original = getattr(candidate, name)

        def wrapped(*a, _original=original, _label=label, **kw):
            counts[_label] += 1
            return _original(*a, **kw)

        monkeypatch.setattr(candidate, name, wrapped)
    from data.providers import tencent, tushare

    adapter = tencent if provider == "akshare_tencent" else tushare
    original = adapter._rows_from_records

    def wrapped(*a, **kw):
        counts["adapter"] += 1
        return original(*a, **kw)

    monkeypatch.setattr(adapter, "_rows_from_records", wrapped)
    with candidate.tencent_tushare_native_read_scope():
        cache = candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()
        for _ in range(2):
            candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert counts == dict(index=1, capture=2, raw=2, adapter=2)
        assert len(cache) == 1
        entry = next(iter(cache.values()))
        with pytest.raises(TypeError):
            entry[0]["schema"] = "forged"
        with pytest.raises(TypeError):
            entry[2][legacy.INSTRUMENT.symbol][("fake", legacy.SESSION)] = ()
        with pytest.raises(ValueError, match="evidence_invalid"):
            candidate._validate_tencent_tushare_reported_amount(
                store, mat, (replace(bar, amount=bar.amount + 1),)
            )
        assert cache == {}
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert counts["index"] == 2
    assert cache == {}
    assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() is None
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert counts["index"] == 3


@pytest.mark.parametrize("provider", ["tushare", "akshare_tencent"])
def test_native_records_avoid_dataframe_and_keep_every_raw_and_capture_hash(
    tmp_path, monkeypatch, provider
):
    import pandas as pd

    from data.storage import objects

    store, mat, bar = prepared(tmp_path, provider)
    capture = read_provider_capture(store, mat.capture_ref)
    counts = {capture.capture_id: 0, capture.raw_object_ref.object_id: 0}
    original = objects.object_id_from_bytes

    def counted_hash(raw):
        identity = original(raw)
        if identity in counts:
            counts[identity] += 1
        return identity

    monkeypatch.setattr(objects, "object_id_from_bytes", counted_hash)
    monkeypatch.setattr(
        pd,
        "DataFrame",
        lambda *a, **kw: pytest.fail(
            "Native record replay must not construct DataFrame"
        ),
    )
    with candidate.tencent_tushare_native_read_scope():
        for _ in range(2):
            candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert counts == {capture.capture_id: 2, capture.raw_object_ref.object_id: 2}
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
    assert counts == {capture.capture_id: 3, capture.raw_object_ref.object_id: 3}


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", Decimal("10.01")),
        ("volume", Decimal(123457)),
        ("event_time", legacy.CAPTURED),
        ("available_at", legacy.EVENT),
        ("captured_at", legacy.EVENT),
        ("suspended", True),
    ],
)
def test_warm_entry_does_not_accept_changed_selected_bar(tmp_path, field, value):
    store, mat, bar = prepared(tmp_path)
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        with pytest.raises(ValueError, match="evidence_invalid"):
            candidate._validate_tencent_tushare_reported_amount(
                store,
                mat,
                (
                    SimpleNamespace(
                        **(
                            {item.name: getattr(bar, item.name) for item in fields(bar)}
                            | {field: value}
                        )
                    ),
                ),
            )
        assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}


@pytest.mark.parametrize("part", ["raw", "capture"])
def test_warm_entry_still_hashes_actual_bytes_and_clears_on_integrity_failure(
    tmp_path, part
):
    store, mat, bar = prepared(tmp_path)
    capture = read_provider_capture(store, mat.capture_ref)
    ref = capture.raw_object_ref if part == "raw" else capture.capture_ref
    path = store._path_for(ref.object_id)
    original = path.read_bytes()
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        path.chmod(0o600)
        path.write_bytes(original + b" ")
        with pytest.raises(Exception, match="mismatch"):
            candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}
        path.write_bytes(original)
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))


@pytest.mark.parametrize("provider", ["tushare", "akshare_tencent"])
@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "outside_bad_finance",
        "outside_duplicate",
        "unselected_bad_finance",
        "unselected_bad_shape",
        "unselected_wrong_endpoint",
        "selected_wrong_code",
    ],
)
def test_selection_and_global_structural_boundaries(tmp_path, provider, case):
    def mutate(payload):
        call = payload["calls"][0]
        frame = call["frame"]
        row = frame["data"][0]
        if case == "duplicate":
            frame["data"].append(copy.deepcopy(row))
        elif case == "missing":
            frame["data"].clear()
        elif case.startswith("outside_"):
            extra = copy.deepcopy(row)
            extra[
                frame["columns"].index(
                    "date" if provider == "akshare_tencent" else "trade_date"
                )
            ] = "2022-03-10" if provider == "akshare_tencent" else "20220310"
            extra[frame["columns"].index("open")] = {
                "invalid": "ignored financial cell"
            }
            frame["data"].append(extra)
            if case == "outside_duplicate":
                frame["data"].append(copy.deepcopy(extra))
        elif case == "selected_wrong_code":
            if provider == "tushare":
                row[0] = "600096.SZ"
            else:
                call["request"]["symbol"] = "sh600000"
        else:
            extra = copy.deepcopy(call)
            if provider == "akshare_tencent":
                extra["symbol"] = "sh600000"
            else:
                extra["ts_code"] = "600000.SH"
                extra["frame"]["data"][0][0] = "600000.SH"
            if case == "unselected_bad_finance":
                extra["frame"]["data"][0][2] = {"invalid": "ignored"}
            if case == "unselected_bad_shape":
                extra["frame"]["data"][0].append(99)
            if case == "unselected_wrong_endpoint":
                extra["endpoint"] = "not_daily"
                if provider == "akshare_tencent":
                    extra.pop("frame")
            payload["calls"].append(extra)

    store, mat, bar = prepared(tmp_path, provider, mutate)
    try:
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        result = "pass"
    except ValueError as exc:
        result = str(exc)
    expected = case in {
        "outside_bad_finance",
        "outside_duplicate",
        "unselected_bad_finance",
    } or (
        provider == "akshare_tencent"
        and case in {"unselected_bad_shape", "unselected_wrong_endpoint"}
    )
    assert (result == "pass") is expected


def test_store_and_capture_id_isolation(tmp_path):
    first, mat, bar = prepared(tmp_path / "one")
    second, other_mat, _ = prepared(tmp_path / "two")
    assert mat.capture_ref == other_mat.capture_ref
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(first, mat, (bar,))
        candidate._validate_tencent_tushare_reported_amount(second, mat, (bar,))
        assert len(candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()) == 2
        capture = read_provider_capture(second, mat.capture_ref)
        path = second._path_for(capture.raw_object_ref.object_id)
        path.chmod(0o600)
        path.write_bytes(b"bad")
        with pytest.raises(Exception):
            candidate._validate_tencent_tushare_reported_amount(second, mat, (bar,))
        assert len(candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()) == 1


def test_scope_nested_join_and_exception_cleanup():
    with candidate.tencent_tushare_native_read_scope():
        outer = candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()
        with candidate.tencent_tushare_native_read_scope(join_existing=True):
            assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() is outer
        try:
            with candidate.tencent_tushare_native_read_scope():
                inner = candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()
                inner["x"] = "y"
                raise RuntimeError("stop")
        except RuntimeError:
            pass
        assert inner == {}
        assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() is outer
    assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() is None


@pytest.mark.parametrize("provider", ["tushare", "akshare_tencent"])
def test_unselected_symbol_stays_unvalidated_until_it_is_selected(tmp_path, provider):
    def mutate(payload):
        extra = copy.deepcopy(payload["calls"][0])
        if provider == "tushare":
            extra["ts_code"] = "600000.SH"
            extra["frame"]["data"][0][0] = "600000.SH"
        else:
            extra["symbol"] = "sh600000"
            extra["request"]["symbol"] = "sh600000"
        extra["frame"]["data"][0][extra["frame"]["columns"].index("open")] = 20
        payload["calls"].append(extra)

    store, mat, bar = prepared(tmp_path, provider, mutate)
    from core.types import InstrumentKey, InstrumentType

    other = replace(bar, instrument=InstrumentKey("600000", InstrumentType.STOCK))
    from data.market.capture import capture_provider_payload, read_provider_raw_payload

    capture = read_provider_capture(store, mat.capture_ref)
    request = json.loads(capture.request_json)
    request["instruments"].append({"symbol": "600000", "instrument_type": "stock"})
    widened = capture_provider_payload(
        store,
        provider=capture.provider,
        operation=capture.operation,
        request=request,
        raw_payload=read_provider_raw_payload(store, capture),
        payload_format=capture.payload_format,
        adapter_version=capture.adapter_version,
        started_at=capture.started_at,
        completed_at=capture.completed_at,
    )
    mat = SimpleNamespace(capture_ref=widened.capture_ref)
    with candidate.tencent_tushare_native_read_scope():
        candidate._validate_tencent_tushare_reported_amount(store, mat, (bar,))
        assert len(candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()) == 1
        with pytest.raises(ValueError, match="evidence_invalid"):
            candidate._validate_tencent_tushare_reported_amount(
                store, mat, (bar, other)
            )
        assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() == {}


def test_public_dataset_read_opens_fresh_scope_and_clears_it(tmp_path):
    legacy.test_native_dataset_cold_replay_retains_policy_and_finer_primary(tmp_path)
    assert candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get() is None


@pytest.mark.parametrize("provider", ["tushare", "akshare_tencent"])
def test_membership_set_changes_reuse_one_capture_and_lazy_symbol_indexes(
    tmp_path, monkeypatch, provider
):
    def mutate(payload):
        extra = copy.deepcopy(payload["calls"][0])
        if provider == "tushare":
            extra["ts_code"] = "600000.SH"
            extra["frame"]["data"][0][0] = "600000.SH"
        else:
            extra["symbol"] = "sh600000"
            extra["request"]["symbol"] = "sh600000"
        payload["calls"].append(extra)

    store, mat, bar = prepared(tmp_path, provider, mutate)
    from core.types import InstrumentKey, InstrumentType
    from data.market.capture import capture_provider_payload, read_provider_raw_payload

    capture = read_provider_capture(store, mat.capture_ref)
    request = json.loads(capture.request_json)
    request["instruments"].append({"symbol": "600000", "instrument_type": "stock"})
    widened = capture_provider_payload(
        store,
        provider=capture.provider,
        operation=capture.operation,
        request=request,
        raw_payload=read_provider_raw_payload(store, capture),
        payload_format=capture.payload_format,
        adapter_version=capture.adapter_version,
        started_at=capture.started_at,
        completed_at=capture.completed_at,
    )
    mat = SimpleNamespace(capture_ref=widened.capture_ref)
    other = replace(bar, instrument=InstrumentKey("600000", InstrumentType.STOCK))
    counts = {"inputs": 0, "index": 0}
    for name, label in [
        ("_tencent_tushare_native_inputs", "inputs"),
        ("_tencent_tushare_native_index", "index"),
    ]:
        original = getattr(candidate, name)

        def wrapped(*a, _original=original, _label=label, **kw):
            counts[_label] += 1
            return _original(*a, **kw)

        monkeypatch.setattr(candidate, name, wrapped)
    with candidate.tencent_tushare_native_read_scope():
        for bars in ((bar,), (bar, other), (other,), (bar,)):
            candidate._validate_tencent_tushare_reported_amount(store, mat, bars)
        cache = candidate._TENCENT_TUSHARE_NATIVE_INDEXES.get()
        assert len(cache) == 1
        assert set(next(iter(cache.values()))[2]) == {"600000", "600096"}
        assert counts == {"inputs": 1, "index": 2}
    assert cache == {}
