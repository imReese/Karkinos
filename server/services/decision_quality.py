"""Evidence-bound daily Decision Quality Score and immutable captures.

The current projection is calculated only from the canonical Decision payload.
Capturing it appends audit evidence; it never mutates financial facts, risk
decisions, execution state, or authority.
"""

from __future__ import annotations

from typing import Any

from data.market_data import is_fund_estimate_quote_source
from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.decision_quality import (
    DECISION_QUALITY_CAPTURE_VERSION,
    DECISION_QUALITY_CONFIRMATION,
    DECISION_QUALITY_TARGET_VERSION,
    DecisionQualityCaptureRejected,
    DecisionQualityCaptureRequest,
    DecisionQualityCaptureResult,
    DecisionQualityDimension,
    DecisionQualityReplay,
    DecisionQualityReport,
    DecisionQualityTarget,
    DecisionQualityTargetDrift,
    DecisionQualityView,
    StoredDecisionQualityCapture,
)
from server.contracts.idempotency import IdempotencyConflict
from server.persistence.decision_quality import DecisionQualityStore

_TRUSTED_MARKET_STATUSES = {"confirmed", "live"}
_TRUSTED_CANDIDATE_DATA_STATUSES = {
    "complete",
    "confirmed",
    "fresh",
    "live",
    "pass",
}
_CHECKED_RISK_STATUSES = {"blocked", "passed"}


