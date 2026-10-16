"""Persist unresolved publication failures independently of last-good reads."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market_daily_store import (
    read_verified_market_daily_receipt_records_on_connection,
)
from data.market_data import (
    PUBLISHED_FUND_NAV_QUOTE_SOURCES,
    is_fund_estimate_quote_source,
)
from server.contracts.quote_ingestion import (
    QuoteIngestionCommand,
    quote_authority_conflict_fields,
)
from server.persistence.connection import connect_sqlite
from server.persistence.database_identity import require_database_path
from server.persistence.database_normalization import stable_json_fingerprint
from server.persistence.event_log import insert_event_sync
from server.persistence.financial_fact_event_payloads import quote_instant_storage_key

RECOVERY_KEY = "valuation_publication_recovery"
ATTEMPT_KEY = "valuation_snapshot_publication_attempt"
UNPUBLISHED_RECOVERY_CONFIRMATION = (
    "discard_proven_unpublished_failed_quote_refresh_without_changing_financial_facts"
)
_RECOVERY_EVENT = "market.quote.unpublished_refresh.discarded"


def _instrument_scope(scope) -> set[tuple[str, str]]:
    keys = [
        InstrumentKey.from_values(symbol, asset_type) for asset_type, symbol in scope
    ]
    return {(key.instrument_type.value, key.symbol) for key in keys}


def _control(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value_json FROM main.runtime_controls WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise ValueError("valuation publication recovery metadata invalid")
    return value


class QuoteRunScopeUnavailable(ValueError):
    """Legacy audit metadata cannot establish an exact requested scope."""


class InvalidQuoteRunScope(ValueError):
    """An explicit request identity is malformed or internally inconsistent."""


def quote_run_scope(
    conn: sqlite3.Connection, run_id: str | None, *, require_exact: bool = False
) -> list[list[str]] | None:
    """Unknown historical scope blocks reads; every new publication requires proof."""
    run = conn.execute(
        "SELECT asset_type, symbol_count, metadata_json FROM main.quote_fetch_runs "
        "WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    try:
        return _requested_scope(run)
    except (QuoteRunScopeUnavailable, InvalidQuoteRunScope):
        if require_exact:
            raise
        return None


def _requested_scope(run) -> list[list[str]]:
    if run is None:
        raise QuoteRunScopeUnavailable("quote publication requested scope unavailable")
    try:
        metadata = json.loads(run[2] or "{}")
    except (ValueError, TypeError) as exc:
        raise InvalidQuoteRunScope(
            "quote publication request metadata invalid"
        ) from exc
    if not isinstance(metadata, dict):
        raise InvalidQuoteRunScope("quote publication request metadata invalid")
    if not {"requested_symbols", "symbols"}.intersection(metadata):
        raise QuoteRunScopeUnavailable("quote publication requested scope unavailable")
    symbols = metadata.get("requested_symbols", metadata.get("symbols"))
    if (
        not isinstance(symbols, list)
        or len(symbols) != run[1]
        or not symbols
        or any(not isinstance(s, str) or not s.strip() for s in symbols)
    ):
        raise InvalidQuoteRunScope("quote publication requested symbols invalid")
    asset_types = metadata.get(
        "instrument_types", metadata.get("asset_types", [run[0]] * len(symbols))
    )
    if (
        not isinstance(asset_types, list)
        or len(asset_types) != len(symbols)
        or any(not isinstance(kind, str) or not kind.strip() for kind in asset_types)
    ):
        raise InvalidQuoteRunScope(
            "quote publication requested instrument types invalid"
        )
    if "instrument_types" in metadata:
        if any(
            kind not in {item.value for item in InstrumentType} for kind in asset_types
        ):
            raise InvalidQuoteRunScope(
                "quote publication requires canonical instrument types"
            )
    elif any(kind.strip().lower() == "fund" for kind in asset_types):
        # Broad fund identity cannot establish an ETF or open-end-fund request.
        raise QuoteRunScopeUnavailable(
            "quote publication requested fund identity unavailable"
        )
    try:
        scope = _instrument_scope(zip(asset_types, symbols, strict=True))
    except (TypeError, ValueError) as exc:
        raise InvalidQuoteRunScope(
            "quote publication requested identity invalid"
        ) from exc
    if len(scope) != len(symbols):
        raise InvalidQuoteRunScope("quote publication requested identities duplicated")
    return [list(key) for key in sorted(scope)]


def unresolved_publications(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    control = _control(conn, RECOVERY_KEY)
    if control is not None:
        failures = control.get("failures")
        if not isinstance(failures, list) or any(
            not isinstance(item, dict) for item in failures
        ):
            raise ValueError("valuation publication recovery metadata invalid")
        for item in failures:
            scope = item.get("scope")
            if scope is not None and (
                not isinstance(scope, list)
                or any(
                    not isinstance(key, list)
                    or len(key) != 2
                    or any(not isinstance(part, str) or not part for part in key)
                    for key in scope
                )
            ):
                raise ValueError("valuation publication recovery scope invalid")
        return failures
    # Older releases persisted only the latest attempt. Keep that failure when
    # startup or an unrelated ledger write publishes another valuation.
    attempt = _control(conn, ATTEMPT_KEY)
    if attempt is None:
        # Schema-10 releases wrote failure into the current pointer itself.
        # Preserve it before a startup publication replaces that legacy control.
        attempt = _control(conn, "valuation_snapshot_publication")
    if attempt and attempt.get("status") == "failed":
        return [
            {
                **attempt,
                "scope": quote_run_scope(conn, attempt.get("quote_fetch_run_id")),
            }
        ]
    return []


def affected_publications(
    conn: sqlite3.Connection, instruments: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Unknown failure scope blocks; known scope affects only its consumers."""
    return [
        failure
        for failure in unresolved_publications(conn)
        if publication_affects_instruments(failure, instruments)
    ]


