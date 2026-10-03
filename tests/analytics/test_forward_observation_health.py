"""Configured health uses real canonical outcomes without inventing financial books."""

from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from analytics.forward_observation_health import (
    FORWARD_OBSERVATION_HEALTH_POLICY_ID,
    evaluate_forward_observation_health,
    validate_forward_observation_health_policy,
)
from analytics.forward_target_outcomes import evaluate_forward_target_outcome
from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation

AS_OF = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
POLICY = {
    "mode": "pause_on_breach",
    "window_intervals": 3,
    "minimum_eligible_intervals": 2,
    "minimum_mean_relative_price_response": "-0.05",
}


def instant(day, hour=8):
    return datetime.combine(day, time(hour), timezone.utc)


def bar(symbol, day, close):
    value = Decimal(close)
    return DailyBarObservation(
        instrument=InstrumentKey(symbol, InstrumentType.STOCK),
        session_date=day,
        event_time=instant(day, 7),
        available_at=instant(day, 7) + timedelta(minutes=1),
        captured_at=instant(day, 7) + timedelta(minutes=2),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(100000),
        amount=Decimal(1000000),
    )


def observation(day, *, horizon=1, weights=None, closes=("11", "12")):
    decision = date(2026, 9, day)
    reference, end = (
        decision + timedelta(days=1),
        decision + timedelta(days=1 + horizon),
    )
    weights = (
        weights
        if weights is not None
        else {"600000": Decimal("0.5"), "600001": Decimal(0)}
    )
    publication = {
        "id": f"publication-{day}",
        "decision_session": decision.isoformat(),
        "published_at": instant(decision).isoformat(),
        "dataset_id": "sha256:" + "a" * 64,
        "payload": {
            "reference_session": reference.isoformat(),
            "end_session": end.isoformat(),
            "horizon_sessions": horizon,
            "target_weights": {key: str(value) for key, value in weights.items()},
        },
    }
    bars = [
        bar(symbol, session, value)
        for symbol, closing in zip(weights, closes, strict=True)
        for session, value in ((reference, "10"), (end, closing))
    ]
    outcome = {
        "publication_id": publication["id"],
        "horizon": horizon,
        "dataset_id": "sha256:" + "b" * 64,
        "measured_at": (instant(end) + timedelta(seconds=1)).isoformat(),
        "payload": evaluate_forward_target_outcome(
            publication_at=instant(decision),
            reference_session=reference,
            end_session=end,
            target_weights=weights,
            bars=bars,
            evaluated_at=instant(end),
        ),
    }
    return publication, outcome


def evaluate(pairs, *, policy=POLICY, outcomes=None, **changes):
    return evaluate_forward_observation_health(
        publications=[pair[0] for pair in pairs],
        outcomes=outcomes if outcomes is not None else [pair[1] for pair in pairs],
        policy=policy,
        **{"evaluated_at": NOW, "market_as_of": AS_OF, **changes},
    )


def test_explicit_policy_and_exact_price_metric_do_not_create_nav_or_alpha_claims():
    result = evaluate([observation(1), observation(2)])
    assert result["status"] == "threshold_breached"
    assert result["action"] == "pause_observation"
    assert result["mean_relative_price_response"] == "-0.1"
    assert result["counts"]["eligible"] == 2
    assert result["is_nav_return"] is False
    assert result["includes_fees"] is False
    assert result["includes_distributions"] is False
    assert result["corporate_action_coverage_complete"] is False
    assert all(
        item["corporate_action_status"] == "coverage_missing"
        for item in result["interval_results"]
    )
    assert result["input_fingerprint"].startswith("sha256:")


def test_observer_and_exact_threshold_equality_never_pause():
    pairs = [observation(1), observation(2)]
    observed = evaluate(pairs, policy={**POLICY, "mode": "observe_only"})
    assert observed["status"] == "threshold_breached"
    assert observed["action"] == "none"
    equal = evaluate(
        pairs, policy={**POLICY, "minimum_mean_relative_price_response": "-0.1"}
    )
    assert equal["status"] == "within_rule"
    assert equal["action"] == "none"


def test_nonoverlap_slots_do_not_change_when_missing_outcome_arrives():
    pairs = [observation(day, horizon=2) for day in (1, 2, 3, 4, 5)]
    missing = evaluate(
        pairs, outcomes=[pairs[1][1], pairs[2][1], pairs[3][1], pairs[4][1]]
    )
    complete = evaluate(pairs)
    assert (
        missing["selected_publication_ids"]
        == complete["selected_publication_ids"]
        == ["publication-1", "publication-3", "publication-5"]
    )
    assert missing["counts"]["missing_matured"] == 1
    assert missing["counts"]["eligible"] == 2
    assert missing["status"] == "unavailable"
    assert missing["action"] == "none"
    assert complete["action"] == "pause_observation"