class DecisionQualityService:
    """Build, capture, replay, and aggregate daily decision-quality evidence."""

    def __init__(self, *, store: DecisionQualityStore, now) -> None:
        self._store = store
        self._now = now

    def view(self, decision_payload: dict[str, Any]) -> DecisionQualityView:
        target = build_decision_quality_target(decision_payload)
        report = self.report()
        current_capture = next(
            (
                item
                for item in self._latest_by_day()
                if item.decision_date == target.decision_date
            ),
            None,
        )
        return DecisionQualityView(
            current_target=target,
            report=report,
            current_day_capture=current_capture,
            current_binding_valid=(
                current_capture.target_fingerprint == target.fingerprint
                if current_capture is not None
                else None
            ),
        )

    def capture(
        self,
        decision_payload: dict[str, Any],
        request: DecisionQualityCaptureRequest,
    ) -> DecisionQualityCaptureResult:
        existing = self._store.get_by_idempotency_key(request.idempotency_key)
        target = build_decision_quality_target(decision_payload)
        if existing is not None:
            if (
                existing.request_fingerprint != request.fingerprint
                or existing.target_fingerprint != request.expected_target_fingerprint
            ):
                raise IdempotencyConflict(
                    "decision quality idempotency key was reused with different input"
                )
            return self._result(existing, target=target, reused=True)
        if request.expected_target_fingerprint != target.fingerprint:
            raise DecisionQualityTargetDrift(
                "decision quality evidence changed; preview the current target again"
            )
        capture, reused = self._store.record(
            target=target,
            request=request,
            captured_at=self._now(),
        )
        return self._result(capture, target=target, reused=reused)

    def get(
        self,
        snapshot_id: str,
        decision_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capture = self._store.get(snapshot_id)
        result = {
            "capture": capture.to_dict(),
            "audit_replay": self._store.verify_replay(snapshot_id).to_dict(),
            "persisted_facts_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }
        if decision_payload is not None:
            current = build_decision_quality_target(decision_payload)
            result["current_target"] = current.to_dict()
            result["target_binding_valid"] = (
                capture.target_fingerprint == current.fingerprint
            )
        return result

    def replay(self, snapshot_id: str) -> DecisionQualityReplay:
        return self._store.verify_replay(snapshot_id)

    def report(self) -> DecisionQualityReport:
        captures = self._store.list()
        latest = self._latest_by_day(captures)
        invalid = [
            item.snapshot_id
            for item in latest
            if not self._store.verify_replay(item.snapshot_id).valid
        ]
        summaries = tuple(
            {
                "snapshot_id": item.snapshot_id,
                "decision_date": item.decision_date,
                "captured_at": item.captured_at,
                "qualified": item.qualified,
                "diagnostic_score_percent": item.target.get("diagnostic_score_percent"),
                "target_fingerprint": item.target_fingerprint,
                "audit_valid": item.snapshot_id not in invalid,
            }
            for item in latest
        )
        evaluated = len(latest)
        qualified = sum(1 for item in latest if item.qualified)
        decision_dates = sorted(item.decision_date for item in latest)
        if invalid:
            status = "blocked"
            score = None
            blockers = ("decision_quality_audit_integrity_failure",)
        elif evaluated == 0:
            status = "empty"
            score = None
            blockers = ("no_captured_decision_days",)
        else:
            status = "complete"
            score = round(100 * qualified / evaluated, 2)
            blockers = ()
        return DecisionQualityReport(
            status=status,
            score_percent=score,
            evaluated_day_count=evaluated,
            qualified_day_count=qualified,
            blocked_day_count=evaluated - qualified,
            total_capture_count=len(captures),
            coverage_start=decision_dates[0] if decision_dates else None,
            coverage_end=decision_dates[-1] if decision_dates else None,
            latest_by_day=summaries,
            blockers=blockers,
        )

    def _latest_by_day(
        self,
        captures: list[StoredDecisionQualityCapture] | None = None,
    ) -> list[StoredDecisionQualityCapture]:
        latest: dict[str, StoredDecisionQualityCapture] = {}
        for capture in captures if captures is not None else self._store.list():
            if capture.decision_date not in latest:
                latest[capture.decision_date] = capture
        return [latest[key] for key in sorted(latest, reverse=True)]

    def _result(
        self,
        capture: StoredDecisionQualityCapture,
        *,
        target: DecisionQualityTarget,
        reused: bool,
    ) -> DecisionQualityCaptureResult:
        return DecisionQualityCaptureResult(
            capture=capture,
            current_target=target,
            report=self.report(),
            audit_replay=self._store.verify_replay(capture.snapshot_id),
            reused=reused,
        )


def build_decision_quality_target(
    decision_payload: dict[str, Any],
) -> DecisionQualityTarget:
    summary = _mapping(decision_payload.get("summary"))
    portfolio = _mapping(summary.get("portfolio"))
    market_data = _mapping(summary.get("market_data"))
    account_truth = _mapping(summary.get("account_truth"))
    candidates = [
        _mapping(item) for item in list(decision_payload.get("candidates") or [])
    ]
    decision_date = str(decision_payload.get("decision_date") or "").strip()
    if not decision_date:
        raise DecisionQualityCaptureRejected("decision_date is required")
    decision = str(decision_payload.get("decision") or "no_action")
    candidate_identity = [_candidate_identity(item) for item in candidates]
    decision_fingerprint = content_fingerprint(
        {
            "decision_date": decision_date,
            "decision": decision,
            "candidates": candidate_identity,
            "no_action_reasons": list(decision_payload.get("no_action_reasons") or []),
        }
    )
    dimensions = (
        _data_complete_dimension(
            candidates=candidates,
            portfolio=portfolio,
            market_data=market_data,
            account_truth=account_truth,
        ),
        _risk_checked_dimension(candidates),
        _benchmark_aware_dimension(candidates),
        _journaled_dimension(candidates),
        _later_reviewable_dimension(candidates),
    )
    identity = {
        "schema_version": DECISION_QUALITY_TARGET_VERSION,
        "decision_date": decision_date,
        "decision": decision,
        "candidate_count": len(candidates),
        "decision_fingerprint": decision_fingerprint,
        "dimensions": [item.to_dict() for item in dimensions],
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": int(portfolio.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": portfolio.get("ledger_fingerprint"),
        "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
    }
    return DecisionQualityTarget(
        decision_date=decision_date,
        decision=decision,
        candidate_count=len(candidates),
        decision_fingerprint=decision_fingerprint,
        dimensions=dimensions,
        valuation_snapshot_id=_optional_text(portfolio.get("valuation_snapshot_id")),
        ledger_cutoff_id=int(portfolio.get("ledger_cutoff_id") or 0),
        ledger_fingerprint=_optional_text(portfolio.get("ledger_fingerprint")),
        quote_set_fingerprint=_optional_text(portfolio.get("quote_set_fingerprint")),
        fingerprint=content_fingerprint(identity),
    )


def _data_complete_dimension(
    *,
    candidates: list[dict[str, Any]],
    portfolio: dict[str, Any],
    market_data: dict[str, Any],
    account_truth: dict[str, Any],
) -> DecisionQualityDimension:
    blockers: list[str] = []
    if portfolio.get("fact_authority") != "persisted_valuation_snapshot":
        blockers.append("decision_not_bound_to_persisted_valuation_snapshot")
    if not portfolio.get("valuation_snapshot_id"):
        blockers.append("valuation_snapshot_id_missing")
    if portfolio.get("valuation_status") != "complete":
        blockers.append("valuation_snapshot_not_complete")
    if int(portfolio.get("ledger_cutoff_id") or 0) <= 0:
        blockers.append("ledger_cutoff_missing")
    if not portfolio.get("ledger_fingerprint"):
        blockers.append("ledger_fingerprint_missing")
    if not portfolio.get("quote_set_fingerprint"):
        blockers.append("quote_set_fingerprint_missing")
    if str(account_truth.get("gate_status") or "blocked") != "pass":
        blockers.append("account_truth_gate_not_passed")
    if str(market_data.get("source_health") or "unknown") not in (
        _TRUSTED_MARKET_STATUSES
    ):
        blockers.append("market_data_not_complete")
    incomplete_candidates = []
    for item in candidates:
        data = _mapping(_mapping(item.get("evidence")).get("data_freshness"))
        status = str(data.get("status") or "unknown").strip().lower()
        source = str(data.get("quote_source") or "").strip().lower()
        if (
            status not in _TRUSTED_CANDIDATE_DATA_STATUSES
            or is_fund_estimate_quote_source(source)
        ):
            incomplete_candidates.append(_candidate_ref(item))
    if incomplete_candidates:
        blockers.append("candidate_data_not_complete")
    return DecisionQualityDimension(
        name="data_complete",
        passed=not blockers,
        status="pass" if not blockers else "blocked",
        evidence={
            "fact_authority": portfolio.get("fact_authority"),
            "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
            "valuation_status": portfolio.get("valuation_status"),
            "ledger_cutoff_id": int(portfolio.get("ledger_cutoff_id") or 0),
            "ledger_fingerprint": portfolio.get("ledger_fingerprint"),
            "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
            "market_data_status": market_data.get("source_health"),
            "account_truth_gate_status": account_truth.get("gate_status"),
            "incomplete_candidates": incomplete_candidates,
        },
        blockers=tuple(blockers),
    )


def _risk_checked_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="risk_checked",
            passed=True,
            status="not_applicable_no_action",
            evidence={"candidate_count": 0, "checked_count": 0},
        )
    unchecked = []
    checked = []
    for candidate in candidates:
        risk = _mapping(_mapping(candidate.get("evidence")).get("risk_gate"))
        status = str(risk.get("status") or "not_checked")
        reference = _candidate_ref(candidate)
        if status in _CHECKED_RISK_STATUSES and risk.get("decision_id"):
            checked.append(reference)
        else:
            unchecked.append(reference)
    return DecisionQualityDimension(
        name="risk_checked",
        passed=not unchecked,
        status="pass" if not unchecked else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "checked_count": len(checked),
            "checked_candidates": checked,
            "unchecked_candidates": unchecked,
        },
        blockers=("pre_trade_risk_evidence_incomplete",) if unchecked else (),
    )