def publication_affects_instruments(
    failure: dict[str, Any], instruments: set[tuple[str, str]]
) -> bool:
    """Apply the canonical typed scope rule to already-read incident evidence."""
    return not failure.get("scope") or bool(
        _instrument_scope(instruments).intersection(_instrument_scope(failure["scope"]))
    )


def require_valuation_recovery_clear(db: Any, valuation: Mapping[str, Any]) -> None:
    """Apply the same scoped publication fence to current account admission.

    A complete last-good valuation remains readable, but it cannot admit a new
    account qualification or publication while its quote scope has an unresolved
    publication incident. Cash-only accounts retain the canonical empty scope;
    an incident whose scope is unknown still blocks them.
    """
    try:
        path = require_database_path(
            db, ValueError("valuation_publication_recovery_unavailable")
        )
        quotes = valuation.get("quotes")
        if not isinstance(quotes, list):
            raise ValueError("valuation_publication_recovery_unavailable")
        instruments = {
            (key.instrument_type.value, key.symbol)
            for row in quotes
            for key in [InstrumentKey.from_values(row["symbol"], row["asset_type"])]
        }
        with closing(connect_sqlite(path, readonly=True)) as conn:
            conn.execute("BEGIN")
            failures = affected_publications(conn, instruments)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("valuation_publication_recovery_unavailable") from None
    if failures:
        raise ValueError("valuation_publication_recovery_required")


def _recovery_instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    # Legacy run timestamps use the application's Shanghai wall clock.
    if result.tzinfo is None:
        result = result.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return result.astimezone(timezone.utc)


def _published_run_references(conn, run_ids):
    references: dict[str, list[dict[str, Any]]] = {key: [] for key in run_ids}
    for table in ("quote_snapshots", "latest_quotes"):
        for row in conn.execute(
            f"SELECT fetch_run_id, COUNT(*) FROM {table} "
            "WHERE fetch_run_id IS NOT NULL GROUP BY fetch_run_id"
        ):
            if row[0] in references:
                references[row[0]].append({"table": table, "count": row[1]})
    for row in conn.execute(
        "SELECT snapshot_id, metadata_json, quotes_json FROM valuation_snapshots"
    ):
        metadata = json.loads(row[1] or "{}")
        quotes = json.loads(row[2])
        if not isinstance(metadata, dict) or not isinstance(quotes, list):
            raise ValueError("recovery_valuation_provenance_invalid")
        ingestions = metadata.get("ingestion_run_ids", [])
        if not isinstance(ingestions, list):
            raise ValueError("recovery_valuation_provenance_invalid")
        bound = set(ingestions) | {
            quote.get("fetch_run_id") for quote in quotes if isinstance(quote, dict)
        }
        for identity in run_ids.intersection(bound):
            references[identity].append(
                {"table": "valuation_snapshots", "snapshot_id": row[0]}
            )
    for row in conn.execute(
        "SELECT id, payload_json FROM event_log "
        "WHERE event_type IN ('market.quote.snapshot.recorded','market.quote.refreshed')"
    ):
        payload = json.loads(row[1])
        if not isinstance(payload, dict):
            raise ValueError("recovery_quote_event_provenance_invalid")
        identity = payload.get("fetch_run_id")
        if identity in references:
            references[identity].append({"table": "event_log", "id": row[0]})
    return references


