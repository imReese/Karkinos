"""Public announcement capture fails closed and preserves replayable bytes."""

import builtins
import gzip
import hashlib
import http.client
import json
import socket
import sqlite3
import ssl
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from data import instrument_exchange_source as source

FIXTURES = Path(__file__).parent / "fixtures"
STOCK_URL = source.SSE_LISTING_SOURCES["stock-688802"]


def _body(kind="stock"):
    return gzip.decompress((FIXTURES / f"sse_listing_{kind}.html.gz").read_bytes())


def _denied(*args, **kwargs):
    raise AssertionError("capture must not contact real sockets or databases")


@pytest.fixture(autouse=True)
def no_real_network_or_databases(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _denied)
    monkeypatch.setattr(sqlite3, "connect", _denied)


class Response:
    def __init__(self, body, *, status=200, headers=None, read_error=None):
        self.body = body
        self.status = status
        self.headers = {
            "Content-Type": "text/html; charset=UTF-8",
            "Content-Length": str(len(body)),
        }
        if headers:
            self.headers.update(headers)
        self.read_error = read_error
        self.offset = 0

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, size):
        if self.read_error:
            raise self.read_error
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


def _transport(monkeypatch, response, *, request_error=None):
    calls = []

    class Connection:
        def __init__(self, host, *, timeout, context):
            self.closed = False
            self.requests = []
            self.host = host
            self.timeout = timeout
            self.context = context
            calls.append(self)

        def request(self, method, path, *, headers):
            self.requests.append((method, path, headers))
            if request_error:
                raise request_error

        def getresponse(self):
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    return calls


def _captures(root):
    return tuple(sorted((root / "captures").glob("*.json")))


@pytest.mark.parametrize(
    "source_id,kind,event_day,publication_day",
    [
        ("stock-688802", "stock", "2025-12-17", "2025-12-16"),
        ("etf-530380", "etf", "2025-09-30", "2025-09-30"),
    ],
)
def test_public_notices_capture_verified_transport_and_replayable_claims(
    tmp_path, monkeypatch, source_id, kind, event_day, publication_day
):
    raw = _body(kind)
    calls = _transport(monkeypatch, Response(raw))
    url = source.SSE_LISTING_SOURCES[source_id]
    result = source.capture_sse_listing_source(url, output_dir=tmp_path)
    assert len(calls) == 1
    connection = calls[0]
    assert connection.closed
    assert connection.host == "www.sse.com.cn"
    assert connection.timeout == source.REQUEST_TIMEOUT_SECONDS
    assert connection.context.check_hostname is True
    assert connection.context.verify_mode == ssl.CERT_REQUIRED
    assert connection.requests == [
        (
            "GET",
            urlsplit(url).path,
            {
                "Accept-Encoding": "identity",
                "User-Agent": "Karkinos/" + source.COLLECTOR_VERSION,
            },
        )
    ]
    assert result.requested_url == result.final_url == url
    assert result.raw_size_bytes == len(raw)
    assert result.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.qualification == "blocked"
    assert result.human_verification_status == "not_performed"
    assert result.verified_supported_dates == ()
    assert result.available_at is None
    assert result.authorizes_metadata_publication is False
    assert datetime.fromisoformat(result.completed_at) >= datetime.fromisoformat(
        result.started_at
    )
    assert source.read_sse_source_object(tmp_path, result.raw_sha256) == raw
    normalized_bytes = source.read_sse_source_object(tmp_path, result.normalized_sha256)
    mapping_bytes = source.read_sse_source_object(tmp_path, result.mapping_sha256)
    for digest, body in (
        (result.normalized_sha256, normalized_bytes),
        (result.mapping_sha256, mapping_bytes),
    ):
        assert hashlib.sha256(body).hexdigest() == digest
    normalized, mapping = json.loads(normalized_bytes), json.loads(mapping_bytes)
    assert normalized["records"] == [
        {
            "record_id": source_id,
            "symbol": source_id.split("-")[1],
            "instrument_type": kind,
            "exchange": "SSE",
            "valid_from": event_day,
            "valid_to": event_day,
        }
    ]
    assert mapping["raw_sha256"] == result.raw_sha256
    assert mapping["normalized_sha256"] == result.normalized_sha256
    assert mapping["record_locator"] == "/records/0"
    assert mapping["generated_record_id"] == normalized["records"][0]["record_id"]
    assert mapping["page_publication_date"] == publication_day
    assert mapping["available_at"] is None
    assert mapping["scope"] == "announcement_claim_only"
    assert mapping["valid_to_rule"] == (
        "single_claimed_listing_day_not_delisting_or_continuous_affiliation"
    )
    locations = [mapping["publication_date_location"]]
    for spans in mapping["fields"].values():
        locations.extend(spans)
    for location in locations:
        start, end = location["byte_start"], location["byte_end_exclusive"]
        assert raw[start:end].decode() == location["text"]
        assert raw[:start].count(b"\n") + 1 == location["line_1based"]
    receipt_path = tmp_path / "captures" / (result.receipt_sha256 + ".json")
    assert _captures(tmp_path) == (receipt_path,)
    receipt_bytes = receipt_path.read_bytes()
    assert hashlib.sha256(receipt_bytes).hexdigest() == result.receipt_sha256
    assert json.loads(receipt_bytes) == json.loads(json.dumps(asdict(result)))


