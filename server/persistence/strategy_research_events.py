"""Append-only hash-chain repository operations for strategy research."""

from __future__ import annotations

import json

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.persistence.strategy_research_errors import StrategyResearchOperationalError


class StrategyResearchEventRepositoryMixin:
    def append_event(
        self,
        entity_id: str,
        event_type: str,
        payload: JsonObject,
        *,
        created_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            previous = conn.execute(
                """
                SELECT event_hash FROM ai_strategy_research_events
                WHERE entity_id=? ORDER BY rowid DESC LIMIT 1
                """,
                (entity_id,),
            ).fetchone()
            previous_hash = str(previous["event_hash"]) if previous else None
            identity = {
                "entity_id": entity_id,
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous_hash,
                "created_at": created_at,
            }
            event_hash = content_fingerprint(identity)
            event_id = "ai-strategy-event-" + event_hash[:24]
            conn.execute(
                """
                INSERT OR IGNORE INTO ai_strategy_research_events
                (event_id, entity_id, event_type, payload_json, previous_hash,
                 event_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    entity_id,
                    event_type,
                    canonical_json(payload),
                    previous_hash,
                    event_hash,
                    created_at,
                ),
            )

    def verify_events(self, entity_id: str) -> tuple[bool, list[str]]:
        """Replay one isolated research event chain without mutating storage."""
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT event_type, payload_json, previous_hash, event_hash,
                           created_at
                    FROM ai_strategy_research_events WHERE entity_id=?
                    """,
                    (entity_id,),
                ).fetchall()
        except StrategyResearchOperationalError:
            return False, ["strategy_event_store_missing"]
        if not rows:
            return False, ["strategy_event_chain_missing"]
        errors: list[str] = []
        hashes = {str(row["event_hash"]) for row in rows}
        children: dict[str | None, list[str]] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                errors.append("strategy_event_payload_invalid")
                continue
            previous_hash = (
                str(row["previous_hash"]) if row["previous_hash"] is not None else None
            )
            expected = content_fingerprint(
                {
                    "entity_id": entity_id,
                    "event_type": str(row["event_type"]),
                    "payload": payload,
                    "previous_hash": previous_hash,
                    "created_at": str(row["created_at"]),
                }
            )
            event_hash = str(row["event_hash"])
            if expected != event_hash:
                errors.append("strategy_event_hash_mismatch")
            if previous_hash is not None and previous_hash not in hashes:
                errors.append("strategy_event_previous_hash_missing")
            children.setdefault(previous_hash, []).append(event_hash)
        if len(children.get(None, [])) != 1:
            errors.append("strategy_event_root_count_invalid")
        if any(len(items) != 1 for key, items in children.items() if key is not None):
            errors.append("strategy_event_chain_branch")
        return not errors, sorted(set(errors))