def _refresh_count_basis(run, metadata, scope, staged_count):
    requested = [item[1] for item in scope]
    if (
        run["success_count"] >= 0
        and run["failure_count"] > 0
        and run["success_count"] + run["failure_count"] == run["symbol_count"]
        and staged_count == run["success_count"]
    ):
        return "terminal_counts", None
    # SchedulerLoop._finish_failed_poll rejects the whole batch after any quote
    # quality/time failure, including proposals already staged earlier in it.
    error = str(run["error_message"] or "")
    if (
        run["trigger"] == "scheduler_poll"
        and run["status"] == "failed"
        and run["success_count"] == 0
        and run["failure_count"] == run["symbol_count"]
        and 0 <= staged_count <= run["symbol_count"]
        and metadata.get("success_symbols") == []
        and sorted(metadata.get("failed_symbols") or []) == sorted(requested)
        and (
            error.startswith("scheduler quote is stale: ")
            or error
            == "quote ingestion quote_timestamp must not be later than the authoritative capture time"
        )
    ):
        return "scheduler_rejected_complete_batch", None
    # The manual-refresh producer counts refreshed/failed symbols separately
    # from its explicitly skipped group. Skipped quotes may still be staged;
    # these persisted group identities must fully explain the legacy counters.
    if run["trigger"] == "manual_refresh":
        groups = [
            metadata.get(name)
            for name in ("refreshed_symbols", "failed_symbols", "skipped_symbols")
        ]
        if all(
            isinstance(group, list) and all(isinstance(x, str) for x in group)
            for group in groups
        ):
            refreshed, failed, skipped = groups
            combined = refreshed + failed + skipped
            if (
                len(set(combined)) == len(combined)
                and sorted(combined) == sorted(requested)
                and len(refreshed) == run["success_count"]
                and len(failed) == run["failure_count"]
                and staged_count == len(refreshed) + len(skipped)
            ):
                return "manual_refresh_explicit_skipped_group", set(refreshed + skipped)
    raise ValueError("recovery_terminal_or_staged_counts_inconsistent")


def _rejected_estimate_evidence(conn, run, commands):
    """A recognized estimate cannot replace a preexisting published fund NAV.

    The rejected provider proposal is never promoted to a financial fact. Its
    exact prior NAV snapshot and recording event establish the disposition;
    neither today's price nor a newly complete valuation is used as a proxy.
    """
    prior_refs = []
    for command in commands:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM quote_snapshots WHERE symbol=? AND instrument_type=? "
                "AND quote_instant_utc=? ORDER BY id",
                (
                    command.symbol,
                    command.asset_type,
                    quote_instant_storage_key(command.quote_timestamp),
                ),
            )
            if _recovery_instant(row["created_at"])
            <= _recovery_instant(run["finished_at"])
        ]
        for prior in rows:
            financial_conflicts = set(
                quote_authority_conflict_fields(prior, command.to_dict())
            ) & {"price", "nav_date"}
            if not financial_conflicts:
                continue
            if (
                command.asset_type != "open_end_fund"
                or not is_fund_estimate_quote_source(command.quote_source)
                or str(prior["quote_source"] or "").strip().lower()
                not in PUBLISHED_FUND_NAV_QUOTE_SOURCES
                or not command.nav_date
                or prior["nav_date"] != command.nav_date
                or prior["quote_status"]
                not in {"live", "confirmed", "fresh", "healthy", "cache", "cached"}
            ):
                raise ValueError("recovery_prior_financial_fact_requires_resolution")
            peers = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM quote_snapshots WHERE symbol=? AND instrument_type='open_end_fund' "
                    "AND nav_date=? ORDER BY id",
                    (command.symbol, command.nav_date),
                )
                if _recovery_instant(row["created_at"])
                <= _recovery_instant(run["finished_at"])
                and str(row["quote_source"] or "").strip().lower()
                in PUBLISHED_FUND_NAV_QUOTE_SOURCES
            ]
            if any(
                "price" in quote_authority_conflict_fields(peer, prior)
                for peer in peers
            ):
                raise ValueError("recovery_prior_published_nav_conflicting")
            events = conn.execute(
                "SELECT id,payload_json,created_at FROM event_log "
                "WHERE event_type='market.quote.snapshot.recorded' AND source='quote_snapshots' AND source_ref=?",
                (str(prior["id"]),),
            ).fetchall()
            if len(events) != 1:
                raise ValueError("recovery_prior_nav_event_missing_or_ambiguous")
            event = json.loads(events[0][1])
            if (
                not isinstance(event, dict)
                or event.get("snapshot_id") != prior["id"]
                or event.get("symbol") != command.symbol
                or event.get("asset_type") != "open_end_fund"
                or event.get("fetch_run_id") != prior["fetch_run_id"]
                or quote_instant_storage_key(event.get("quote_timestamp"))
                != prior["quote_instant_utc"]
                or quote_authority_conflict_fields(prior, event)
                or _recovery_instant(events[0][2])
                > _recovery_instant(run["finished_at"])
            ):
                raise ValueError("recovery_prior_nav_event_changed")
            prior_refs.append(
                {
                    "snapshot_id": prior["id"],
                    "snapshot_fingerprint": stable_json_fingerprint(prior),
                    "event_id": events[0][0],
                    "event_fingerprint": stable_json_fingerprint(event),
                }
            )
    return prior_refs


