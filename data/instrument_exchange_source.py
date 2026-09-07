"""Explicit SSE announcement acquisition; content evidence never grants authority."""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import re
import ssl
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

SSE_LISTING_SOURCES = MappingProxyType(
    {
        "stock-688802": "https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20251216_10801769.shtml",
        "etf-530380": "https://www.sse.com.cn/disclosure/announcement/listing/c/c_20250930_10793503.shtml",
    }
)
COLLECTOR_VERSION = "sse-listing-capture-v1"
MAPPING_VERSION = "sse-listing-announcement-single-claimed-day-v1"
MAX_RESPONSE_BYTES = 128 * 1024
REQUEST_TIMEOUT_SECONDS = 10
TOTAL_TIMEOUT_SECONDS = 20


class SseSourceCaptureRejected(ValueError):
    """Acquisition, interpretation or immutable persistence could not complete."""


@dataclass(frozen=True)
class SseSourceCapture:
    source_id: str
    requested_url: str
    final_url: str
    started_at: str
    completed_at: str
    raw_sha256: str
    raw_size_bytes: int
    normalized_sha256: str
    mapping_sha256: str
    prior_raw_sha256s: tuple[str, ...]
    differs_from_prior_capture: bool
    schema_version: str = field(default="karkinos.sse_source_capture.v1", init=False)
    collector_version: str = field(default=COLLECTOR_VERSION, init=False)
    mapping_version: str = field(default=MAPPING_VERSION, init=False)
    http_status: int = field(default=200, init=False)
    capture_status: str = field(default="captured", init=False)
    transport_checks: tuple[str, ...] = field(
        default=(
            "fixed_https_origin_and_path",
            "default_certificate_and_hostname_validation",
            "no_redirect",
            "bounded_complete_html_response",
        ),
        init=False,
    )
    qualification: str = field(default="blocked", init=False)
    human_verification_status: str = field(default="not_performed", init=False)
    verified_supported_dates: tuple[str, ...] = field(default=(), init=False)
    available_at: None = field(default=None, init=False)
    authorizes_metadata_publication: bool = field(default=False, init=False)

    @property
    def receipt_sha256(self) -> str:
        return _digest(_json(asdict(self)))