def _benchmark_aware_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="benchmark_aware",
            passed=True,
            status="not_applicable_no_strategy_action",
            evidence={"candidate_count": 0, "aware_count": 0},
        )
    aware: list[str] = []
    missing: list[str] = []
    benchmark_evidence: list[dict[str, Any]] = []
    for candidate in candidates:
        validation = _mapping(
            _mapping(candidate.get("evidence")).get("after_cost_oos_validation")
        )
        oos = _mapping(validation.get("oos_validation"))
        supplied = (
            validation.get("status") == "attached"
            and validation.get("backtest_result_id") is not None
            and bool(str(oos.get("benchmark_role") or "").strip())
            and oos.get("benchmark_return") is not None
            and oos.get("validation_status") != "benchmark_not_supplied"
        )
        reference = _candidate_ref(candidate)
        if supplied:
            aware.append(reference)
        else:
            missing.append(reference)
        benchmark_evidence.append(
            {
                "candidate": reference,
                "backtest_result_id": validation.get("backtest_result_id"),
                "benchmark_role": oos.get("benchmark_role"),
                "benchmark_return": oos.get("benchmark_return"),
                "passed_benchmark": oos.get("passed_benchmark"),
                "validation_status": oos.get("validation_status"),
            }
        )
    return DecisionQualityDimension(
        name="benchmark_aware",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "aware_count": len(aware),
            "missing_candidates": missing,
            "benchmarks": benchmark_evidence,
        },
        blockers=("benchmark_evidence_incomplete",) if missing else (),
    )