def _original_quote_events(conn):
    """Index original audit observations once in this consistent plan transaction."""
    originals: dict[
        tuple[InstrumentKey, str], list[tuple[int, dict[str, Any], datetime]]
    ] = {}
    for row in conn.execute(
        "SELECT id,payload_json,created_at FROM event_log "
        "WHERE event_type='market.quote.refreshed' AND source='latest_quotes'"
    ):
        value = json.loads(row[1])
        if not isinstance(value, dict):
            raise ValueError("recovery_prior_quote_event_invalid")
        key = (
            InstrumentKey.from_values(value["symbol"], value["asset_type"]),
            quote_instant_storage_key(value["quote_timestamp"]),
        )
        originals.setdefault(key, []).append((row[0], value, _recovery_instant(row[2])))
    return originals


def _rejected_duplicate_evidence(run, commands, originals):
    """Discard a duplicate proposal while preserving its original financial facts.

    Older releases recorded latest-quote facts in the append-only event log
    before quote snapshots existed. Reopen those original observations; never
    substitute today's latest quote or adopt the failed proposal's differences.
    """
    refs = []
    allowed_differences = {
        "previous_close",
        "change",
        "change_percent",
        "volume",
        "turnover",
        "quote_status",
        "stale_reason",
    }
    for command in commands:
        key = (
            InstrumentKey.from_values(command.symbol, command.asset_type),
            quote_instant_storage_key(command.quote_timestamp),
        )
        for event_id, prior, recorded_at in originals.get(key, []):
            if recorded_at > _recovery_instant(run["finished_at"]):
                continue
            if (
                "price" not in prior
                or "nav_date" not in prior
                or prior["nav_date"] != command.nav_date
                or {"price", "nav_date"}.intersection(
                    quote_authority_conflict_fields(prior, command.to_dict())
                )
            ):
                raise ValueError("recovery_prior_financial_fact_requires_resolution")
            conflicts = set(quote_authority_conflict_fields(prior, command.to_dict()))
            if conflicts - allowed_differences:
                raise ValueError("recovery_prior_financial_fact_requires_resolution")
            if conflicts:
                refs.append(
                    {
                        "event_id": event_id,
                        "event_fingerprint": stable_json_fingerprint(prior),
                        "rejected_difference_fields": sorted(conflicts),
                    }
                )
    if not refs:
        raise ValueError("recovery_prior_financial_fact_requires_resolution")
    return refs


def attach_recovery_market_database(
    conn: sqlite3.Connection, database_path: str | Path | None
) -> None:
    """Reopen an explicitly selected existing market owner without creating it."""
    if database_path is None:
        return
    path = Path(database_path).resolve(strict=True)
    main = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    if path == main:
        raise ValueError("recovery_market_database_identity_invalid")
    conn.execute("ATTACH DATABASE ? AS market_meta", (path.as_uri() + "?mode=ro",))


def _legacy_close_receipt(conn, *, day, provider, finished_at):
    row = conn.execute(
        "SELECT * FROM market_meta.market_daily_ingestion_receipts "
        "WHERE trade_date=? AND provider_name=?",
        (day, provider),
    ).fetchone()
    if row is None:
        raise ValueError("recovery_legacy_close_receipt_missing")
    receipt = json.loads(row["receipt_json"])
    if (
        not isinstance(receipt, dict)
        or receipt.get("trade_date") != day
        or receipt.get("provider_name") != provider
        or receipt.get("row_count") != row["row_count"]
        or receipt.get("dataset_fingerprint") != row["dataset_fingerprint"]
        or _recovery_instant(row["created_at"]) > _recovery_instant(finished_at)
    ):
        raise ValueError("recovery_legacy_close_receipt_identity_changed")
    records = read_verified_market_daily_receipt_records_on_connection(
        conn,
        receipt,
        schema="market_meta",
    )
    if records is None:
        raise ValueError("recovery_legacy_close_receipt_integrity_failed")
    return (
        receipt,
        {str(record[0]): record for record in records},
        {
            "trade_date": day,
            "provider_name": provider,
            "receipt_fingerprint": receipt["receipt_fingerprint"],
            "dataset_fingerprint": receipt["dataset_fingerprint"],
            "stored_receipt_fingerprint": stable_json_fingerprint(dict(row)),
            "full_receipt_verified": True,
        },
    )