def capture_sse_listing_source(url: str, *, output_dir: str | Path) -> SseSourceCapture:
    """Perform the fixed HTTPS request and publish a receipt after all objects exist."""
    source_id = _source_id(url)
    started_at = datetime.now(timezone.utc).isoformat()
    content = _fetch(url)
    completed_at = datetime.now(timezone.utc).isoformat()
    normalized, mapping = _derive(content, source_id)
    root = Path(output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        objects, captures = root / "objects", root / "captures"
        for directory in (objects, captures):
            if directory.is_symlink():
                raise SseSourceCaptureRejected("evidence_directory_symlink")
            directory.mkdir(exist_ok=True)
        lock_fd = os.open(
            root / ".capture.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(lock_fd, "rb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            prior = set()
            for path in sorted(captures.glob("*.json")):
                previous = _read_receipt(root, path.stem)
                if previous["requested_url"] == url:
                    prior.add(previous["raw_sha256"])
            for body in (content, normalized, mapping):
                _put_immutable(objects, _digest(body), body)
            raw_digest = _digest(content)
            result = SseSourceCapture(
                source_id,
                url,
                url,
                started_at,
                completed_at,
                raw_digest,
                len(content),
                _digest(normalized),
                _digest(mapping),
                tuple(sorted(prior)),
                bool(prior - {raw_digest}),
            )
            _put_immutable(
                captures, result.receipt_sha256 + ".json", _json(asdict(result))
            )
            return result
    except OSError as exc:
        raise SseSourceCaptureRejected("evidence_write_failed") from exc


def read_sse_source_object(output_dir: str | Path, digest: str) -> bytes:
    """Read exact saved bytes by expected digest without fetching or repairing."""
    return _read_object(Path(output_dir).resolve() / "objects", digest, digest)


def _source_id(url: str) -> str:
    for name, allowed in SSE_LISTING_SOURCES.items():
        if url == allowed:
            return name
    raise SseSourceCaptureRejected("source_url_not_allowed")


def _fetch(url: str) -> bytes:
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(
        "www.sse.com.cn", timeout=REQUEST_TIMEOUT_SECONDS, context=context
    )
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    try:
        connection.request(
            "GET",
            urlsplit(url).path,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": "Karkinos/" + COLLECTOR_VERSION,
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise SseSourceCaptureRejected("source_redirect_rejected")
        if response.status != 200:
            raise SseSourceCaptureRejected("source_http_status_rejected")
        if (
            response.getheader("Content-Type", "").split(";")[0].strip().lower()
            != "text/html"
        ):
            raise SseSourceCaptureRejected("source_content_type_rejected")
        if response.getheader("Content-Encoding") not in (None, "identity"):
            raise SseSourceCaptureRejected("source_content_encoding_rejected")
        length = response.getheader("Content-Length")
        transfer = response.getheader("Transfer-Encoding")
        if transfer not in (None, "chunked") or (transfer and length is not None):
            raise SseSourceCaptureRejected("source_framing_rejected")
        if length is not None and (
            not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES
        ):
            raise SseSourceCaptureRejected("source_size_rejected")
        content = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise SseSourceCaptureRejected("source_timeout")
            chunk = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - len(content)))
            if time.monotonic() > deadline:
                raise SseSourceCaptureRejected("source_timeout")
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_RESPONSE_BYTES:
                raise SseSourceCaptureRejected("source_size_rejected")
        if not content:
            raise SseSourceCaptureRejected("source_empty")
        if length is not None and len(content) != int(length):
            raise SseSourceCaptureRejected("source_truncated")
        return bytes(content)
    except ssl.SSLCertVerificationError as exc:
        raise SseSourceCaptureRejected("source_tls_verification_failed") from exc
    except TimeoutError as exc:
        raise SseSourceCaptureRejected("source_timeout") from exc
    except http.client.IncompleteRead as exc:
        raise SseSourceCaptureRejected("source_truncated") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise SseSourceCaptureRejected("source_fetch_failed") from exc
    finally:
        connection.close()


def _derive(content: bytes, source_id: str) -> tuple[bytes, bytes]:
    try:
        document = content.decode("utf-8")
        if "</body>" not in document or "</html>" not in document:
            raise ValueError("incomplete document")
        bodies = list(re.finditer(r'<div class="allZoom">(.*?)</div>', document, re.S))
        dates = list(
            re.finditer(
                r'<div class="article_opt">.*?<i>\s*(\d{4}-\d{2}-\d{2})\s*</i>',
                document,
                re.S,
            )
        )
        if len(bodies) != 1 or len(dates) != 1:
            raise ValueError("ambiguous announcement structure")
        body = bodies[0].group(1)
        kind, symbol = source_id.split("-")
        code_pattern = (
            r'证券代码为["“](\d{6})["”]'
            if kind == "stock"
            else r"证券代码[：:]\s*(\d{6})"
        )

        def one(pattern: str) -> re.Match:
            matches = list(re.finditer(pattern, body))
            if len(matches) != 1:
                raise ValueError("missing or ambiguous announcement field")
            return matches[0]

        code = one(code_pattern)
        event = one(r"于(\d{4}年\d{1,2}月\d{1,2}日)起")
        issuer = one(r"(上海证券交易所)")
        venue = one(r"(本所科创板|本所市场)")
        type_text = "A股股票" if kind == "stock" else "交易型开放式指数证券投资基金"
        if code.group(1) != symbol or type_text not in body:
            raise ValueError("unexpected typed instrument")
        opposite = "交易型开放式指数证券投资基金" if kind == "stock" else "A股股票"
        if opposite in body:
            raise ValueError("conflicting instrument types")
        event_day = date(
            *(int(value) for value in re.findall(r"\d+", event.group(1)))
        ).isoformat()
        publication_day = date.fromisoformat(dates[0].group(1)).isoformat()
        if event_day < publication_day:
            raise ValueError("unsupported retrospective notice")
        record = dict(
            record_id=source_id,
            symbol=symbol,
            instrument_type=kind,
            exchange="SSE",
            valid_from=event_day,
            valid_to=event_day,
        )
        normalized = _json(
            dict(
                schema_version="karkinos.instrument-exchange-source.v1",
                records=[record],
            )
        )

        def span(start: int, end: int) -> dict:
            return dict(
                byte_start=len(document[:start].encode()),
                byte_end_exclusive=len(document[:end].encode()),
                text=document[start:end],
                line_1based=document[:start].count("\n") + 1,
            )

        def located(match: re.Match) -> dict:
            return span(
                bodies[0].start(1) + match.start(1), bodies[0].start(1) + match.end(1)
            )

        type_start = bodies[0].start(1) + body.index(type_text)
        mapping = _json(
            dict(
                schema_version="karkinos.sse_source_mapping.v1",
                mapping_version=MAPPING_VERSION,
                raw_sha256=_digest(content),
                normalized_sha256=_digest(normalized),
                record_locator="/records/0",
                generated_record_id=source_id,
                fields=dict(
                    symbol=[located(code)],
                    instrument_type=[span(type_start, type_start + len(type_text))],
                    exchange=[located(venue), located(issuer)],
                    valid_from=[located(event)],
                    valid_to=[located(event)],
                ),
                page_publication_date=publication_day,
                publication_date_location=span(dates[0].start(1), dates[0].end(1)),
                available_at=None,
                scope="announcement_claim_only",
                valid_to_rule="single_claimed_listing_day_not_delisting_or_continuous_affiliation",
                limitations=[
                    "actual_listing_not_independently_verified",
                    "historical_interval_not_verified",
                    "source_capture_is_not_human_review",
                ],
            )
        )
        return normalized, mapping
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise SseSourceCaptureRejected("source_announcement_invalid") from exc


def _json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_object(directory: Path, filename: str, digest: str) -> bytes:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise SseSourceCaptureRejected("evidence_digest_invalid")
    path = directory / filename
    if directory.is_symlink() or path.is_symlink():
        raise SseSourceCaptureRejected("evidence_object_symlink")
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise SseSourceCaptureRejected("evidence_object_unavailable") from exc
    if len(content) > MAX_RESPONSE_BYTES or _digest(content) != digest:
        raise SseSourceCaptureRejected("evidence_content_digest_mismatch")
    return content


def _read_receipt(root: Path, digest: str) -> dict:
    content = _read_object(root / "captures", digest + ".json", digest)
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or _json(payload) != content:
            raise ValueError("invalid capture record")
        values = {
            value.name: payload[value.name]
            for value in fields(SseSourceCapture)
            if value.init
        }
        values["prior_raw_sha256s"] = tuple(values["prior_raw_sha256s"])
        if _json(asdict(SseSourceCapture(**values))) != content:
            raise ValueError("invalid capture fields")
        source_id = _source_id(payload["requested_url"])
        if (
            payload["source_id"] != source_id
            or payload["final_url"] != payload["requested_url"]
        ):
            raise ValueError("invalid capture origin")
        first, last = (
            datetime.fromisoformat(payload[name])
            for name in ("started_at", "completed_at")
        )
        if first.tzinfo is None or last.tzinfo is None or last < first:
            raise ValueError("invalid capture time")
        raw = read_sse_source_object(root, payload["raw_sha256"])
        if payload["raw_size_bytes"] != len(raw):
            raise ValueError("invalid capture size")
        normalized, mapping = _derive(raw, source_id)
        for name, expected in (
            ("normalized_sha256", normalized),
            ("mapping_sha256", mapping),
        ):
            if read_sse_source_object(root, payload[name]) != expected:
                raise ValueError("derived object changed")
        return payload
    except (TypeError, KeyError, ValueError) as exc:
        raise SseSourceCaptureRejected("evidence_capture_invalid") from exc


def _put_immutable(directory: Path, filename: str, content: bytes) -> None:
    expected = _digest(content)
    target = directory / filename
    if target.exists() or target.is_symlink():
        _read_object(directory, filename, expected)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=directory)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
            linked = True
        except FileExistsError:
            _read_object(directory, filename, expected)
        Path(temporary).unlink()
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _read_object(directory, filename, expected)
    except (OSError, SseSourceCaptureRejected):
        if linked:
            target.unlink()
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)
