"""Composition root for after-close AI shadow research automation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from data.store import DataStore
from server.bootstrap import resolve_data_dir
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.services.reviewed_fee_schedule import resolve_reviewed_fee_schedule


def compose_ai_shadow_research_automation_service(
    state: Any,
    *,
    research_service_builder: Callable[[bool], Any],
    service_type: Callable[..., Any],
) -> Any:
    """Initialize persistence and wire all explicit runtime dependencies."""

    store = ShadowResearchStore(Path(getattr(state.db, "_path")))
    store.init()
    return service_type(
        state=state,
        store=store,
        data_store=DataStore(resolve_data_dir()),
        research_service_builder=research_service_builder,
        reviewed_fee_schedule_resolver=lambda **kwargs: resolve_reviewed_fee_schedule(
            state, **kwargs
        ),
    )