def _quarantined_legacy_close_evidence(conn, run, commands):
    """Dispose an unpublished batch without adopting misdated legacy closes.

    The existing typed migration refuses a legacy close when independently
    dated bars disagree. Retain that raw record unchanged and unadopted. Both
    exact dates must have real, fully replayed receipts predating this failure;
    a nearby quote event is never presented as the old record's provenance.
    """
    if "market_meta" not in {row[1] for row in conn.execute("PRAGMA database_list")}:
        raise ValueError("recovery_legacy_market_evidence_required")
    metadata = json.loads(run["metadata_json"])
    receipt_cache = {}
    facts = []
    publication = _control(conn, "valuation_snapshot_publication")
    current_quotes = []
    current_id = None
    if publication and publication.get("status") == "ready":
        current_id = publication.get("snapshot_id")
        row = conn.execute(
            "SELECT quotes_json FROM valuation_snapshots WHERE snapshot_id=?",
            (current_id,),
        ).fetchone()
        if row is None:
            raise ValueError("recovery_legacy_current_consumer_unknown")
        current_quotes = json.loads(row[0])
        if not isinstance(current_quotes, list):
            raise ValueError("recovery_legacy_current_consumer_unknown")
    for command in commands:
        day, previous_day = command.daily_close_date, command.previous_close_date
        if (
            command.asset_type != "stock"
            or not day
            or not previous_day
            or date.fromisoformat(previous_day) >= date.fromisoformat(day)
            or command.daily_close_source != "market_bar_close"
            or command.quote_source != "market_bar_close"
            or not command.provider_name
            or command.provider_name != metadata.get("market_data_provider")
            or day != metadata.get("target_trade_date")
        ):
            raise ValueError("recovery_legacy_close_disposition_unsupported")
        old = conn.execute(
            "SELECT * FROM daily_close_snapshots WHERE symbol=? AND trade_date=?",
            (command.symbol, day),
        ).fetchone()
        typed = conn.execute(
            "SELECT * FROM daily_close_snapshots_v2 WHERE symbol=? AND instrument_type='stock' AND trade_date=?",
            (command.symbol, day),
        ).fetchone()
        if (
            old is None
            or old["asset_class"] != "stock"
            or old["source"] != "reported_previous_close"
            or typed is not None
            or _recovery_instant(old["captured_at"])
            >= _recovery_instant(run["started_at"])
            or old["close_price"] != command.previous_close
            or old["close_price"] == command.daily_close_price
        ):
            raise ValueError("recovery_legacy_prior_close_changed_or_adopted")
        selected = []
        for session in (previous_day, day):
            key = (session, command.provider_name)
            if key not in receipt_cache:
                receipt_cache[key] = _legacy_close_receipt(
                    conn,
                    day=session,
                    provider=command.provider_name,
                    finished_at=run["finished_at"],
                )
            receipt, bars, reference = receipt_cache[key]
            bar = bars.get(command.symbol)
            expected = (
                old["close_price"]
                if session == previous_day
                else command.daily_close_price
            )
            if bar is None or bar[5] != expected:
                raise ValueError("recovery_legacy_dated_close_revision_or_missing")
            if session == day and (
                receipt["receipt_fingerprint"] != metadata.get("receipt_fingerprint")
                or receipt["dataset_fingerprint"]
                != metadata.get("market_dataset_fingerprint")
                or receipt["receipt_fingerprint"]
                != command.metadata.get("receipt_fingerprint")
                or receipt["dataset_fingerprint"]
                != command.metadata.get("market_dataset_fingerprint")
            ):
                raise ValueError("recovery_legacy_candidate_receipt_binding_changed")
            selected.append(
                {"receipt": reference, "instrument_type": "stock", "bar": list(bar)}
            )
        latest = conn.execute(
            "SELECT * FROM latest_quotes WHERE symbol=? AND asset_type='stock'",
            (command.symbol,),
        ).fetchone()
        consumers = [dict(latest)] if latest is not None else []
        consumers.extend(
            quote
            for quote in current_quotes
            if isinstance(quote, dict)
            and quote.get("symbol") == command.symbol
            and quote.get("asset_type") == "stock"
        )
        for quote in consumers:
            extra = quote.get("metadata") or json.loads(
                quote.get("metadata_json") or "{}"
            )
            prior_date = quote.get("previous_close_date") or extra.get(
                "previous_close_date"
            )
            if prior_date == day and quote.get("previous_close") == old["close_price"]:
                raise ValueError("recovery_legacy_close_still_consumed")
        facts.append(
            {
                "legacy_record": dict(old),
                "legacy_record_fingerprint": stable_json_fingerprint(dict(old)),
                "typed_close_adopted": False,
                "dated_receipts": selected,
                "current_consumers_fingerprint": stable_json_fingerprint(consumers),
            }
        )
    if not facts:
        raise ValueError("recovery_legacy_close_disposition_unsupported")
    return {
        "disposition": "preserve_unverified_legacy_record_without_market_fact_authority",
        "migration_rule": "karkinos.daily_close_identity_migration.v2",
        "current_valuation_snapshot_id": current_id,
        "facts": facts,
        "financial_facts_changed": False,
        "historical_point_in_time_status_upgraded": False,
    }