@pytest.mark.parametrize(
    "url",
    [
        STOCK_URL.replace("www.sse.com.cn", "example.test"),
        STOCK_URL.replace("www.sse.com.cn", "www.sse.com.cn.example.test"),
        STOCK_URL.replace("https:", "http:"),
        STOCK_URL + "#fragment",
        STOCK_URL + "?download=1",
        STOCK_URL.replace("10801769", "10801768"),
        STOCK_URL.replace("https://", "https://user@"),
        STOCK_URL.replace(".cn/", ".cn:443/"),
    ],
)
def test_non_allowlisted_urls_reject_before_any_transport_or_write(
    tmp_path, monkeypatch, url
):
    monkeypatch.setattr(http.client, "HTTPSConnection", _denied)
    with pytest.raises(source.SseSourceCaptureRejected, match="source_url_not_allowed"):
        source.capture_sse_listing_source(url, output_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", [301, 302, 307, 308, 403, 404, 500])
def test_http_failure_never_follows_redirect_or_publishes_receipt(
    tmp_path, monkeypatch, status
):
    calls = _transport(
        monkeypatch,
        Response(_body(), status=status, headers={"Location": STOCK_URL}),
    )
    reason = (
        "source_redirect_rejected"
        if 300 <= status < 400
        else "source_http_status_rejected"
    )
    with pytest.raises(source.SseSourceCaptureRejected, match=reason):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert len(calls) == len(calls[0].requests) == 1
    assert calls[0].closed
    assert _captures(tmp_path) == ()


@pytest.mark.parametrize(
    "error,reason",
    [
        (
            ssl.SSLCertVerificationError("hostname mismatch"),
            "source_tls_verification_failed",
        ),
        (TimeoutError("deadline"), "source_timeout"),
        (ConnectionError("connection failed"), "source_fetch_failed"),
    ],
)
def test_connection_failure_is_closed_and_never_records_success(
    tmp_path, monkeypatch, error, reason
):
    calls = _transport(monkeypatch, Response(_body()), request_error=error)
    with pytest.raises(source.SseSourceCaptureRejected, match=reason):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert calls[0].closed
    assert _captures(tmp_path) == ()


@pytest.mark.parametrize(
    "headers,reason",
    [
        ({"Content-Type": "application/json"}, "source_content_type_rejected"),
        ({"Content-Encoding": "gzip"}, "source_content_encoding_rejected"),
        ({"Content-Length": "-1"}, "source_size_rejected"),
        (
            {"Content-Length": str(source.MAX_RESPONSE_BYTES + 1)},
            "source_size_rejected",
        ),
        ({"Transfer-Encoding": "chunked"}, "source_framing_rejected"),
        (
            {"Content-Length": None, "Transfer-Encoding": "gzip"},
            "source_framing_rejected",
        ),
        ({"Content-Length": "1"}, "source_truncated"),
    ],
)
def test_invalid_response_headers_do_not_create_capture(
    tmp_path, monkeypatch, headers, reason
):
    _transport(monkeypatch, Response(_body(), headers=headers))
    with pytest.raises(source.SseSourceCaptureRejected, match=reason):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert _captures(tmp_path) == ()


@pytest.mark.parametrize(
    "body,headers,read_error,reason",
    [
        (b"", {}, None, "source_empty"),
        (
            b"x" * (source.MAX_RESPONSE_BYTES + 1),
            {"Content-Length": None},
            None,
            "source_size_rejected",
        ),
        (b"partial", {"Content-Length": "100"}, None, "source_truncated"),
        (b"", {}, http.client.IncompleteRead(b"partial", 10), "source_truncated"),
        (b"", {}, TimeoutError("slow body"), "source_timeout"),
        (b"<html><body>broken", {}, None, "source_announcement_invalid"),
        (b"\xff</body></html>", {}, None, "source_announcement_invalid"),
    ],
)
def test_bad_response_body_never_publishes_success(
    tmp_path, monkeypatch, body, headers, read_error, reason
):
    calls = _transport(
        monkeypatch, Response(body, headers=headers, read_error=read_error)
    )
    with pytest.raises(source.SseSourceCaptureRejected, match=reason):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert calls[0].closed
    assert _captures(tmp_path) == ()


def test_total_read_deadline_cannot_be_extended_by_small_chunks(tmp_path, monkeypatch):
    calls = _transport(monkeypatch, Response(_body()))
    times = iter([0.0, 1.0, source.TOTAL_TIMEOUT_SECONDS + 1.0])
    monkeypatch.setattr(source.time, "monotonic", lambda: next(times))
    with pytest.raises(source.SseSourceCaptureRejected, match="source_timeout"):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert calls[0].closed
    assert _captures(tmp_path) == ()


@pytest.mark.parametrize(
    "old,new",
    [
        ('证券代码为"688802"', '证券代码为"688803"'),
        ("上海证券交易所", "其他证券交易所"),
        ("本所科创板", "其他市场"),
        ("A股股票", "交易型开放式指数证券投资基金"),
        ("2025年12月17日起", "2025年12月15日起"),
        ("</html>", ""),
    ],
)
def test_malformed_or_conflicting_announcement_claim_is_not_normalized(
    tmp_path, monkeypatch, old, new
):
    raw = _body().decode()
    assert old in raw
    _transport(monkeypatch, Response(raw.replace(old, new).encode()))
    with pytest.raises(
        source.SseSourceCaptureRejected, match="source_announcement_invalid"
    ):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert _captures(tmp_path) == ()


@pytest.mark.parametrize("failed_directory", ["objects", "captures"])
def test_write_failure_never_leaves_a_success_receipt(
    tmp_path, monkeypatch, failed_directory
):
    _transport(monkeypatch, Response(_body()))
    original_link = source.os.link

    def failing_link(src, dst, *args, **kwargs):
        if Path(dst).parent.name == failed_directory:
            raise OSError("injected persistence failure")
        return original_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(source.os, "link", failing_link)
    with pytest.raises(source.SseSourceCaptureRejected, match="evidence_write_failed"):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert _captures(tmp_path) == ()
    assert list(tmp_path.rglob(".pending-*")) == []


def test_receipt_directory_sync_failure_preserves_last_good_capture(
    tmp_path, monkeypatch
):
    _transport(monkeypatch, Response(_body()))
    source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    original_link, original_sync = source.os.link, source.os.fsync
    receipt_linked = False

    def track_link(src, dst, *args, **kwargs):
        nonlocal receipt_linked
        result = original_link(src, dst, *args, **kwargs)
        receipt_linked = Path(dst).parent.name == "captures"
        return result

    def failing_sync(descriptor):
        if receipt_linked:
            raise OSError("injected receipt-directory sync failure")
        return original_sync(descriptor)

    monkeypatch.setattr(source.os, "link", track_link)
    monkeypatch.setattr(source.os, "fsync", failing_sync)
    changed = _body().replace(b"</html>", b"<!-- changed -->\n</html>")
    _transport(monkeypatch, Response(changed))
    with pytest.raises(source.SseSourceCaptureRejected, match="evidence_write_failed"):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert len(_captures(tmp_path)) == 1
    assert all(path.read_bytes() == content for path, content in before.items())
    assert list(tmp_path.rglob(".pending-*")) == []


@pytest.mark.parametrize("directory", ["objects", "captures"])
def test_symlink_evidence_directory_cannot_redirect_writes(
    tmp_path, monkeypatch, directory
):
    output, outside = tmp_path / "output", tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    (output / directory).symlink_to(outside, target_is_directory=True)
    _transport(monkeypatch, Response(_body()))
    with pytest.raises(
        source.SseSourceCaptureRejected, match="evidence_directory_symlink"
    ):
        source.capture_sse_listing_source(STOCK_URL, output_dir=output)
    assert list(outside.iterdir()) == []
    assert _captures(output) == ()


def test_changed_capture_keeps_prior_objects_and_reports_changed_bytes(
    tmp_path, monkeypatch
):
    first_raw = _body()
    _transport(monkeypatch, Response(first_raw))
    first = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    changed_raw = first_raw.replace(b"</html>", b"<!-- later capture -->\n</html>")
    _transport(monkeypatch, Response(changed_raw))
    second = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert second.prior_raw_sha256s == (first.raw_sha256,)
    assert second.differs_from_prior_capture is True
    assert second.raw_sha256 != first.raw_sha256
    assert len(_captures(tmp_path)) == 2
    assert all(path.read_bytes() == content for path, content in before.items())
    assert source.read_sse_source_object(tmp_path, first.raw_sha256) == first_raw
    assert source.read_sse_source_object(tmp_path, second.raw_sha256) == changed_raw


def test_same_bytes_capture_does_not_claim_source_change(tmp_path, monkeypatch):
    _transport(monkeypatch, Response(_body()))
    first = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    _transport(monkeypatch, Response(_body()))
    second = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert second.prior_raw_sha256s == (first.raw_sha256,)
    assert second.raw_sha256 == first.raw_sha256
    assert second.differs_from_prior_capture is False
    assert len(list((tmp_path / "objects").iterdir())) == 3


@pytest.mark.parametrize(
    "object_field",
    ["raw_sha256", "normalized_sha256", "mapping_sha256", "receipt_sha256"],
)
def test_tampered_prior_evidence_is_not_repaired_or_replaced(
    tmp_path, monkeypatch, object_field
):
    _transport(monkeypatch, Response(_body()))
    first = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    digest = getattr(first, object_field)
    path = (
        tmp_path / "captures" / (digest + ".json")
        if object_field == "receipt_sha256"
        else tmp_path / "objects" / digest
    )
    path.write_bytes(path.read_bytes() + b"tampered")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _transport(monkeypatch, Response(_body()))
    with pytest.raises(source.SseSourceCaptureRejected):
        source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    assert len(_captures(tmp_path)) == 1
    assert all(p.read_bytes() == content for p, content in before.items())


def test_read_by_expected_digest_rejects_tamper_and_path_traversal(
    tmp_path, monkeypatch
):
    _transport(monkeypatch, Response(_body()))
    result = source.capture_sse_listing_source(STOCK_URL, output_dir=tmp_path)
    path = tmp_path / "objects" / result.raw_sha256
    path.write_bytes(b"changed")
    with pytest.raises(
        source.SseSourceCaptureRejected, match="evidence_content_digest_mismatch"
    ):
        source.read_sse_source_object(tmp_path, result.raw_sha256)
    with pytest.raises(
        source.SseSourceCaptureRejected, match="evidence_digest_invalid"
    ):
        source.read_sse_source_object(tmp_path, "../../app.db")


def test_capture_writes_only_explicit_directory_without_financial_state(
    tmp_path, monkeypatch
):
    output = tmp_path / "explicit" / "evidence"
    unrelated = tmp_path / "untouched.txt"
    unrelated.write_text("unrelated")
    _transport(monkeypatch, Response(_body()))
    original_import = builtins.__import__

    def no_server_import(name, *args, **kwargs):
        if name == "server" or name.startswith("server."):
            raise AssertionError("capture may not import server state")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_server_import)
    source.capture_sse_listing_source(STOCK_URL, output_dir=output)
    assert unrelated.read_text() == "unrelated"
    assert all(
        p.is_relative_to(output)
        for p in tmp_path.rglob("*")
        if p.is_file() and p != unrelated
    )
    assert not list(tmp_path.rglob("*.db"))


