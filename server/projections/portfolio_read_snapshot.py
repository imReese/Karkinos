"""Immutable, provider-free input snapshots for shared portfolio reads.

This module owns only the read-side coordination boundary.  Callers resolve a
fully published identity first and inject three persisted-fact readers.  The
service never imports a market provider, a persistence writer, OMS, or trading
authority code.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from threading import RLock
from time import perf_counter_ns
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast

from server.singleflight import SingleFlightCompletion


class PortfolioReadSnapshotRejected(RuntimeError):
    """Raised before a mixed or incomplete read snapshot can be cached."""


class PortfolioReadIdentityMismatch(PortfolioReadSnapshotRejected):
    """Raised when one read port returns facts bound to another identity."""


@dataclass(frozen=True, slots=True)
class PortfolioReadSnapshotIdentity:
    """Complete content identity for one replayable portfolio read."""

    valuation_snapshot_id: str
    ledger_cutoff_id: int
    ledger_fingerprint: str
    market_generation_id: str
    market_receipt_fingerprint: str
    market_content_fingerprint: str
    policy_version: str
    market_evidence_status: str = "complete"

    def __post_init__(self) -> None:
        for field_name in (
            "valuation_snapshot_id",
            "ledger_fingerprint",
            "market_generation_id",
            "market_receipt_fingerprint",
            "market_content_fingerprint",
            "policy_version",
            "market_evidence_status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if (
            isinstance(self.ledger_cutoff_id, bool)
            or not isinstance(self.ledger_cutoff_id, int)
            or self.ledger_cutoff_id < 0
        ):
            raise ValueError("ledger_cutoff_id must be a non-negative integer")
        if self.market_evidence_status not in {"complete", "legacy_incomplete"}:
            raise ValueError(
                "market_evidence_status must be complete or legacy_incomplete"
            )


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PortfolioReadPortResult(Generic[T]):
    """One identity-bound persisted read plus its observable SQL cost."""

    identity: PortfolioReadSnapshotIdentity
    value: T
    query_count: int
    rows_read: int

    def __post_init__(self) -> None:
        for field_name in ("query_count", "rows_read"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


PublishedValuationReader = Callable[
    [PortfolioReadSnapshotIdentity],
    PortfolioReadPortResult[Mapping[str, Any]],
]
LedgerRowsReader = Callable[
    [PortfolioReadSnapshotIdentity],
    PortfolioReadPortResult[Sequence[Mapping[str, Any]]],
]
PriceMatrixReader = Callable[
    [PortfolioReadSnapshotIdentity, tuple[Mapping[str, Any], ...]],
    PortfolioReadPortResult[Sequence[Mapping[str, Any]]],
]
IntradayQuoteRowsReader = Callable[
    [PortfolioReadSnapshotIdentity, tuple[Mapping[str, Any], ...]],
    PortfolioReadPortResult[Sequence[Mapping[str, Any]]],
]


@dataclass(frozen=True, slots=True)
class PortfolioReadSnapshotPorts:
    """The complete and deliberately read-only I/O surface for one build."""

    read_published_valuation: PublishedValuationReader
    read_ledger_rows: LedgerRowsReader
    read_price_matrix: PriceMatrixReader
    read_intraday_quote_rows: IntradayQuoteRowsReader | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "read_published_valuation",
            "read_ledger_rows",
            "read_price_matrix",
        ):
            if not callable(getattr(self, field_name)):
                raise TypeError(f"{field_name} must be callable")
        if self.read_intraday_quote_rows is not None and not callable(
            self.read_intraday_quote_rows
        ):
            raise TypeError("read_intraday_quote_rows must be callable or None")


@dataclass(frozen=True, slots=True)
class PortfolioReadSnapshotBuildMetrics:
    """Cost of the successful cold build that produced one snapshot."""

    query_count: int
    rows_read: int
    build_latency_ms: float


@dataclass(frozen=True, slots=True)
class PortfolioReadSnapshot:
    """Deeply immutable inputs shared by all projections for one identity."""

    identity: PortfolioReadSnapshotIdentity
    published_valuation: Mapping[str, Any]
    ledger_rows: tuple[Mapping[str, Any], ...]
    price_matrix_rows: tuple[Mapping[str, Any], ...]
    intraday_quote_rows: tuple[Mapping[str, Any], ...]
    build_metrics: PortfolioReadSnapshotBuildMetrics
    persisted_facts_only: bool = field(default=True, init=False)
    provider_contact_performed: bool = field(default=False, init=False)
    write_performed: bool = field(default=False, init=False)
    authorizes_execution: bool = field(default=False, init=False)
    changes_trading_authority: bool = field(default=False, init=False)
    changes_capital_authority: bool = field(default=False, init=False)

    @property
    def market_evidence_complete(self) -> bool:
        """Whether this snapshot is bound to complete published market evidence."""

        return self.identity.market_evidence_status == "complete"


@dataclass(frozen=True, slots=True)
class PortfolioReadSnapshotMetrics:
    """Immutable observation of cache, read, and build behavior."""

    cache_hits: int
    cache_misses: int
    cache_invalidations: int
    cache_evictions: int
    singleflight_waits: int
    builds: int
    build_failures: int
    query_count: int
    rows_read: int
    last_build_latency_ms: float | None
    total_build_latency_ms: float
    max_build_latency_ms: float
    cache_entries: int
    inflight_builds: int

    @property
    def average_build_latency_ms(self) -> float | None:
        if self.builds == 0:
            return None
        return self.total_build_latency_ms / self.builds


class PortfolioReadSnapshotService:
    """Build and cache content-addressed portfolio read inputs.

    Cache entries are keyed by the complete identity, so a newly published
    identity can never receive an older snapshot.  Older entries may remain in
    the bounded LRU for explicit replay.  A transition between requested
    identities records one logical invalidation of the prior active read while
    retaining its immutable content-addressed entry.
    """

    def __init__(
        self,
        *,
        max_entries: int = 4,
        monotonic_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")

        self._max_entries = max_entries
        self._monotonic_ns = monotonic_ns
        self._lock = RLock()
        self._cache: OrderedDict[
            PortfolioReadSnapshotIdentity, PortfolioReadSnapshot
        ] = OrderedDict()
        self._inflight: dict[
            PortfolioReadSnapshotIdentity,
            SingleFlightCompletion[PortfolioReadSnapshot],
        ] = {}
        self._last_requested_identity: PortfolioReadSnapshotIdentity | None = None

        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_invalidations = 0
        self._cache_evictions = 0
        self._singleflight_waits = 0
        self._builds = 0
        self._build_failures = 0
        self._query_count = 0
        self._rows_read = 0
        self._last_build_latency_ms: float | None = None
        self._total_build_latency_ms = 0.0
        self._max_build_latency_ms = 0.0

    def get_or_build(
        self,
        identity: PortfolioReadSnapshotIdentity,
        ports: PortfolioReadSnapshotPorts,
    ) -> PortfolioReadSnapshot:
        """Return one exact snapshot, sharing a cold build across callers."""

        if not isinstance(identity, PortfolioReadSnapshotIdentity):
            raise TypeError("identity must be PortfolioReadSnapshotIdentity")
        if not isinstance(ports, PortfolioReadSnapshotPorts):
            raise TypeError("ports must be PortfolioReadSnapshotPorts")

        with self._lock:
            if (
                self._last_requested_identity is not None
                and self._last_requested_identity != identity
            ):
                self._cache_invalidations += 1
            self._last_requested_identity = identity

            cached = self._cache.get(identity)
            if cached is not None:
                self._cache.move_to_end(identity)
                self._cache_hits += 1
                return cached

            self._cache_misses += 1
            flight = self._inflight.get(identity)
            if flight is not None:
                self._singleflight_waits += 1
                wait_for_flight = True
            else:
                flight = SingleFlightCompletion()
                self._inflight[identity] = flight
                wait_for_flight = False

        if wait_for_flight:
            return flight.wait()

        try:
            snapshot = self._build(identity, ports)
        except BaseException as exc:
            with self._lock:
                self._inflight.pop(identity, None)
                self._build_failures += 1
            flight.fail(exc)
            raise

        with self._lock:
            self._cache[identity] = snapshot
            self._cache.move_to_end(identity)
            active_identity = self._last_requested_identity
            if active_identity is not None and active_identity in self._cache:
                self._cache.move_to_end(active_identity)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)
                self._cache_evictions += 1
            self._inflight.pop(identity, None)
            self._builds += 1
            self._query_count += snapshot.build_metrics.query_count
            self._rows_read += snapshot.build_metrics.rows_read
            latency = snapshot.build_metrics.build_latency_ms
            self._last_build_latency_ms = latency
            self._total_build_latency_ms += latency
            self._max_build_latency_ms = max(self._max_build_latency_ms, latency)
        flight.succeed(snapshot)
        return snapshot

    def metrics(self) -> PortfolioReadSnapshotMetrics:
        """Return a stable metrics value without exposing mutable cache state."""

        with self._lock:
            return PortfolioReadSnapshotMetrics(
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                cache_invalidations=self._cache_invalidations,
                cache_evictions=self._cache_evictions,
                singleflight_waits=self._singleflight_waits,
                builds=self._builds,
                build_failures=self._build_failures,
                query_count=self._query_count,
                rows_read=self._rows_read,
                last_build_latency_ms=self._last_build_latency_ms,
                total_build_latency_ms=self._total_build_latency_ms,
                max_build_latency_ms=self._max_build_latency_ms,
                cache_entries=len(self._cache),
                inflight_builds=len(self._inflight),
            )

    def _build(
        self,
        identity: PortfolioReadSnapshotIdentity,
        ports: PortfolioReadSnapshotPorts,
    ) -> PortfolioReadSnapshot:
        started_ns = self._monotonic_ns()

        valuation_result = _identity_bound_result(
            ports.read_published_valuation(identity),
            expected=identity,
            port_name="read_published_valuation",
        )
        valuation = _freeze_mapping(
            _require_mapping(valuation_result.value, "published valuation")
        )
        _validate_published_valuation(valuation, identity)

        ledger_result = _identity_bound_result(
            ports.read_ledger_rows(identity),
            expected=identity,
            port_name="read_ledger_rows",
        )
        ledger_rows = _freeze_rows(ledger_result.value, "ledger rows")

        matrix_result = _identity_bound_result(
            ports.read_price_matrix(identity, ledger_rows),
            expected=identity,
            port_name="read_price_matrix",
        )
        price_matrix_rows = _freeze_rows(matrix_result.value, "price matrix rows")

        intraday_reader = ports.read_intraday_quote_rows
        if intraday_reader is None:
            intraday_result = PortfolioReadPortResult(
                identity=identity,
                value=(),
                query_count=0,
                rows_read=0,
            )
        else:
            intraday_result = _identity_bound_result(
                intraday_reader(identity, ledger_rows),
                expected=identity,
                port_name="read_intraday_quote_rows",
            )
        intraday_quote_rows = _freeze_rows(
            intraday_result.value,
            "intraday quote rows",
        )

        finished_ns = self._monotonic_ns()
        latency_ms = max(finished_ns - started_ns, 0) / 1_000_000
        return PortfolioReadSnapshot(
            identity=identity,
            published_valuation=valuation,
            ledger_rows=ledger_rows,
            price_matrix_rows=price_matrix_rows,
            intraday_quote_rows=intraday_quote_rows,
            build_metrics=PortfolioReadSnapshotBuildMetrics(
                query_count=(
                    valuation_result.query_count
                    + ledger_result.query_count
                    + matrix_result.query_count
                    + intraday_result.query_count
                ),
                rows_read=(
                    valuation_result.rows_read
                    + ledger_result.rows_read
                    + matrix_result.rows_read
                    + intraday_result.rows_read
                ),
                build_latency_ms=latency_ms,
            ),
        )


def _identity_bound_result(
    result: PortfolioReadPortResult[T],
    *,
    expected: PortfolioReadSnapshotIdentity,
    port_name: str,
) -> PortfolioReadPortResult[T]:
    if not isinstance(result, PortfolioReadPortResult):
        raise PortfolioReadSnapshotRejected(
            f"{port_name} must return PortfolioReadPortResult"
        )
    if result.identity != expected:
        raise PortfolioReadIdentityMismatch(
            f"{port_name} returned facts for a different portfolio read identity"
        )
    return result


def _validate_published_valuation(
    valuation: Mapping[str, Any],
    identity: PortfolioReadSnapshotIdentity,
) -> None:
    expected_fields: tuple[tuple[str, object], ...] = (
        ("snapshot_id", identity.valuation_snapshot_id),
        ("ledger_cutoff_id", identity.ledger_cutoff_id),
        ("ledger_fingerprint", identity.ledger_fingerprint),
        ("valuation_policy", identity.policy_version),
    )
    for field_name, expected in expected_fields:
        if valuation.get(field_name) != expected:
            raise PortfolioReadSnapshotRejected(
                f"published valuation {field_name} does not match requested identity"
            )


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioReadSnapshotRejected(f"{label} must be a mapping")
    return cast(Mapping[str, Any], value)


def _freeze_rows(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise PortfolioReadSnapshotRejected(f"{label} must be a sequence")
    frozen: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise PortfolioReadSnapshotRejected(f"{label}[{index}] must be a mapping")
        frozen.append(_freeze_mapping(cast(Mapping[str, Any], row)))
    return tuple(frozen)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PortfolioReadSnapshotRejected("persisted fact keys must be strings")
        frozen[key] = _freeze_value(item)
    return MappingProxyType(frozen)


def _freeze_value(value: Any) -> Any:
    if value is None or isinstance(
        value,
        (bool, int, float, str, bytes, Decimal, date, datetime),
    ):
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(cast(Mapping[str, Any], value))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    raise PortfolioReadSnapshotRejected(
        f"persisted fact value type {type(value).__name__} is not immutable"
    )


__all__ = (
    "PortfolioReadIdentityMismatch",
    "PortfolioReadPortResult",
    "PortfolioReadSnapshot",
    "PortfolioReadSnapshotBuildMetrics",
    "PortfolioReadSnapshotIdentity",
    "PortfolioReadSnapshotMetrics",
    "PortfolioReadSnapshotPorts",
    "PortfolioReadSnapshotRejected",
    "PortfolioReadSnapshotService",
)