def unpublished_quote_recovery_plan(
    conn: sqlite3.Connection, *, incident_refs: Sequence[str] | None = None
) -> dict[str, Any]:
    """Prove terminal failed refreshes never entered the financial publication lane.

    Staged provider results are proposals. A terminal, audited failed/partial
    refresh can be discarded when the complete requested scope and every staged
    payload are known, and no canonical quote or immutable valuation references
    its run. Quote materialization records a snapshot and event before its close
    in the same transaction; potentially orphaned closes during the attempt are
    nevertheless rejected. Actual price-conflict publications remain fenced.

    The caller owns a consistent read or immediate write transaction. This is
    neither a price adjudication nor permission to alter any market/account fact.
    """
    incidents = {
        item.get("incident_ref") or publication_incident_ref(item): item
        for item in unresolved_publications(conn)
    }
    requested = sorted(set(incident_refs) if incident_refs is not None else incidents)
    if len(requested) > 10_000 or any(not isinstance(key, str) for key in requested):
        raise ValueError("recovery_incident_selection_invalid")
    run_ids = {
        str(incidents[key].get("quote_fetch_run_id") or "")
        for key in requested
        if key in incidents
    }
    references = _published_run_references(conn, run_ids)
    repairs, blocked = [], []
    original_quote_events = None
    for identity in requested:
        try:
            incident = incidents.get(identity)
            if incident is None or publication_incident_ref(incident) != identity:
                raise ValueError("recovery_incident_identity_changed")
            publication_failure = (
                incident.get("reason") == "quote_batch_publication_failed"
                and incident.get("error_type") == "ValueError"
                and incident.get("daily_close_conflict") is None
            )
            if incident.get("status") != "failed" or not (
                incident.get("reason") == "quote_fetch_run_not_fully_successful"
                or publication_failure
            ):
                raise ValueError(
                    "recovery_financial_publication_requires_fact_resolution"
                )
            run_id = str(incident.get("quote_fetch_run_id") or "")
            row = conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError("recovery_run_missing")
            run = dict(row)
            if (
                run["status"] not in {"failed", "partial_success", "error"}
                or not run["finished_at"]
                or incident.get("quote_fetch_run_status") != run["status"]
            ):
                raise ValueError("recovery_run_not_terminal_failed_refresh")
            legacy_completion = (
                "failed_at" not in incident and "incident_ref" not in incident
            )
            if (
                not legacy_completion
                and incident.get("failed_at") != run["finished_at"]
            ):
                raise ValueError("recovery_terminal_time_mismatch")
            scope = quote_run_scope(conn, run_id, require_exact=True)
            if scope is None or scope != incident.get("scope"):
                raise ValueError("recovery_requested_scope_changed")
            if references.get(run_id):
                raise ValueError("recovery_run_has_published_financial_facts")
            metadata = json.loads(run["metadata_json"] or "{}")
            completion = metadata.get("quote_publication_completion_fingerprint")
            if not (legacy_completion and completion is None) and (
                not isinstance(completion, str)
                or len(completion.removeprefix("sha256:")) != 64
                or any(
                    c not in "0123456789abcdef"
                    for c in completion.removeprefix("sha256:")
                )
            ):
                raise ValueError("recovery_completion_binding_missing")
            events = conn.execute(
                "SELECT id,payload_json,timestamp FROM event_log WHERE event_type='task_run.completed' "
                "AND source='quote_fetch_runs' AND source_ref=? ORDER BY id",
                (run_id,),
            ).fetchall()
            if len(events) != 1:
                raise ValueError("recovery_completion_event_ambiguous")
            event = json.loads(events[0][1])
            if (
                not isinstance(event, dict)
                or events[0][2] != run["finished_at"]
                or any(
                    event.get(key) != run[key]
                    for key in (
                        "run_id",
                        "started_at",
                        "finished_at",
                        "provider",
                        "asset_type",
                        "symbol_count",
                        "success_count",
                        "failure_count",
                        "cache_hit_count",
                        "status",
                        "error_message",
                    )
                )
                or event.get("metadata") != metadata
            ):
                raise ValueError("recovery_completion_event_changed")
            staged = conn.execute(
                "SELECT * FROM quote_ingestion_items WHERE run_id=? ORDER BY symbol,asset_type,id",
                (run_id,),
            ).fetchall()
            if publication_failure:
                if not (
                    run["status"] == "failed"
                    and run["failure_count"] == 0
                    and run["success_count"] == len(staged) == run["symbol_count"]
                    and metadata.get("valuation_snapshot_publication") == "failed"
                ):
                    raise ValueError(
                        "recovery_financial_publication_requires_fact_resolution"
                    )
                count_basis, expected_staged_symbols = (
                    "rolled_back_estimate_batch",
                    None,
                )
            else:
                count_basis, expected_staged_symbols = _refresh_count_basis(
                    run, metadata, scope, len(staged)
                )
            manifest, close_refs = [], []
            seen = set()
            commands = []
            for item in staged:
                payload = json.loads(item["payload_json"])
                command = QuoteIngestionCommand.from_dict(payload)
                canonical = command.to_dict()
                fingerprint = stable_json_fingerprint(payload)
                canonical_fingerprint = stable_json_fingerprint(canonical)
                legacy_identity_default = (
                    legacy_completion
                    and command.asset_type == payload.get("asset_type")
                    and "identity_provenance" not in payload
                    and canonical
                    == {
                        **payload,
                        "identity_provenance": "explicit_canonical",
                        "metadata": {
                            **payload.get("metadata", {}),
                            "identity_provenance": "explicit_canonical",
                        },
                    }
                )
                key = (command.asset_type, command.symbol)
                if (
                    command.fetch_run_id != run_id
                    or key in seen
                    or list(key) not in scope
                    or command.symbol != item["symbol"]
                    or command.asset_type != item["asset_type"]
                    or (
                        fingerprint != canonical_fingerprint
                        and not legacy_identity_default
                    )
                    or item["payload_fingerprint"] != fingerprint
                ):
                    raise ValueError("recovery_staged_payload_changed")
                seen.add(key)
                commands.append(command)
                manifest.append(
                    {
                        "id": item["id"],
                        "payload_fingerprint": fingerprint,
                        "canonical_command_fingerprint": canonical_fingerprint,
                        "staged_record_fingerprint": stable_json_fingerprint(
                            dict(item)
                        ),
                    }
                )
                if command.daily_close_date is not None:
                    close = conn.execute(
                        "SELECT * FROM daily_close_snapshots_v2 "
                        "WHERE symbol=? AND instrument_type=? AND trade_date=?",
                        (command.symbol, command.asset_type, command.daily_close_date),
                    ).fetchone()
                    if close is not None:
                        if (
                            _recovery_instant(run["started_at"])
                            <= _recovery_instant(close["captured_at"])
                            <= _recovery_instant(run["finished_at"])
                        ):
                            raise ValueError("recovery_unbound_close_during_failed_run")
                        if (
                            publication_failure
                            and "price"
                            in quote_authority_conflict_fields(
                                {"price": close["close_price"]},
                                {"price": command.daily_close_price},
                            )
                        ):
                            raise ValueError("recovery_prior_close_requires_resolution")
                        close_refs.append(stable_json_fingerprint(dict(close)))
            if (
                expected_staged_symbols is not None
                and {item[1] for item in seen} != expected_staged_symbols
            ):
                raise ValueError("recovery_manual_staged_group_mismatch")
            proof = {
                "incident_ref": identity,
                "classification": "unpublished_failed_refresh",
                "counter_basis": count_basis,
                "run_fingerprint": stable_json_fingerprint(run),
                "completed_event_id": events[0][0],
                "completed_event_fingerprint": stable_json_fingerprint(event),
                "completion_binding": "legacy_exact_completed_event"
                if legacy_completion
                else "completion_fingerprint_and_event",
                "staged_payloads": manifest,
                "existing_close_fingerprints": close_refs,
                "published_quote_and_valuation_reference_count": 0,
            }
            if publication_failure:
                proof["classification"] = (
                    "unpublished_estimate_rejected_below_published_nav"
                )
                prior_nav = _rejected_estimate_evidence(conn, run, commands)
                if prior_nav:
                    proof["prior_published_nav"] = prior_nav
                elif legacy_completion:
                    proof["classification"] = (
                        "unpublished_legacy_batch_with_nonauthoritative_reported_previous_close"
                    )
                    proof["legacy_close_disposition"] = (
                        _quarantined_legacy_close_evidence(conn, run, commands)
                    )
                else:
                    proof["classification"] = (
                        "unpublished_duplicate_quote_proposal_rejected"
                    )
                    if original_quote_events is None:
                        original_quote_events = _original_quote_events(conn)
                    proof["prior_quote_events"] = _rejected_duplicate_evidence(
                        run, commands, original_quote_events
                    )
            repairs.append(
                {**proof, "proof_fingerprint": stable_json_fingerprint(proof)}
            )
        except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as exc:
            blocked.append({"incident_ref": identity, "blockers": [str(exc)]})
    return {
        "schema_version": "karkinos.unpublished_quote_refresh_recovery.v1",
        "status": "ready"
        if repairs and not blocked
        else "partially_ready"
        if repairs
        else "blocked",
        "repairs": repairs,
        "blocked_incidents": blocked,
        "proof_fingerprint": stable_json_fingerprint(repairs),
        "changes_financial_facts": False,
        "authorizes_execution": False,
    }


