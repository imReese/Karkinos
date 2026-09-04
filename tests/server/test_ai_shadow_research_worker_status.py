from __future__ import annotations

import pytest

from server.services.ai_shadow_research_worker_status import (
    build_ai_shadow_research_worker_status,
)


@pytest.mark.unit
def test_worker_status_scopes_provider_call_flag_to_the_status_read() -> None:
    class Store:
        def list_recent(self, *, limit: int = 20) -> list[dict[str, object]]:
            assert limit == 20
            return [
                {
                    "run_id": "automation:provider-job:completed",
                    "run_date": "2026-09-04",
                    "status": "completed",
                    "payload": {
                        "available_at": "2026-09-04T10:00:00+00:00",
                        "deadline_at": "2026-09-07T01:00:00+00:00",
                        "last_result": {
                            "run_status": "completed",
                            "provider_call_count": 10,
                        },
                    },
                }
            ]

    result = build_ai_shadow_research_worker_status(Store())

    assert result["provider_call_performed"] is False
    assert result["provider_call_performed_scope"] == "this_status_read"
    assert result["latest_job"]["last_result"]["provider_call_count"] == 10