def test_window_counts_reserved_slots_including_zero_exposure_without_backfill():
    pairs = [observation(day) for day in (1, 2, 3, 4)]
    pairs[-1] = observation(4, weights={"600000": Decimal(0), "600001": Decimal(0)})
    result = evaluate(pairs, policy={**POLICY, "window_intervals": 2})
    assert result["selected_publication_ids"] == ["publication-3", "publication-4"]
    assert result["counts"]["zero_exposure"] == 1
    assert result["counts"]["eligible"] == 1
    assert result["status"] == "insufficient_evidence"
    assert result["action"] == "none"


def test_pending_is_not_missing_or_a_zero_return():
    pair = observation(29)
    result = evaluate([pair], outcomes=[])
    assert result["status"] == "waiting"
    assert result["counts"]["pending"] == 1
    assert result["counts"]["missing_matured"] == 0
    assert result["mean_relative_price_response"] is None


def test_data_failure_preserves_diagnostic_metric_without_performance_action():
    result = evaluate([observation(1), observation(2)], data_available=False)
    assert result["status"] == "unavailable"
    assert result["mean_relative_price_response"] == "-0.1"
    assert result["action"] == "none"


def evidence(pair, *, ex_date, **event_changes):
    outcome = pair[1]["payload"]
    return {
        "schema_version": "karkinos.corporate_action_evidence.v1",
        "status": "observed",
        "coverage_status": "provider_reported_only",
        "start_date": "2026-01-01",
        "end_date": outcome["end_session"],
        "available_at": outcome["evaluated_at"],
        "captured_at": outcome["evaluated_at"],
        "matched_event_count": 40,
        "events": [
            {
                "symbol": "600001",
                "instrument_type": "stock",
                "div_proc": "实施",
                "ex_date": ex_date,
                "cash_div_tax": "0.1",
                "cash_div": "0.09",
                "stk_div": "0",
                "stk_bo_rate": "0",
                "stk_co_rate": "0",
                **event_changes,
            }
        ],
    }


@pytest.mark.parametrize(
    "boundary,excluded", [("reference_session", False), ("end_session", True)]
)
def test_known_exdate_excludes_interval_only_after_reference_close(boundary, excluded):
    pairs = [observation(1), observation(2)]
    pair = pairs[0]
    pair[1]["payload"]["corporate_action_evidence"] = evidence(
        pair, ex_date=pair[1]["payload"][boundary]
    )
    result = evaluate(pairs)
    assert result["counts"]["corporate_action_excluded"] == int(excluded)
    assert result["counts"]["eligible"] == 2 - int(excluded)
    assert result["action"] == ("none" if excluded else "pause_observation")


def test_share_action_on_zero_target_still_confounds_equal_weight_benchmark():
    pairs = [observation(1), observation(2)]
    pair = pairs[0]
    pair[1]["payload"]["corporate_action_evidence"] = evidence(
        pair,
        ex_date=pair[1]["payload"]["end_session"],
        cash_div_tax="0",
        cash_div="0",
        stk_div="0.1",
        stk_bo_rate="0.1",
    )
    result = evaluate(pairs)
    assert result["counts"]["corporate_action_excluded"] == 1
    assert result["action"] == "none"


