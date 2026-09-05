"""Process bootstrap for the isolated shadow-research worker."""

from __future__ import annotations

import os
import uuid
from typing import Any

from server.composition.ai_shadow_research_automation import (
    compose_ai_shadow_research_worker,
)
from server.db import AppDatabase
from server.dependencies import AppState
from server.persistence.runtime_controls import RuntimeControlRepository
from server.services.ai_shadow_research_worker import AiShadowResearchWorker
from server.services.trading_controls import TradingControlState
from server.workers.presence import run_with_presence


async def run_ai_shadow_research_worker(config: Any) -> None:
    """Initialize one non-HTTP process and consume research jobs forever."""

    db = AppDatabase()
    await db.init()
    state = AppState()
    state.config = config
    state.db = db
    state.trading_controls = TradingControlState(db=db)
    worker = compose_ai_shadow_research_worker(
        state,
        service_type=AiShadowResearchWorker,
    )
    await run_with_presence(
        RuntimeControlRepository(db.path),
        "research_worker_heartbeat",
        f"research-worker:{os.getpid()}:{uuid.uuid4().hex}",
        worker.run_forever(),
    )
