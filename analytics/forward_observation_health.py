"""Configured checks on forward price responses, never account or alpha returns."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from analytics.forward_target_outcomes import FORWARD_TARGET_OUTCOME_POLICY_ID

FORWARD_OBSERVATION_HEALTH_POLICY_ID = "karkinos.research.forward_price_health.v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_LIMITATIONS = [
    "Relative raw-price responses are not NAV, executable returns, or proof of alpha decay.",
    "Fees, taxes, distributions, fills and market-factor attribution are not modeled.",
    "Corporate-action evidence is provider-reported only; missing or empty observations do not prove absence of actions, including ETF distributions.",
    "Configured thresholds are monitoring choices, not universal profitability or statistical significance criteria.",
]


def evaluate_forward_observation_health(
    *,
    publications: Sequence[Mapping],
    outcomes: Sequence[Mapping],
    policy: Mapping | None,
    evaluated_at: datetime,
    market_as_of: date | None,
    data_available: bool = True,
) -> dict[str, Any]:
    """Select temporal slots before eligibility so missing evidence cannot reselect.

    Each slot is one published interval. Adjacent intervals may share their
    endpoint close, but their return periods cannot overlap. The rolling window
    contains the last configured number of matured slots, including exclusions.
    """
    result: dict[str, Any] = {
        "policy_id": FORWARD_OBSERVATION_HEALTH_POLICY_ID,
        "status": "not_configured" if policy is None else "unavailable",
        "action": "none",
        "evaluated_at": None,
        "market_as_of": None,
        "data_available": data_available is True,
        "counts": dict.fromkeys(
            (
                "scheduled_matured",
                "pending",
                "missing_matured",
                "zero_exposure",
                "corporate_action_excluded",
                "unresolved",
                "eligible",
            ),
            0,
        ),
        "mean_relative_price_response": None,
        "threshold": None,
        "selected_publication_ids": [],
        "interval_results": [],
        "input_fingerprint": None,
        "blockers": [],
        "return_basis": "unadjusted_price_only",
        "is_nav_return": False,
        "includes_fees": False,
        "includes_distributions": False,
        "assumes_fills": False,
        "corporate_action_coverage_complete": False,
        "limitations": list(_LIMITATIONS),
    }
    if policy is None:
        return result
    settings = validate_forward_observation_health_policy(policy)
    try:
        evaluated_at = _instant(evaluated_at)
        if market_as_of is None:
            result.update(
                evaluated_at=evaluated_at.isoformat(),
                policy=settings,
                threshold=settings["minimum_mean_relative_price_response"],
                data_available=False,
                blockers=["health_market_boundary_unavailable"],
            )
            return result
        market_as_of = _day(market_as_of)
        if type(data_available) is not bool or _close(market_as_of) > evaluated_at:
            raise ValueError("health_evaluation_boundary_invalid")
        result.update(
            evaluated_at=evaluated_at.isoformat(),
            market_as_of=market_as_of.isoformat(),
            policy=settings,
            threshold=settings["minimum_mean_relative_price_response"],
        )
        result["input_fingerprint"] = _fingerprint(
            {
                "publications": publications,
                "outcomes": [_outcome_input(item) for item in outcomes],
                "policy": settings,
                "evaluated_at": evaluated_at.isoformat(),
                "market_as_of": market_as_of.isoformat(),
                "data_available": data_available,
            }
        )
        _sequence(publications)
        _sequence(outcomes)
        slots = _slots(publications, evaluated_at)
        by_id = {slot["id"]: slot for slot in slots["all"]}
        indexed = {}
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                raise ValueError("health_outcome_invalid")
            publication_id = outcome["publication_id"]
            if publication_id not in by_id or publication_id in indexed:
                raise ValueError("health_outcome_identity_invalid")
            if (
                "measured_at" in outcome
                and _instant(outcome["measured_at"]) > evaluated_at
            ):
                raise ValueError("health_outcome_in_future")
            if (
                not isinstance(outcome.get("dataset_id"), str)
                or not outcome["dataset_id"]
            ):
                raise ValueError("health_outcome_dataset_missing")
            indexed[publication_id] = outcome
        matured = [slot for slot in slots["selected"] if slot["end"] <= market_as_of]
        selected = matured[-settings["window_intervals"] :]
        counts = result["counts"]
        counts["scheduled_matured"] = len(selected)
        counts["pending"] = len(slots["selected"]) - len(matured)
        result["selected_publication_ids"] = [slot["id"] for slot in selected]
        responses = []
        for slot in selected:
            item = {
                "publication_id": slot["id"],
                "reference_session": slot["reference"].isoformat(),
                "end_session": slot["end"].isoformat(),
                "status": "missing_matured",
                "relative_price_response": None,
            }
            outcome = indexed.get(slot["id"])
            if outcome is None:
                counts["missing_matured"] += 1
            else:
                try:
                    response, gross, assessment = _response(slot, outcome, evaluated_at)
                    item["outcome_fingerprint"] = _fingerprint(_outcome_input(outcome))
                    item["corporate_action_status"] = assessment
                    if gross == 0:
                        item["status"] = "zero_exposure"
                        counts["zero_exposure"] += 1
                    elif assessment == "known_exdate_overlap":
                        item["status"] = "corporate_action_excluded"
                        counts["corporate_action_excluded"] += 1
                    elif assessment == "unresolved":
                        raise ValueError("health_corporate_action_unresolved")
                    else:
                        item.update(
                            status="eligible",
                            relative_price_response=_decimal_text(response),
                        )
                        counts["eligible"] += 1
                        responses.append(response)
                except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                    item.update(status="unresolved", blocker=_reason(exc))
                    counts["unresolved"] += 1
            result["interval_results"].append(item)
        if responses:
            result["mean_relative_price_response"] = _decimal_text(
                sum(responses, Fraction()) / len(responses)
            )
        if not data_available or counts["missing_matured"] or counts["unresolved"]:
            result["status"] = "unavailable"
            result["blockers"] = (
                (["health_current_data_unavailable"] if not data_available else [])
                + (
                    ["health_matured_outcome_missing"]
                    if counts["missing_matured"]
                    else []
                )
                + (["health_outcome_unresolved"] if counts["unresolved"] else [])
            )
        elif not selected:
            result["status"] = "waiting"
        elif counts["eligible"] < settings["minimum_eligible_intervals"]:
            result["status"] = "insufficient_evidence"
        else:
            mean = sum(responses, Fraction()) / len(responses)
            breached = mean < Fraction(
                Decimal(settings["minimum_mean_relative_price_response"])
            )
            result["status"] = "threshold_breached" if breached else "within_rule"
            if breached and settings["mode"] == "pause_on_breach":
                result["action"] = "pause_observation"
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        result.update(status="unavailable", action="none", blockers=[_reason(exc)])
    return result


def validate_forward_observation_health_policy(policy: Mapping) -> dict[str, Any]:
    """Reject invalid configuration before its immutable observation is started."""
    try:
        return _policy(policy)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise ValueError("health_policy_invalid") from None


def _policy(value):
    fields = {
        "mode",
        "window_intervals",
        "minimum_eligible_intervals",
        "minimum_mean_relative_price_response",
    }
    constants = {
        "policy_id": FORWARD_OBSERVATION_HEALTH_POLICY_ID,
        "metric": "target_minus_equal_weight_universe_price_response",
        "comparison": "mean_strictly_less_than_threshold",
        "interval_selection": "chronological_nonoverlapping_slots_before_eligibility",
    }
    if (
        not isinstance(value, Mapping)
        or not fields <= set(value)
        or set(value) - fields - set(constants)
        or any(
            key in value and value[key] != expected
            for key, expected in constants.items()
        )
    ):
        raise ValueError("health_policy_invalid")
    window, minimum = value["window_intervals"], value["minimum_eligible_intervals"]
    if (
        value["mode"] not in {"observe_only", "pause_on_breach"}
        or type(window) is not int
        or type(minimum) is not int
        or not 1 <= minimum <= window
    ):
        raise ValueError("health_policy_invalid")
    return {
        **value,
        **constants,
        "minimum_mean_relative_price_response": str(
            _number(value["minimum_mean_relative_price_response"])
        ),
    }


def _slots(publications, evaluated_at):
    parsed, seen = [], set()
    for publication in publications:
        if not isinstance(publication, Mapping):
            raise ValueError("health_publication_invalid")
        identity, payload = publication["id"], publication["payload"]
        if (
            not isinstance(identity, str)
            or not identity
            or identity in seen
            or not isinstance(payload, Mapping)
            or not isinstance(publication.get("dataset_id"), str)
            or not publication["dataset_id"]
        ):
            raise ValueError("health_publication_identity_invalid")
        seen.add(identity)
        published_at = _instant(publication["published_at"])
        reference, end = (
            _day(payload["reference_session"]),
            _day(payload["end_session"]),
        )
        decision = _day(publication["decision_session"])
        horizon = payload["horizon_sessions"]
        weights = _weights(payload["target_weights"])
        if (
            not _close(decision) <= published_at <= evaluated_at
            or published_at >= datetime.combine(reference, time(9, 30), _SHANGHAI)
            or (
                "published_at" in payload
                and _instant(payload["published_at"]) != published_at
            )
            or not decision < reference < end
            or type(horizon) is not int
            or horizon < 1
        ):
            raise ValueError("health_publication_boundary_invalid")
        parsed.append(
            {
                "id": identity,
                "decision": decision,
                "published_at": published_at,
                "reference": reference,
                "end": end,
                "horizon": horizon,
                "weights": weights,
            }
        )
    parsed.sort(key=lambda item: (item["decision"], item["published_at"], item["id"]))
    if (
        len({item["decision"] for item in parsed}) != len(parsed)
        or len({item["horizon"] for item in parsed}) > 1
        or len({tuple(sorted(item["weights"])) for item in parsed}) > 1
    ):
        raise ValueError("health_publication_scope_conflict")
    selected = []
    for slot in parsed:
        if not selected or slot["reference"] >= selected[-1]["end"]:
            selected.append(slot)
    return {"all": parsed, "selected": selected}


def _response(slot, outcome, evaluated_at):
    payload = outcome["payload"]
    if (
        not isinstance(payload, Mapping)
        or payload.get("status") != "measured"
        or payload.get("policy_id") != FORWARD_TARGET_OUTCOME_POLICY_ID
        or payload.get("blockers") != []
    ):
        raise ValueError("health_outcome_not_measured")
    if (
        type(outcome["horizon"]) is not int
        or outcome["horizon"] != slot["horizon"]
        or _day(payload["reference_session"]) != slot["reference"]
        or _day(payload["end_session"]) != slot["end"]
        or _instant(payload["publication_at"]) != slot["published_at"]
        or _weights(payload["target_weights"]) != slot["weights"]
    ):
        raise ValueError("health_outcome_binding_mismatch")
    at = _instant(payload["evaluated_at"])
    if (
        not slot["published_at"] <= at <= evaluated_at
        or (
            "measured_at" in outcome
            and not at <= _instant(outcome["measured_at"]) <= evaluated_at
        )
        or payload.get("return_basis") != "unadjusted_price_only"
        or any(
            payload.get(flag) is not False
            for flag in (
                "is_nav_return",
                "includes_fees",
                "includes_distributions",
                "assumes_fills",
            )
        )
    ):
        raise ValueError("health_outcome_basis_invalid")
    observations = payload["observations"]
    _sequence(observations)
    values = {}
    for item in observations:
        symbol = item["symbol"]
        if (
            symbol not in slot["weights"]
            or symbol in values
            or item.get("instrument_type") not in {"stock", "etf"}
            or _number(item["target_weight"]) != slot["weights"][symbol]
        ):
            raise ValueError("health_outcome_universe_mismatch")
        for key, session in (("reference", slot["reference"]), ("end", slot["end"])):
            bar = item[key]
            if (
                _day(bar["session_date"]) != session
                or _instant(bar["event_time"]).astimezone(_SHANGHAI).date() != session
                or not _close(session)
                <= _instant(bar["event_time"])
                <= _instant(bar["available_at"])
                <= _instant(bar["captured_at"])
                <= at
            ):
                raise ValueError("health_outcome_bar_not_available")
        reference, end = (
            _number(item["reference"]["close"]),
            _number(item["end"]["close"]),
        )
        if reference <= 0 or end <= 0:
            raise ValueError("health_outcome_price_invalid")
        change = Fraction(end) / Fraction(reference) - 1
        if _number(item["price_return"]) != Decimal(_decimal_text(change)) or _number(
            item["weighted_price_response"]
        ) != Decimal(_decimal_text(change * Fraction(slot["weights"][symbol]))):
            raise ValueError("health_outcome_price_response_mismatch")
        values[symbol] = change
    if set(values) != set(slot["weights"]):
        raise ValueError("health_outcome_universe_mismatch")
    gross = sum((Fraction(weight) for weight in slot["weights"].values()), Fraction())
    weighted = sum(
        (
            Fraction(slot["weights"][symbol]) * change
            for symbol, change in values.items()
        ),
        Fraction(),
    )
    if _number(payload["weighted_price_response"]) != Decimal(_decimal_text(weighted)):
        raise ValueError("health_outcome_weighted_response_mismatch")
    benchmark = sum(values.values(), Fraction()) / len(values)
    return (
        weighted - benchmark,
        gross,
        _corporate_actions(payload.get("corporate_action_evidence"), slot, at),
    )


def _corporate_actions(evidence, slot, evaluated_at):
    if evidence is None:
        return "coverage_missing"
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("schema_version") != "karkinos.corporate_action_evidence.v1"
        or evidence.get("status") != "observed"
        or evidence.get("coverage_status") != "provider_reported_only"
    ):
        return "unresolved"
    if (
        not _day(evidence["start_date"])
        <= slot["reference"]
        < slot["end"]
        <= _day(evidence["end_date"])
        or not _instant(evidence["available_at"])
        <= _instant(evidence["captured_at"])
        <= evaluated_at
    ):
        return "unresolved"
    _sequence(evidence["events"])
    known = False
    for event in evidence["events"]:
        if event["symbol"] not in slot["weights"]:
            continue
        if event.get("ex_date") is None:
            if event.get("div_proc") == "实施":
                return "unresolved"
            continue
        if not slot["reference"] < _day(event["ex_date"]) <= slot["end"]:
            continue
        if event.get("instrument_type") != "stock" or event.get("div_proc") != "实施":
            return "unresolved"
        terms = {
            name: None if event.get(name) is None else _number(event[name])
            for name in (
                "cash_div_tax",
                "cash_div",
                "stk_div",
                "stk_bo_rate",
                "stk_co_rate",
            )
        }
        if any(value is not None and value < 0 for value in terms.values()):
            return "unresolved"
        if any(value is not None and value > 0 for value in terms.values()):
            known = True
        elif terms["cash_div_tax"] != 0 or terms["stk_div"] != 0:
            return "unresolved"
    return "known_exdate_overlap" if known else "no_reported_overlap"


def _weights(value):
    if not isinstance(value, Mapping) or not value:
        raise ValueError("health_target_weights_invalid")
    result = {}
    for symbol, weight in value.items():
        if not isinstance(symbol, str) or not symbol or symbol.strip() != symbol:
            raise ValueError("health_target_weights_invalid")
        result[symbol] = _number(weight)
        if not 0 <= result[symbol] <= 1:
            raise ValueError("health_target_weights_invalid")
    if sum((Fraction(weight) for weight in result.values()), Fraction()) > 1:
        raise ValueError("health_target_weights_invalid")
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("health_number_invalid")
    number = Decimal(str(value))
    if not number.is_finite() or abs(number.adjusted()) > 100:
        raise ValueError("health_number_invalid")
    return number


def _day(value):
    value = date.fromisoformat(value) if isinstance(value, str) else value
    if type(value) is not date:
        raise ValueError("health_date_invalid")
    return value


def _instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("health_timestamp_invalid")
    return value.astimezone(timezone.utc)


def _close(day):
    return datetime.combine(day, time(15), _SHANGHAI)


def _sequence(value):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("health_evidence_sequence_invalid")


def _decimal_text(value):
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return format(Decimal(value.numerator) / Decimal(value.denominator), "f")


def _outcome_input(value):
    if not isinstance(value, Mapping):
        raise ValueError("health_outcome_invalid")
    return {key: item for key, item in value.items() if key != "measured_at"}


def _fingerprint(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )


def _reason(exc):
    text = str(exc)
    return text if text.startswith("health_") else "health_evidence_invalid"