@pytest.mark.parametrize(
    "changes",
    [
        {"ex_date": None},
        {
            "cash_div_tax": None,
            "cash_div": None,
            "stk_div": None,
            "stk_bo_rate": None,
            "stk_co_rate": None,
        },
        {"div_proc": "预案"},
    ],
)
def test_unresolved_action_terms_block_performance_action(changes):
    pairs = [observation(1), observation(2)]
    pair = pairs[0]
    action = evidence(pair, ex_date=pair[1]["payload"]["end_session"])
    action["events"][0].update(changes)
    pair[1]["payload"]["corporate_action_evidence"] = action
    result = evaluate(pairs)
    assert result["status"] == "unavailable"
    assert result["counts"]["unresolved"] == 1
    assert result["action"] == "none"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p, o: o["payload"]["observations"][0].update(price_return="NaN"),
        lambda p, o: o["payload"]["observations"][0]["end"].update(close="Infinity"),
        lambda p, o: o["payload"]["observations"][0]["end"].update(close="0"),
        lambda p, o: o["payload"].update(
            target_weights={"600000": "0.4", "600001": "0"}
        ),
        lambda p, o: o["payload"].update(includes_fees=True),
        lambda p, o: o.update(measured_at="2026-10-01T08:00:00Z"),
        lambda p, o: o["payload"]["observations"].pop(),
        lambda p, o: p["payload"].update(
            target_weights={"600000": "-1", "600001": "0"}
        ),
        lambda p, o: p.update(published_at="2026-09-02T09:30:00+08:00"),
        lambda p, o: o["payload"]["observations"].append(None),
        lambda p, o: p.update(published_at="2026-09-01T06:59:59Z"),
        lambda p, o: p["payload"].update(published_at="2026-09-01T07:59:59Z"),
        lambda p, o: o["payload"].update(policy_id="unknown-outcome-policy"),
        lambda p, o: o["payload"].update(blockers=["missing_evidence"]),
        lambda p, o: o.update(horizon=True),
        lambda p, o: o["payload"]["observations"][0].update(instrument_type="unknown"),
        lambda p, o: o["payload"]["observations"][0].update(
            weighted_price_response="0"
        ),
        lambda p, o: o["payload"].update(weighted_price_response="0"),
    ],
)
def test_malformed_or_future_evidence_is_unavailable_and_never_pauses(mutation):
    pairs = [observation(1), observation(2)]
    mutation(*pairs[0])
    result = evaluate(pairs)
    assert result["status"] == "unavailable"
    assert result["action"] == "none"


@pytest.mark.parametrize(
    "change",
    [
        {"window_intervals": 0},
        {"minimum_eligible_intervals": 4},
        {"mode": "automatic_profit"},
        {"minimum_mean_relative_price_response": "NaN"},
        {"window_intervals": True},
        {"policy_id": "changed"},
        {"unknown": True},
    ],
)
def test_policy_has_explicit_validated_parameters_and_no_numeric_defaults(change):
    with pytest.raises(ValueError, match="^health_policy_invalid$"):
        validate_forward_observation_health_policy({**POLICY, **change})
    with pytest.raises(ValueError, match="^health_policy_invalid$"):
        evaluate([], policy={**POLICY, **change})


def test_normalized_policy_revalidates_and_missing_configuration_stays_disabled():
    normalized = validate_forward_observation_health_policy(POLICY)
    assert normalized["policy_id"] == FORWARD_OBSERVATION_HEALTH_POLICY_ID
    assert validate_forward_observation_health_policy(normalized) == normalized
    assert evaluate([], policy=None)["status"] == "not_configured"
    with pytest.raises(ValueError, match="health_policy_invalid"):
        validate_forward_observation_health_policy({"mode": "observe_only"})


def test_decimal_context_cannot_change_threshold_or_average():
    pairs = [observation(1), observation(2)]
    expected = evaluate(pairs)
    with localcontext() as context:
        context.prec = 2
        assert evaluate(copy.deepcopy(pairs)) == expected


def test_proposed_outcomes_and_persisted_outcomes_share_health_identity():
    pairs = [observation(1), observation(2)]
    persisted = evaluate(pairs)
    proposed = copy.deepcopy(pairs)
    for _, outcome in proposed:
        outcome.pop("measured_at")
    assert evaluate(proposed) == persisted
    proposed[0][1]["payload"]["evaluated_at"] = "2026-10-01T08:00:00Z"
    rejected = evaluate(proposed)
    assert rejected["status"] == "unavailable"
    assert rejected["action"] == "none"


def test_unknown_market_boundary_never_infers_date_or_returns_from_wall_clock():
    result = evaluate([observation(1), observation(2)], market_as_of=None)
    assert result["status"] == "unavailable"
    assert result["action"] == "none"
    assert result["market_as_of"] is None
    assert result["mean_relative_price_response"] is None
    assert result["blockers"] == ["health_market_boundary_unavailable"]
    assert evaluate([], policy=None, market_as_of=None)["status"] == "not_configured"


def test_future_stored_measurement_remains_invalid_despite_not_entering_fingerprint():
    pairs = [observation(1), observation(2)]
    previous = evaluate(pairs)
    pairs[0][1]["measured_at"] = "2026-10-01T08:00:00Z"
    result = evaluate(pairs)
    assert result["input_fingerprint"] == previous["input_fingerprint"]
    assert result["status"] == "unavailable"
    assert result["action"] == "none"
    assert result["blockers"] == ["health_outcome_in_future"]
