"""Persist process liveness separately from job success or financial readiness."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timezone


async def run_with_presence(controls, key: str, owner: str, work) -> None:
    def write(status):
        controls.set_value(
            key,
            {
                "status": status,
                "owner": owner,
                "as_of": datetime.now(timezone.utc).isoformat(),
                "release_sha": os.environ.get("KARKINOS_RELEASE_SHA"),
            },
        )

    async def heartbeat():
        while True:
            write("ready")
            await asyncio.sleep(20)

    try:
        async with asyncio.TaskGroup() as group:
            pulse = group.create_task(heartbeat())

            async def run():
                try:
                    await work
                finally:
                    pulse.cancel()

            group.create_task(run())
    finally:
        # Stale timestamps also report worker loss when the database is locked.
        with contextlib.suppress(Exception):
            write("stopped")