def discard_proven_unpublished_quote_refreshes(
    database_path: str | Path,
    *,
    incident_refs: Sequence[str],
    expected_proof_fingerprint: str,
    actor: str,
    confirmation: str,
    now: datetime,
    market_database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retire only reviewed, re-proven incidents and preserve their exact audit.

    Revalidation and receipt/incident writes share one SQLite write lock with
    quote publication. No staged proposal or financial/account fact is changed.
    """
    if confirmation != UNPUBLISHED_RECOVERY_CONFIRMATION or not actor.strip():
        raise ValueError("recovery_requires_explicit_discard_confirmation")
    if (
        now.tzinfo is None
        or not incident_refs
        or len(set(incident_refs)) != len(incident_refs)
    ):
        raise ValueError("recovery_command_invalid")
    request = {
        "incident_refs": sorted(incident_refs),
        "proof_fingerprint": expected_proof_fingerprint,
        "actor": actor,
        "confirmation": confirmation,
    }
    command_id = stable_json_fingerprint(request)
    with closing(connect_sqlite(database_path)) as conn:
        conn.row_factory = sqlite3.Row
        attach_recovery_market_database(conn, market_database_path)
        conn.execute("BEGIN IMMEDIATE")
        replay = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type=? AND source_ref=?",
            (_RECOVERY_EVENT, command_id),
        ).fetchone()
        if replay is not None:
            result = json.loads(replay[0])
            if result.get("request") != request:
                raise ValueError("recovery_receipt_identity_changed")
            return {**result, "reused": True}
        plan = unpublished_quote_recovery_plan(conn, incident_refs=incident_refs)
        if (
            plan["status"] != "ready"
            or plan["proof_fingerprint"] != expected_proof_fingerprint
        ):
            raise ValueError("recovery_proof_changed_or_not_ready")
        failures = unresolved_publications(conn)
        selected = set(incident_refs)
        resolved = [
            item
            for item in failures
            if (item.get("incident_ref") or publication_incident_ref(item)) in selected
        ]
        if len(resolved) != len(selected):
            raise ValueError("recovery_incident_selection_changed")
        stamp = now.astimezone(timezone.utc).isoformat()
        result = {
            "schema_version": plan["schema_version"],
            "request": request,
            "resolved_incidents": resolved,
            "proofs": plan["repairs"],
            "resolved_count": len(resolved),
            "completed_at": stamp,
            "changes_financial_facts": False,
            "authorizes_execution": False,
        }
        insert_event_sync(
            conn,
            event_type=_RECOVERY_EVENT,
            timestamp=stamp,
            entity_type="quote_publication_recovery",
            entity_id=command_id,
            source="valuation_publication_recovery",
            source_ref=command_id,
            payload=result,
        )
        _save(
            conn,
            [
                item
                for item in failures
                if (item.get("incident_ref") or publication_incident_ref(item))
                not in selected
            ],
            stamp,
        )
        conn.commit()
        return {**result, "reused": False}


def record_publication_recovery(
    conn: sqlite3.Connection, failure: dict[str, Any], *, updated_at: str
) -> None:
    failures = unresolved_publications(conn)
    run_id = failure.get("quote_fetch_run_id")
    failures = [item for item in failures if item.get("quote_fetch_run_id") != run_id]
    incident = {
        **failure,
        "scope": quote_run_scope(conn, run_id),
        "failed_at": updated_at,
    }
    failures.append({**incident, "incident_ref": publication_incident_ref(incident)})
    _save(conn, failures, updated_at)


def assert_quote_publication_not_started(conn: sqlite3.Connection, run_id: str) -> None:
    if any(
        item.get("quote_fetch_run_id") == run_id
        for item in unresolved_publications(conn)
    ):
        raise RuntimeError("quote publication already unresolved")


def begin_quote_publication(
    conn: sqlite3.Connection, *, run_id: str, updated_at: str
) -> str:
    """Persist a scope fence before any candidate fact can be materialized."""
    assert_quote_publication_not_started(conn, run_id)
    pending = {
        "status": "pending",
        "reason": "quote_batch_publication_incomplete",
        "quote_fetch_run_id": run_id,
        "scope": quote_run_scope(conn, run_id),
        "started_at": updated_at,
    }
    ref = publication_incident_ref(pending)
    _save(
        conn,
        [*unresolved_publications(conn), {**pending, "incident_ref": ref}],
        updated_at,
    )
    return ref


def complete_quote_publication(
    conn: sqlite3.Connection, *, attempt_ref: str, updated_at: str
) -> None:
    """Only the transaction that began this attempt may commit its success."""
    failures = unresolved_publications(conn)
    pending = [item for item in failures if item.get("incident_ref") == attempt_ref]
    if len(pending) != 1 or pending[0].get("status") != "pending":
        raise RuntimeError("quote publication attempt identity drift")
    _save(
        conn,
        [item for item in failures if item.get("incident_ref") != attempt_ref],
        updated_at,
    )


def publication_incident_ref(incident: dict[str, Any]) -> str:
    return "sha256:" + stable_json_fingerprint(
        {key: value for key, value in incident.items() if key != "incident_ref"}
    )


def preserve_publication_recovery(conn: sqlite3.Connection, *, updated_at: str) -> None:
    """Retain incidents until a fact-bound repair receipt can prove resolution.

    A complete valuation or a later successful request is not such a receipt:
    neither proves that a prior session's conflicting close has been repaired.
    """
    failures = unresolved_publications(conn)
    if not failures:
        return
    _save(conn, failures, updated_at)


def _save(conn: sqlite3.Connection, failures: list[dict[str, Any]], at: str) -> None:
    conn.execute(
        "INSERT INTO runtime_controls(key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
        "updated_at=excluded.updated_at",
        (RECOVERY_KEY, json.dumps({"failures": failures}, sort_keys=True), at),
    )