def test_collector_module_import_does_not_load_server_application_state():
    program = """
import builtins
import socket
import sqlite3
original_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == 'server' or name.startswith('server.'):
        raise AssertionError('collector imported server')
    return original_import(name, *args, **kwargs)
def forbidden(*args, **kwargs):
    raise AssertionError('collector initialized network or database')
builtins.__import__ = blocked_import
socket.create_connection = forbidden
sqlite3.connect = forbidden
import data.instrument_exchange_source
import tools.capture_instrument_exchange_source
"""
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "kind,event_day", [("stock", "2025-12-17"), ("etf", "2025-09-30")]
)
def test_captured_normalization_is_accepted_as_content_but_preview_stays_blocked(
    tmp_path, monkeypatch, kind, event_day
):
    from core.types import InstrumentKey
    from server.projections.instrument_exchange_evidence import (
        ExchangeSourceReference,
        InstrumentExchangeTarget,
        InstrumentExchangeTargets,
        preview_instrument_exchange_evidence,
    )
    from server.projections.portfolio_read_snapshot import PortfolioReadSnapshotIdentity

    _transport(monkeypatch, Response(_body(kind)))
    source_id = "stock-688802" if kind == "stock" else "etf-530380"
    capture = source.capture_sse_listing_source(
        source.SSE_LISTING_SOURCES[source_id], output_dir=tmp_path
    )
    content = source.read_sse_source_object(tmp_path, capture.normalized_sha256)
    targets = InstrumentExchangeTargets(
        PortfolioReadSnapshotIdentity(
            "valuation", 1, "ledger", "market", "receipt", "content", "policy"
        ),
        datetime(2026, 9, 7, tzinfo=timezone.utc),
        "synthetic-coverage",
        "synthetic-metadata",
        (
            InstrumentExchangeTarget(
                InstrumentKey.from_values(source_id.split("-")[1], kind),
                (event_day,),
                (None,),
                "synthetic-instrument",
            ),
        ),
    )
    reference = ExchangeSourceReference(
        capture.normalized_sha256,
        capture.requested_url,
        capture.normalized_sha256,
        ("/records/0",),
    )
    preview = preview_instrument_exchange_evidence(
        targets,
        current_targets=targets,
        sources=(reference,),
        source_contents={reference.content_ref: content},
    )
    item = preview.items[0]
    assert item.candidate_exchange == "SSE"
    assert item.record_matched_dates == (event_day,)
    assert item.status == "blocked"
    assert item.human_verification_status == "not_performed"
    assert item.verified_supported_dates == ()
    assert "source_authenticity_unverified" in item.blockers
    assert "human_review_required" in item.blockers
    assert preview.database_writes_performed is False
    assert preview.authorizes_metadata_publication is False
