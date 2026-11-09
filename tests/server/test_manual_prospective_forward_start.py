"""Manual startup uses the real isolated observation/book journey on synthetic data."""

from datetime import datetime, time, timezone

import pytest

from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.research import research_observation_automation as automation
from tests.server import test_reserved_forward_observation as original
from tests.server.test_research_observation_inputs import DAYS
from tests.server.test_research_observations_journey import journey  # noqa: F401


@pytest.mark.parametrize(
    "exercise_forward,scenario",
    [
        (False, "normal"),
        ("main", "normal"),
        (False, "late_seed"),
        (False, "late_partial"),
    ],
)
def test_manual_start_keeps_real_fresh_cash_and_published_first_session(
    journey, tmp_path, monkeypatch, exercise_forward, scenario
):
    # Reuse the existing full product fixture. Only the separately-tested source
    # resolver is replaced; observation, publication, paper accounting and their
    # temporary SQLite owners are real.
    actual_start = automation.start_reserved_champion_observation
    current = journey[2]
    prepared = []
    calls = []

    async def manual_start(db, objects, **kwargs):
        binding = StrategyResearchAuditStore(db.path).get_sealed_test(
            kwargs["reservation_id"]
        )["evidence"]["reservation"]
        if calls and not prepared:
            from server.services.research.datasets import ensure_forward_seed_for_source

            seed = ensure_forward_seed_for_source(db, None, source={}, now=current[0])
            assert seed["status"] == "ready"
            binding.update(
                source_kind="manual_research",
                forward_seed_dataset_id=seed["dataset_id"],
                first_evaluation_session=DAYS[5].isoformat(),
            )
            prepared.append(True)
        if (scenario == "late_seed" and len(calls) == 1) or (
            scenario == "late_partial" and len(calls) == 2
        ):
            current[0] = datetime.combine(DAYS[5], time(1, 30), timezone.utc)
            before = journey[1].repository.list()
            blocked = await actual_start(
                db, objects, **kwargs, clock=lambda: current[0]
            )
            assert (
                blocked["last_blocker"]["code"]
                == "manual_research_first_opening_missed"
            )
            assert journey[1].repository.list() == before
            assert all(not item["publications"] for item in before)
            raise RuntimeError("verified_late_start_refusal")
        calls.append(True)
        # Deliberately supply a stale captured now; manual uses only this fresh clock.
        kwargs["clock"] = lambda: current[0]
        return await actual_start(db, objects, **kwargs)

    monkeypatch.setattr(original, "start_reserved_champion_observation", manual_start)
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_manual_source_binding",
        lambda *_a, **_k: None,
    )
    if scenario == "normal":
        original.test_reserved_start_waits_then_resumes_exact_cash_fees_and_keeps_owner_pause(
            journey, tmp_path, monkeypatch, exercise_forward, True
        )
    else:
        with pytest.raises(RuntimeError, match="verified_late_start_refusal"):
            original.test_reserved_start_waits_then_resumes_exact_cash_fees_and_keeps_owner_pause(
                journey, tmp_path, monkeypatch, exercise_forward, True
            )
    assert prepared