def _journaled_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="journaled",
            passed=True,
            status="satisfied_by_daily_capture",
            evidence={
                "candidate_count": 0,
                "journaled_count": 0,
                "no_action_decision_will_be_journaled_by_capture": True,
            },
        )
    journaled: list[str] = []
    missing: list[str] = []
    for candidate in candidates:
        evidence = _mapping(candidate.get("evidence"))
        journal = _mapping(evidence.get("journal"))
        signal = _mapping(evidence.get("signal"))
        reference = _candidate_ref(candidate)
        if journal.get("has_journal_entry") is True and signal.get("id") is not None:
            journaled.append(reference)
        else:
            missing.append(reference)
    return DecisionQualityDimension(
        name="journaled",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "journaled_count": len(journaled),
            "missing_candidates": missing,
        },
        blockers=("signal_journal_evidence_incomplete",) if missing else (),
    )


def _later_reviewable_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="later_reviewable",
            passed=True,
            status="satisfied_by_content_addressed_capture",
            evidence={
                "candidate_count": 0,
                "reviewable_count": 0,
                "capture_is_replayable": True,
            },
        )
    reviewable: list[str] = []
    missing: list[str] = []
    for candidate in candidates:
        evidence = _mapping(candidate.get("evidence"))
        journal = _mapping(evidence.get("journal"))
        signal_id = _mapping(evidence.get("signal")).get("id")
        reference = _candidate_ref(candidate)
        try:
            stable_signal_id = int(signal_id) > 0
        except (TypeError, ValueError):
            stable_signal_id = False
        if stable_signal_id and journal.get("has_journal_entry") is True:
            reviewable.append(reference)
        else:
            missing.append(reference)
    return DecisionQualityDimension(
        name="later_reviewable",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "reviewable_count": len(reviewable),
            "missing_candidates": missing,
            "review_contract": "karkinos.decision_outcome_review.v1",
        },
        blockers=("post_decision_review_identity_incomplete",) if missing else (),
    )


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = _mapping(candidate.get("evidence"))
    signal = _mapping(evidence.get("signal"))
    risk = _mapping(evidence.get("risk_gate"))
    validation = _mapping(evidence.get("after_cost_oos_validation"))
    oos = _mapping(validation.get("oos_validation"))
    journal = _mapping(evidence.get("journal"))
    data = _mapping(evidence.get("data_freshness"))
    return {
        "action_id": candidate.get("action_id"),
        "action": candidate.get("action"),
        "symbol": candidate.get("symbol"),
        "target_weight": candidate.get("target_weight"),
        "signal_id": signal.get("id"),
        "risk_decision_id": risk.get("decision_id"),
        "risk_status": risk.get("status"),
        "backtest_result_id": validation.get("backtest_result_id"),
        "benchmark_role": oos.get("benchmark_role"),
        "benchmark_return": oos.get("benchmark_return"),
        "benchmark_validation_status": oos.get("validation_status"),
        "data_status": data.get("status"),
        "journaled": journal.get("has_journal_entry") is True,
    }


def _candidate_ref(candidate: dict[str, Any]) -> str:
    return f"{candidate.get('action_id') or 'action'}:{candidate.get('symbol') or 'unknown'}"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
