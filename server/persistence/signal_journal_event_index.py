"""One-pass event lookup index for the persisted signal journal."""

from __future__ import annotations

from typing import Any

SignalJournalEventIndex = dict[
    str,
    dict[Any, tuple[int, dict[str, Any]]],
]


def index_signal_journal_events(
    events: list[dict[str, Any]],
) -> SignalJournalEventIndex:
    """Index one newest-first event list for repeated journal lookups."""

    index: SignalJournalEventIndex = {
        key: {}
        for key in (
            "decision_review_by_signal",
            "signal_review_by_ref",
            "manual_order_by_signal",
            "manual_order_by_action",
            "order_by_signal",
            "order_by_action",
            "risk_by_ref",
            "action_by_ref",
            "fallback_by_signal",
            "fallback_by_action",
        )
    }
    for ordinal, event in enumerate(events):
        source = event.get("source")
        source_ref = event.get("source_ref")
        payload = event.get("payload", {})
        nested_payload = payload.get("payload")
        if not isinstance(nested_payload, dict):
            nested_payload = {}

        if source == "decision_outcome_reviews":
            _index_first(
                index["decision_review_by_signal"],
                payload.get("signal_id"),
                ordinal,
                event,
            )
        if source == "signal_reviews":
            _index_first(
                index["signal_review_by_ref"],
                source_ref,
                ordinal,
                event,
            )
        if source in {"manual_orders", "orders"} and (
            event.get("event_type") == "order.status_changed"
        ):
            prefix = "manual_order" if source == "manual_orders" else "order"
            for source_signal_id in (
                payload.get("source_signal_id"),
                nested_payload.get("source_signal_id"),
            ):
                _index_first(
                    index[f"{prefix}_by_signal"],
                    source_signal_id,
                    ordinal,
                    event,
                )
            _index_first(
                index[f"{prefix}_by_action"],
                _string_key(nested_payload.get("action_id")),
                ordinal,
                event,
            )
        if source == "risk_decisions":
            _index_first(
                index["risk_by_ref"],
                source_ref,
                ordinal,
                event,
                include_none=True,
            )
        if source == "action_tasks":
            _index_first(
                index["action_by_ref"],
                source_ref,
                ordinal,
                event,
                include_none=True,
            )
        for source_signal_id in (
            payload.get("source_signal_id"),
            nested_payload.get("source_signal_id"),
        ):
            _index_first(
                index["fallback_by_signal"],
                source_signal_id,
                ordinal,
                event,
            )
        _index_first(
            index["fallback_by_action"],
            _string_key(nested_payload.get("action_id")),
            ordinal,
            event,
        )
    return index


def latest_indexed_signal_journal_event(
    *,
    signal_id: int,
    action_ref: str | None,
    risk_ref: str | None,
    event_index: SignalJournalEventIndex,
) -> dict[str, Any] | None:
    prioritized = (
        ("decision_review_by_signal", signal_id),
        ("signal_review_by_ref", str(signal_id)),
    )
    for category, key in prioritized:
        candidate = event_index[category].get(key)
        if candidate is not None:
            return candidate[1]

    for prefix in ("manual_order", "order"):
        candidate = _earliest_indexed_event(
            event_index[f"{prefix}_by_signal"].get(signal_id),
            event_index[f"{prefix}_by_action"].get(action_ref),
        )
        if candidate is not None:
            return candidate

    return _earliest_indexed_event(
        event_index["risk_by_ref"].get(risk_ref),
        event_index["action_by_ref"].get(action_ref),
        event_index["fallback_by_signal"].get(signal_id),
        event_index["fallback_by_action"].get(action_ref),
    )


def _index_first(
    target: dict[Any, tuple[int, dict[str, Any]]],
    key: Any,
    ordinal: int,
    event: dict[str, Any],
    *,
    include_none: bool = False,
) -> None:
    if key is not None or include_none:
        try:
            target.setdefault(key, (ordinal, event))
        except TypeError:
            pass


def _string_key(value: Any) -> str | None:
    return str(value) if value is not None else None


def _earliest_indexed_event(
    *candidates: tuple[int, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    available = [candidate for candidate in candidates if candidate is not None]
    return min(available, key=lambda candidate: candidate[0])[1] if available else None


__all__ = [
    "SignalJournalEventIndex",
    "index_signal_journal_events",
    "latest_indexed_signal_journal_event",
]
