"""Explicit calendar timing revision; synthetic fixtures, no investment evidence."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from analytics.sealed_holdout import build_sealed_partition
from server.contracts.content_identity import content_fingerprint
from server.contracts.recommendation_publication import (
    FINAL_CALENDAR_AT_EVALUATION,
    validate_final_statistical_policy,
)
from server.services.research import research_final_evaluation as owner
from tests.server.test_manual_research_prospective import manual, reserve  # noqa: F401
from tests.server.test_research_final_evaluation import harness  # noqa: F401
from tests.server.test_research_final_statistical_policy import final_policy  # noqa: F401

CALENDAR = "server.services.market.market_universe_automation.verified_trading_dates"


def opt_in(binding, t):
    profile = binding["simulation_policy"]["statistical_policy"]
    profile["calendar_verification_timing"] = FINAL_CALENDAR_AT_EVALUATION
    binding.pop("effective_checkpoint", None)
    binding["checkpoint_resolution"] = {
        "calendar_verification_timing": FINAL_CALENDAR_AT_EVALUATION,
        "last_session_on_or_before": profile["decision_checkpoint"],
    }
    profile["comparator_bindings"] = owner._statistical_comparator_bindings(
        binding, t.h.selection, t.h.store, policy=profile
    )
    binding["simulation_policy"]["statistical_policy_fingerprint"] = (
        content_fingerprint(profile)
    )
    return binding


def cross_year(m, *, revised):
    m.start, m.end = "2026-11-04", "2027-02-13"
    m.now[0] = datetime.fromisoformat("2026-11-03T12:00:00+00:00")
    m.sim["statistical_policy"]["decision_checkpoint"] = m.end
    binding = deepcopy(m.t.binding)
    partition = build_sealed_partition(
        research_start=m.t.h.selection.start_date,
        research_end=m.t.h.selection.end_date,
        prospective_start=m.start,
        sealed_end=m.end,
    )
    binding.update(
        partition=partition.to_json_dict(),
        partition_fingerprint=partition.partition_fingerprint,
        first_evaluation_session=m.start,
        effective_checkpoint="2027-02-12",
        simulation_policy=m.sim,
    )
    if revised:
        opt_in(binding, m.t)
    else:
        profile = m.sim["statistical_policy"]
        profile["comparator_bindings"] = owner._statistical_comparator_bindings(
            binding, m.t.h.selection, m.t.h.store, policy=profile
        )
        m.sim["statistical_policy_fingerprint"] = content_fingerprint(profile)


def partial_calendar(_db, *, start_date, end_date):
    if end_date >= "2027-01-01":
        raise ValueError("research_calendar_incomplete:2027:market_calendar_missing")
    day = datetime.fromisoformat(start_date)
    result = []
    while day.date().isoformat() <= end_date:
        if day.weekday() < 5:
            result.append(day.date().isoformat())
        day += timedelta(days=1)
    return result


@pytest.mark.asyncio
async def test_explicit_revision_reserves_without_future_year_and_freezes_rule(
    manual, monkeypatch
):
    m = manual
    cross_year(m, revised=True)
    monkeypatch.setattr(CALENDAR, partial_calendar)
    frozen = deepcopy(m.sim)
    row = await reserve(m)
    binding = row["evidence"]["reservation"]
    assert "effective_checkpoint" not in binding
    assert binding["checkpoint_resolution"]["last_session_on_or_before"] == m.end
    assert binding["simulation_policy"] == frozen
    assert binding["error_budget"]["attempt_count"] == 2
    # Later calendar availability cannot rebind identities or spend another alpha.
    monkeypatch.setattr(CALENDAR, lambda *_a, **_k: [m.start, "2027-02-10"])
    assert await reserve(m) == row
    assert binding["simulation_policy"] == frozen


@pytest.mark.asyncio
async def test_original_profile_still_requires_complete_calendar(manual, monkeypatch):
    cross_year(manual, revised=False)
    monkeypatch.setattr(CALENDAR, partial_calendar)
    with pytest.raises(ValueError, match="calendar_incomplete:2027"):
        await reserve(manual)
    assert (
        manual.t.h.store.manual_research_champion_reservation(vars(manual.refs)) is None
    )


@pytest.mark.asyncio
async def test_actual_first_session_missing_still_prevents_allocation(
    manual, monkeypatch
):
    cross_year(manual, revised=True)

    def missing(*_a, **_kw):
        raise ValueError("research_calendar_incomplete:2026:market_calendar_missing")

    monkeypatch.setattr(CALENDAR, missing)
    with pytest.raises(ValueError, match="calendar_incomplete:2026"):
        await reserve(manual)
    assert (
        manual.t.h.store.manual_research_champion_reservation(vars(manual.refs)) is None
    )


def compare(t, *, curves=None, calendar_db=None):
    return owner._compare_final_curves(
        t.binding,
        curves or t.curves,
        seed=t.reserved["sealed_test_id"],
        research_store=t.h.store,
        selection=t.h.selection,
        calendar_db=calendar_db,
    )


@pytest.mark.asyncio
async def test_final_requires_complete_calendar_and_checks_every_observation(
    final_policy, monkeypatch
):
    t = final_policy
    opt_in(t.binding, t)
    frozen = deepcopy(t.binding)
    with pytest.raises(ValueError, match="final_calendar_required"):
        compare(t)

    def unavailable(*_a, **_kw):
        raise ValueError("research_calendar_incomplete")

    monkeypatch.setattr(CALENDAR, unavailable)
    with pytest.raises(ValueError, match="calendar_incomplete"):
        compare(t, calendar_db=t.h.db)
    monkeypatch.setattr(CALENDAR, lambda *_a, **_k: t.days)
    result = compare(t, calendar_db=t.h.db)
    assert result["status"] == "pass"
    assert result["effective_checkpoint"] == t.days[-1]
    assert t.binding == frozen
    assert result["policy"]["minimum_observations"] == 60
    assert result["policy"]["minimum_effective_blocks"] == 12
    assert result["policy"]["maximum_drawdown"] == "0.15"
    assert len(result["comparisons"]) == 11
    assert all(
        x["one_sided_alpha"] == pytest.approx(0.05 / 11) for x in result["comparisons"]
    )
    for replacement in (None, "2026-01-01T00:00:00"):
        curves = deepcopy(t.curves)
        if replacement is None:
            curves["candidate"].pop(15)
        else:
            curves["candidate"][15][0] = replacement
        with pytest.raises(ValueError, match="calendar_observation_mismatch"):
            compare(t, curves=curves, calendar_db=t.h.db)


@pytest.mark.asyncio
async def test_complete_calendar_with_only_59_sessions_cannot_pass(
    final_policy, monkeypatch
):
    opt_in(final_policy.binding, final_policy)
    days = final_policy.days[1:]
    monkeypatch.setattr(CALENDAR, lambda *_a, **_k: days)
    curves = deepcopy(final_policy.curves)
    curves["candidate"] = curves["candidate"][1:]
    curves["comparators"] = {k: v[1:] for k, v in curves["comparators"].items()}
    result = compare(final_policy, curves=curves, calendar_db=final_policy.h.db)
    assert result["status"] != "pass"
    assert result["policy"]["minimum_observations"] == 60


@pytest.mark.asyncio
async def test_calendar_revision_rejects_unknown_policy_and_checkpoint_tampering(
    final_policy,
):
    opt_in(final_policy.binding, final_policy)
    profile = final_policy.binding["simulation_policy"]["statistical_policy"]
    validate_final_statistical_policy(profile, content_fingerprint(profile))
    for mutation, error in (
        (
            {"calendar_verification_timing": "skip"},
            "statistical_frozen_profile_mismatch",
        ),
        ({"schema_version": None}, "statistical_policy_version_unsupported"),
    ):
        bad = {**profile, **mutation}
        with pytest.raises(ValueError, match=error):
            validate_final_statistical_policy(bad, content_fingerprint(bad))
    for mutation in (
        {"effective_checkpoint": "2026-03-17"},
        {"checkpoint_resolution": {"last_session_on_or_before": "2026-03-19"}},
    ):
        bad = {**final_policy.binding, **mutation}
        with pytest.raises(ValueError, match="frozen_checkpoint_mismatch"):
            owner._verified_statistical_inputs(
                bad, final_policy.h.selection, final_policy.h.store
            )


@pytest.mark.asyncio
async def test_canonical_policy_upgrade_preserves_grant_and_omits_v1_rolling_defaults(
    final_policy,
):
    from server.contracts.ai_shadow_research_automation import (
        SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    )
    from tests.server.test_research_simulation_policy import (
        Commands,
        minimal_simulation,
    )

    commands = Commands(final_policy.h.db)
    patch = {"enabled": False, "confirmation": SHADOW_RESEARCH_PAUSE_CONFIRMATION}
    first = commands.update_policy(
        {**patch, "simulation_validation": minimal_simulation()}
    )["simulation_validation"]
    opt_in(final_policy.binding, final_policy)
    profile = deepcopy(final_policy.binding["simulation_policy"]["statistical_policy"])
    upgraded = commands.update_policy(
        {**patch, "simulation_validation": {**first, "statistical_policy": profile}}
    )["simulation_validation"]
    assert upgraded["grant_id"] == first["grant_id"]
    assert upgraded["generation"] != first["generation"]
    assert upgraded["max_final_tests"] == 1
    assert upgraded["total_error_budget"] == "0.05"
    assert upgraded["statistical_policy"] == profile
    unchanged = commands.update_policy(
        {
            **patch,
            "simulation_validation": {
                "expected_generation": upgraded["generation"],
                "updated_by": upgraded["updated_by"],
            },
        }
    )["simulation_validation"]
    assert unchanged == upgraded
    with pytest.raises(ValueError, match="publication_statistical_method_unsupported"):
        commands.update_policy(
            {
                **patch,
                "simulation_validation": {
                    "expected_generation": upgraded["generation"],
                    "statistical_policy": {"schema_version": profile["schema_version"]},
                },
            }
        )
    assert commands.get_policy().simulation_validation == upgraded
