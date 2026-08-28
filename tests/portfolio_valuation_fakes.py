"""Explicit read-only valuation publication contracts for portfolio test doubles."""

from __future__ import annotations

from typing import Any

from server.services.valuation_snapshot import build_current_valuation_snapshot


def _current_quote_rows(db: Any) -> list[dict[str, Any]]:
    """Adapt legacy fixture readers to the persisted-current quote contract."""

    for reader_name in ("list_latest_quotes_sync", "get_latest_quotes_sync"):
        reader = getattr(db, reader_name, None)
        if callable(reader):
            return [dict(row) for row in (reader() or [])]
    return []


def publish_current_valuation(db: Any) -> dict[str, Any]:
    """Freeze one explicit publication marker for a fake database's facts."""

    snapshot = build_current_valuation_snapshot(db, persist=False)
    marker = {
        "status": "ready",
        "snapshot_id": snapshot["snapshot_id"],
        "valuation_snapshot_status": snapshot["status"],
        "as_of": snapshot["as_of"],
        "quote_fetch_run_id": None,
    }
    db._published_valuation_marker = marker
    return marker


def published_valuation_control(db: Any, key: str) -> dict[str, Any] | None:
    """Return only the fake's already-frozen immutable publication marker."""

    if key != "valuation_snapshot_publication":
        return None
    marker = getattr(db, "_published_valuation_marker", None)
    return None if marker is None else dict(marker)


class PublishedValuationFakeDbMixin:
    """Make a fake DB explicitly assert that its current facts are published."""

    def list_quote_selection_candidates_sync(self) -> list[dict[str, Any]]:
        """Expose fixture facts through the production persisted-current port."""

        return _current_quote_rows(self)

    def get_runtime_control_sync(self, key: str) -> dict[str, Any] | None:
        if not hasattr(self, "_published_valuation_marker"):
            publish_current_valuation(self)
        return published_valuation_control(self, key)


def bind_published_valuation(db: Any) -> Any:
    """Attach the explicit marker contract to a mutable namespace fake."""

    if not callable(getattr(db, "list_quote_selection_candidates_sync", None)):
        db.list_quote_selection_candidates_sync = lambda: _current_quote_rows(db)
    publish_current_valuation(db)
    db.get_runtime_control_sync = lambda key: published_valuation_control(db, key)
    return db


__all__ = [
    "PublishedValuationFakeDbMixin",
    "bind_published_valuation",
    "publish_current_valuation",
    "published_valuation_control",
]
