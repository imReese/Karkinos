"""Bounded policy publication using canonical qualification and final evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

from server.contracts.content_identity import content_fingerprint
from server.contracts.recommendation_publication import (
    PUBLICATION_AUTHORIZE,
    PUBLICATION_DECISION_SCHEMA,
    PUBLICATION_POLICY_ID,
    PUBLICATION_POLICY_SCHEMA,
    PUBLICATION_REVOKE,
    fingerprinted,
    legacy_automated_approval,
    publication_number,
    publication_scope_incumbent,
    publication_time,
    read_publication_grant,
    validate_publication_grant,
)
from server.contracts.recommendation_publication import (
    publication_source_blocker as publication_source_blocker,
)
from server.services.account.reviewed_fee_schedule import (
    freeze_deployment_fee_schedule as freeze_deployment_fee_schedule,
)
from server.services.account.reviewed_fee_schedule import (
    resolve_frozen_deployment_fee_schedule as resolve_frozen_deployment_fee_schedule,
)
from server.services.account.valuation_snapshot import (
    require_valuation_recovery_clear,
)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _verified_deployment(db: Any, result_id: int, grant_id: str) -> dict[str, Any]:
    from server.services.research.research_final_evaluation import (
        verify_deployment_validation,
    )

    value = verify_deployment_validation(
        db, result_id=result_id, expected_grant_id=grant_id
    )
    if (
        not fingerprinted(value)
        or value.get("schema_version") != "karkinos.deployment_validation.v1"
        or value.get("status") != "pass"
    ):
        raise ValueError("publication_deployment_validation_not_verified")
    return dict(value)


def _preview_entry_board_policy(db: Any, config: Any, now: datetime):
    """Preserve scientific entry rules; current account permission is separate."""
    from zoneinfo import ZoneInfo

    from server.contracts.ai_shadow_research_automation import SHADOW_RESEARCH_POLICY_ID
    from server.contracts.research_observation_automation import (
        validate_simulation_validation_policy,
    )
    from server.services.account.account_board_permissions import (
        entry_board_policy_blocker,
        freeze_entry_board_policy,
        resolve_board_buy_permissions,
        validate_entry_board_policy,
    )

    day = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    simulation = _object(db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)).get(
        "simulation_validation"
    )
    if isinstance(simulation, Mapping) and simulation.get("enabled") is True:
        # Only the frozen scientific mask is reused, even after its collection
        # window expires. This grants no SIM operation or publication authority.
        selected = validate_simulation_validation_policy(simulation)[
            "entry_board_policy"
        ]
        origin = "frozen_simulation_entry_rules"
    else:
        previous = _object(db.get_automation_policy_sync(PUBLICATION_POLICY_ID))
        if previous.get("entry_board_policy") is not None:
            selected = validate_entry_board_policy(previous["entry_board_policy"])
            origin = "existing_publication_entry_rules"
        else:
            selected = freeze_entry_board_policy(config, day)
            origin = "current_account_entry_rules"
    permissions = resolve_board_buy_permissions(config, day)
    blocker = entry_board_policy_blocker(selected, permissions, decision_date=day)
    if blocker:
        raise ValueError(blocker)
    return selected, permissions, origin


class RecommendationPublicationService:
    def __init__(self, db: Any, store: Any, *, now: Any = None, state: Any = None):
        self.db = db
        self.store = store
        self.clock = now or (lambda: datetime.now(timezone.utc))
        self.state = state

    def _now(self) -> datetime:
        return publication_time(self.clock())

    def status(self, *, include_preview: bool = True) -> dict[str, Any]:
        policy: dict[str, Any] = {
            "policy_id": PUBLICATION_POLICY_ID,
            "enabled": False,
            "generation": None,
            "grant_id": None,
        }
        blockers: list[str] = []
        status = "disabled"
        try:
            policy = read_publication_grant(self.db, require_active=False)
            if policy["enabled"]:
                from server.services.account.account_board_permissions import (
                    validate_entry_board_policy,
                )

                validate_entry_board_policy(policy.get("entry_board_policy"))
                status = (
                    "expired"
                    if self._now() >= publication_time(policy["expires_at"])
                    else "active"
                )
                if status == "expired":
                    blockers.append("publication_grant_expired")
        except ValueError as exc:
            if str(exc) != "publication_grant_missing":
                status, blockers = "invalid", [str(exc)]
        states_reader = getattr(self.db, "list_strategy_promotion_states_sync", None)
        states = states_reader() if callable(states_reader) else []
        decisions = [
            _object(
                _object(row.get("payload_json") or row.get("payload")).get(
                    "publication_decision"
                )
            )
            for row in states
        ]
        decisions = [item for item in decisions if item]
        usable = []
        excluded = []
        for row in states:
            if row.get("stage") != "paper_shadow":
                continue
            blocker = publication_source_blocker(self.db, row)
            if blocker is None:
                from server.services.research.strategy_promotion_support import (
                    resolve_human_ai_shadow_strategy_promotion_binding,
                )

                try:
                    source_payload = _object(
                        row.get("payload_json") or row.get("payload")
                    )
                    binding, evidence_blockers = (
                        resolve_policy_publication_binding(self.db, row)
                        if source_payload.get("decision_source") == "policy"
                        else resolve_human_ai_shadow_strategy_promotion_binding(
                            self.db, str(row["strategy_id"])
                        )
                    )
                    if evidence_blockers or binding.get("status") != "pass":
                        blocker = (
                            ",".join(evidence_blockers)
                            or "publication_source_not_usable"
                        )
                except (ValueError, TypeError, KeyError, LookupError, AttributeError):
                    blocker = "publication_source_evidence_unavailable"
            if blocker:
                excluded.append(
                    {"strategy_id": row.get("strategy_id"), "blocker": blocker}
                )
            else:
                decision = _object(binding.get("publication_decision"))
                source = binding.get("decision_source")
                usable.append(
                    {
                        "strategy_id": str(row["strategy_id"]),
                        "decision_source": source or "unknown",
                        **{
                            key: decision[key]
                            for key in ("grant_id", "generation", "allocation_scope")
                            if key in decision
                        },
                    }
                )
        result = {
            "policy": policy,
            "status": status,
            "blockers": blockers,
            "latest_decision": max(
                decisions, key=lambda item: str(item.get("created_at")), default=None
            ),
            "usable_current_sources": usable,
            "excluded_sources": excluded,
            "proposed_binding": None,
        }
        if include_preview:
            preview = self.preview({})
            result.update(preview)
        return result

    def preview(self, inputs: Mapping[str, Any]) -> dict[str, Any]:
        """Bind reviewable owner settings to current local account and scope facts."""
        try:
            from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
            from server.services.account.reviewed_fee_schedule import (
                build_reviewed_fee_schedule_review_status,
            )
            from server.services.account.valuation_snapshot import (
                build_current_valuation_snapshot,
                portfolio_equity_from_valuation,
            )
            from server.services.market.market_universe_truth import (
                MarketUniversePolicy,
                market_deployment_scope,
            )

            valuation = build_current_valuation_snapshot(self.db, persist=False)
            if valuation.get("status") != "complete":
                raise ValueError("publication_preview_current_valuation_incomplete")
            require_valuation_recovery_clear(self.db, valuation)
            if self.state is None:
                raise ValueError("publication_preview_account_context_unavailable")
            review_status = build_reviewed_fee_schedule_review_status(self.state)
            review = _object(review_status.get("review"))
            account_scope = review.get("account_truth_scope_fingerprint")
            if review_status.get("status") != "active" or not account_scope:
                raise ValueError(
                    "publication_preview_reviewed_account_scope_unavailable"
                )
            from server.services.account.fees.commission import (
                validated_notional_envelope,
            )

            fee_limits, _ = validated_notional_envelope(
                _object(
                    _object(review.get("preview")).get("component_reconciliation")
                ).get("reconciled_notional_envelope")
            )
            if "stock" not in fee_limits:
                raise ValueError("publication_preview_stock_fee_envelope_missing")
            # Four target slots and an explicit 0.5% envelope cushion.
            # This narrows the proposed budget; it never expands the review's
            # range or guarantees that a later price gap will be affordable.
            fee_cash_cap = (fee_limits["stock"] * 4 / Decimal("1.005")).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            current_equity = portfolio_equity_from_valuation(self.db, valuation)
            default_cash = min(
                current_equity,
                Decimal("1000000"),
                fee_cash_cap,
            )
            now = self._now()
            entry_board_policy, board_permissions, board_policy_origin = (
                _preview_entry_board_policy(
                    self.db, getattr(self.state, "config", None), now
                )
            )
            statistical = dict(
                inputs.get("statistical_policy")
                or {
                    "method": "paired_moving_block_bootstrap.v1",
                    "minimum_observations": 60,
                    "block_length": 5,
                    "minimum_effective_blocks": 10,
                    "bootstrap_samples": 100_000,
                    "significance_level": "0.05",
                    "minimum_net_excess": "0",
                    "decision_checkpoint": (now + timedelta(days=120))
                    .date()
                    .isoformat(),
                    "checkpoint_interval_days": 120,
                }
            )
            defaults = {
                "allocation_scope": "stock_research",
                "strategy_family": "formula",
                "max_initial_cash": str(default_cash),
                "risk_limits": {
                    "max_drawdown": "0.2",
                    "max_gross_weight": "1",
                    "max_symbol_weight": "0.30",
                    "max_positions": 4,
                },
                "max_publications": 1,
                "max_final_tests": 1,
                "total_error_budget": "0.05",
                "min_net_improvement": "0",
                "cooldown_days": 30,
                "incumbent_strategy_id": None,
                "expires_at": (now + timedelta(days=180)).isoformat(),
                "updated_by": "human:owner",
            }
            permitted = set(defaults) | {"statistical_policy"}
            if set(inputs) - permitted:
                raise ValueError("publication_preview_unknown_fields")
            policy = {
                **defaults,
                **dict(inputs),
                "enabled": True,
                "schema_version": PUBLICATION_POLICY_SCHEMA,
                "policy_id": PUBLICATION_POLICY_ID,
                "grant_id": str(uuid4()),
                "generation": str(uuid4()),
                "authorization": PUBLICATION_AUTHORIZE,
                "account_scope_fingerprint": account_scope,
                "deployment_scope_fingerprint": market_deployment_scope(
                    MarketUniversePolicy(),
                    portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
                )["deployment_scope_fingerprint"],
                "statistical_policy": statistical,
                "statistical_policy_fingerprint": content_fingerprint(statistical),
                "entry_board_policy": entry_board_policy,
            }
            per_attempt = publication_number(
                policy["total_error_budget"]
            ) / publication_number(policy["max_final_tests"])
            statistical["significance_level"] = str(
                min(publication_number(statistical["significance_level"]), per_attempt)
            )
            policy["statistical_policy_fingerprint"] = content_fingerprint(statistical)
            validate_publication_grant(policy)
            if any(
                publication_number(policy["risk_limits"][key]) < target
                for key, target in {
                    "max_positions": Decimal(4),
                    "max_symbol_weight": Decimal("0.25"),
                    "max_gross_weight": Decimal("0.97"),
                }.items()
            ):
                raise ValueError(
                    "publication_preview_risk_limits_below_fixed_portfolio_targets"
                )
            if statistical[
                "decision_checkpoint"
            ] <= now.date().isoformat() and not statistical.get(
                "checkpoint_interval_days"
            ):
                raise ValueError("publication_preview_checkpoint_not_future")
            from datetime import date

            checkpoint = date.fromisoformat(statistical["decision_checkpoint"])
            interval = int(statistical.get("checkpoint_interval_days", 0))
            while checkpoint <= now.date() and interval:
                checkpoint += timedelta(days=interval)
            if checkpoint >= publication_time(policy["expires_at"]).date():
                raise ValueError("publication_preview_checkpoint_not_before_expiry")
            coverage_start = str(review.get("effective_start_date") or "")
            coverage_end = str(review.get("effective_end_date") or "")
            if not coverage_start or not coverage_end:
                raise ValueError("publication_preview_reviewed_fee_coverage_missing")
            if not (
                date.fromisoformat(coverage_start)
                <= now.date()
                <= date.fromisoformat(coverage_end)
            ):
                raise ValueError("publication_preview_reviewed_fee_window_not_current")
            if checkpoint > date.fromisoformat(coverage_end):
                raise ValueError(
                    "publication_preview_reviewed_fee_checkpoint_not_covered"
                )
            from server.ai_runtime.formula_challengers import (
                frozen_research_challengers,
            )

            # Include a future incumbent even for an initial publication, so a
            # standing profile remains usable for its authorized replacements.
            comparator_count = 2 + len(frozen_research_challengers("grant-preview"))
            if (
                publication_number(statistical["bootstrap_samples"])
                * publication_number(statistical["significance_level"])
                / comparator_count
                < 20
            ):
                raise ValueError("publication_preview_bootstrap_tail_insufficient")
            if publication_number(
                statistical["significance_level"]
            ) > publication_number(policy["total_error_budget"]):
                raise ValueError("publication_preview_test_exceeds_error_budget")
            if publication_number(policy["max_initial_cash"]) > publication_number(
                current_equity
            ):
                raise ValueError("publication_preview_capital_exceeds_current_equity")
            if publication_number(policy["max_initial_cash"]) > fee_cash_cap:
                raise ValueError(
                    "publication_preview_capital_exceeds_reviewed_fee_envelope"
                )
            policy.pop("grant_id")
            policy.pop("generation")
            policy.pop("authorization")
            return {
                "proposed_binding": policy,
                "preview_blockers": [],
                "binding_source": {
                    "valuation_snapshot_id": valuation["snapshot_id"],
                    "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
                    "portfolio_target_limits": {
                        "max_positions": 4,
                        "max_symbol_weight": "0.25",
                        "max_gross_weight": "0.97",
                    },
                    "risk_limit_basis": "observed_book_exposure_and_drawdown",
                    "entry_board_policy": entry_board_policy,
                    "entry_board_policy_source": board_policy_origin,
                    "account_board_permissions": board_permissions,
                    "reviewed_fee_schedule": {
                        "review_id": review.get("review_id"),
                        "effective_start_date": coverage_start,
                        "effective_end_date": coverage_end,
                    },
                },
            }
        except (
            ImportError,
            AttributeError,
            KeyError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            return {
                "proposed_binding": None,
                "preview_blockers": [str(exc)],
                "binding_source": None,
            }

    def update(self, request: Mapping[str, Any]) -> dict[str, Any]:
        current = self.status(include_preview=False)["policy"]
        enabled = request.get("enabled")
        confirmation = request.get("confirmation")
        if type(enabled) is not bool:
            raise ValueError("publication_policy_enabled_invalid")
        if confirmation != (PUBLICATION_AUTHORIZE if enabled else PUBLICATION_REVOKE):
            raise PermissionError("publication_grant_requires_exact_owner_confirmation")
        policy = {
            **current,
            **{
                key: value
                for key, value in request.items()
                if key not in {"confirmation", "expected_generation"}
            },
            "schema_version": PUBLICATION_POLICY_SCHEMA,
            "policy_id": PUBLICATION_POLICY_ID,
            "grant_id": current.get("grant_id") or str(uuid4()),
            "generation": str(uuid4()),
            "enabled": enabled,
            "authorization": PUBLICATION_AUTHORIZE if enabled else "",
        }
        if enabled and self._now() >= publication_time(policy.get("expires_at")):
            raise ValueError("publication_grant_expiry_not_future")
        if enabled:
            fields = (
                "allocation_scope",
                "strategy_family",
                "max_initial_cash",
                "risk_limits",
                "max_publications",
                "max_final_tests",
                "total_error_budget",
                "min_net_improvement",
                "cooldown_days",
                "incumbent_strategy_id",
                "expires_at",
                "updated_by",
                "statistical_policy",
            )
            preview = self.preview(
                {key: policy[key] for key in fields if key in policy}
            )
            proposed = preview.get("proposed_binding")
            if not proposed:
                raise ValueError(
                    "publication_grant_preview_unavailable:"
                    + ",".join(preview["preview_blockers"])
                )
            if any(
                proposed[key] != policy.get(key)
                for key in (
                    "account_scope_fingerprint",
                    "deployment_scope_fingerprint",
                    "statistical_policy_fingerprint",
                    "entry_board_policy",
                )
            ):
                raise ValueError("publication_grant_preview_binding_changed")
        self.store.configure_publication_grant(
            policy=policy,
            expected_generation=request.get("expected_generation"),
            now=self._now().isoformat(),
        )
        return self.status()

    def _incumbent(self, grant: Mapping[str, Any]) -> dict[str, Any] | None:
        return publication_scope_incumbent(self.db, grant)

    def readiness(
        self, qualification_id: str, grant: Mapping[str, Any], *, fresh: bool
    ) -> dict[str, Any]:
        from server.services.account.valuation_snapshot import (
            build_current_valuation_snapshot,
        )
        from server.services.research.strategy_promotion_support import (
            resolve_ai_shadow_qualification_promotion_evidence,
        )

        evidence, blockers = resolve_ai_shadow_qualification_promotion_evidence(
            self.db, qualification_id, require_human_approval=False
        )
        if blockers or evidence.get("status") != "pass":
            raise ValueError("publication_qualification_invalid:" + ",".join(blockers))
        binding = evidence["qualification_binding"]
        if (
            binding.get("account_truth_scope_fingerprint")
            != grant["account_scope_fingerprint"]
        ):
            raise ValueError("publication_account_scope_mismatch")
        if fresh:
            current = build_current_valuation_snapshot(self.db, persist=False)
            if (
                current.get("status") != "complete"
                or current.get("snapshot_id") != binding["valuation_snapshot_id"]
            ):
                raise ValueError("publication_current_qualification_required")
            require_valuation_recovery_clear(self.db, current)
        validation = _verified_deployment(
            self.db, int(evidence["backtest_result_id"]), grant["grant_id"]
        )
        if (
            validation.get("deployment_scope_fingerprint")
            != grant["deployment_scope_fingerprint"]
            or validation.get("statistical_policy_fingerprint")
            != grant["statistical_policy_fingerprint"]
            or validation.get("entry_board_policy") != grant["entry_board_policy"]
        ):
            raise ValueError("publication_validation_scope_or_statistics_mismatch")
        if not all(
            validation.get(key)
            for key in (
                "strategy_fingerprint",
                "code_fingerprint",
                "final_evaluation_id",
                "final_evidence_fingerprint",
            )
        ):
            raise ValueError("publication_validation_binding_incomplete")
        cash = publication_number(validation.get("initial_cash"))
        qualification = self.store.get_qualification_run(
            str(evidence["qualification_run_id"])
        )
        if not 0 < cash <= publication_number(
            grant["max_initial_cash"]
        ) or cash != publication_number(qualification["initial_cash_text"]):
            raise ValueError("publication_validated_capital_mismatch")
        for key, cap in grant["risk_limits"].items():
            bound = publication_number(validation.get("risk_limits", {}).get(key))
            if bound < 0 or bound > publication_number(cap):
                raise ValueError("publication_validated_risk_exceeds_grant")
        budget = validation.get("error_budget", {})
        publication_bound = (
            validation.get("publication_grant_id") == grant["grant_id"]
            and validation.get("publication_grant_generation") == grant["generation"]
            if validation.get("validation_provenance") == "independent_simulation"
            else budget.get("grant_id") == grant["grant_id"]
            and budget.get("generation") == grant["generation"]
        )
        if (
            not publication_bound
            or type(budget.get("attempt_count")) is not int
            or not 1 <= budget["attempt_count"] <= grant["max_final_tests"]
            or not 0
            < publication_number(budget.get("error_budget_spent"))
            <= publication_number(grant["total_error_budget"])
        ):
            raise ValueError("publication_final_test_budget_invalid")
        return {
            "schema_version": "karkinos.ai.policy_publication_readiness.v1",
            "strategy_id": "ai_formula_shadow:" + evidence["source_candidate_id"],
            "candidate_id": evidence["source_candidate_id"],
            "qualification_candidate_id": qualification_id,
            "qualification_run_id": evidence["qualification_run_id"],
            "backtest_result_id": evidence["backtest_result_id"],
            "comparison_fingerprint": evidence["comparison_fingerprint"],
            "qualification_binding": binding,
            "daily_strategy_artifact_binding": evidence[
                "daily_strategy_artifact_binding"
            ],
            "strategy_advancement_gate": evidence["strategy_advancement_gate"],
            "deployment_validation": validation,
            "fee_schedule_binding": evidence["fee_schedule_binding"],
            "dataset_replay": evidence["dataset_replay"],
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_create_order": True,
            "does_not_authorize_execution": True,
            "does_not_change_capital_authority": True,
        }

    def publish(self, qualification_id: str) -> dict[str, Any]:
        grant = read_publication_grant(self.db, now=self._now())
        readiness = self.readiness(qualification_id, grant, fresh=True)
        strategy_id = readiness["strategy_id"]
        validation = readiness["deployment_validation"]

        def current_evidence():
            active = read_publication_grant(self.db, now=self._now())
            result = self.readiness(qualification_id, active, fresh=True)
            read_publication_grant(self.db, now=self._now())
            return result

        current = self.db.get_strategy_promotion_state_sync(strategy_id)
        previous = _object(
            _object((current or {}).get("payload_json")).get("publication_decision")
        )
        if (
            current
            and current.get("stage") == "paper_shadow"
            and previous.get("grant_id") == grant["grant_id"]
            and previous.get("generation") == grant["generation"]
            and previous.get("candidate_id") == readiness["candidate_id"]
            and previous.get("final_evaluation_id") == validation["final_evaluation_id"]
            and previous.get("deployment_validation_fingerprint")
            == validation["evidence_fingerprint"]
        ):
            # A new account valuation may produce another qualification row for
            # the same frozen strategy. A still-usable publication needs no
            # replacement decision and consumes no additional publication.
            existing, blockers = resolve_policy_publication_binding(self.db, current)
            if not blockers and existing.get("status") == "pass":
                return {"strategy_promotion": current, "reused": True}
        if (
            previous.get("grant_id") == grant["grant_id"]
            and previous.get("generation") == grant["generation"]
            and previous.get("qualification_candidate_id") == qualification_id
            and previous.get("deployment_validation_fingerprint")
            == validation["evidence_fingerprint"]
        ):
            return self.store.publish_qualified_candidate_under_policy(
                strategy_id=strategy_id,
                readiness=readiness,
                decision=previous,
                expected_state=current,
                incumbent=None,
                current_evidence_validator=current_evidence,
                now=self._now().isoformat(),
            )
        incumbent = self._incumbent(grant)
        if incumbent and incumbent["strategy_id"] != strategy_id:
            replacement = validation.get("replacement", {})
            if (
                replacement.get("incumbent_strategy_id") != incumbent["strategy_id"]
                or replacement.get("common_interval") is not True
                or publication_number(replacement.get("transition_cost")) < 0
                or publication_number(replacement.get("net_improvement_lower_bound"))
                < publication_number(grant["min_net_improvement"])
            ):
                raise ValueError("publication_incumbent_improvement_unverified")
            if self._now() < publication_time(incumbent["updated_at"]) + timedelta(
                days=grant["cooldown_days"]
            ):
                raise ValueError("publication_replacement_cooldown")
        core = {
            "schema_version": PUBLICATION_DECISION_SCHEMA,
            "decision_source": "policy",
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
            "allocation_scope": grant["allocation_scope"],
            "candidate_id": readiness["candidate_id"],
            "qualification_candidate_id": qualification_id,
            "deployment_validation_fingerprint": validation["evidence_fingerprint"],
            "final_evaluation_id": validation["final_evaluation_id"],
            "expected_incumbent_strategy_id": incumbent["strategy_id"]
            if incumbent and incumbent["strategy_id"] != strategy_id
            else None,
            "expected_incumbent_state_fingerprint": content_fingerprint(incumbent)
            if incumbent
            else None,
        }
        decision_id = content_fingerprint(core)
        if previous.get("decision_id") == decision_id:
            decision = previous
        else:
            decision = {
                **core,
                "decision_id": decision_id,
                "created_at": self._now().isoformat(),
            }
        return self.store.publish_qualified_candidate_under_policy(
            strategy_id=strategy_id,
            readiness=readiness,
            decision=decision,
            expected_state=current,
            incumbent=incumbent,
            current_evidence_validator=current_evidence,
            now=self._now().isoformat(),
        )


def resolve_policy_publication_binding(
    db: Any, state: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Reopen the grant and evidence on each account-consumer read."""
    from server.persistence.ai_shadow_research import ShadowResearchStore

    strategy_id = str(state.get("strategy_id") or "")
    try:
        blocker = publication_source_blocker(db, state)
        if blocker:
            raise ValueError(blocker)
        payload = _object(state.get("payload_json") or state.get("payload"))
        decision = _object(payload.get("publication_decision"))
        grant = read_publication_grant(db)
        if (
            decision.get("schema_version") != PUBLICATION_DECISION_SCHEMA
            or decision.get("decision_source") != "policy"
            or decision.get("allocation_scope") != grant["allocation_scope"]
            or state.get("stage") != "paper_shadow"
            or state.get("gate_status") != "paper_shadow_enabled"
            or bool(state.get("live_like_enabled"))
            or payload.get("human_review") is not None
        ):
            raise ValueError("publication_policy_state_invalid")
        service = RecommendationPublicationService(db, ShadowResearchStore(db._path))
        readiness = service.readiness(
            str(decision["qualification_candidate_id"]), grant, fresh=False
        )
        if (
            readiness != payload.get("readiness")
            or readiness["strategy_id"] != strategy_id
            or int(state.get("backtest_result_id") or 0)
            != readiness["backtest_result_id"]
            or decision.get("deployment_validation_fingerprint")
            != readiness["deployment_validation"]["evidence_fingerprint"]
        ):
            raise ValueError("publication_policy_evidence_drift")
        core = {
            key: value
            for key, value in decision.items()
            if key not in {"decision_id", "created_at"}
        }
        if decision.get("decision_id") != content_fingerprint(core):
            raise ValueError("publication_policy_decision_invalid")
        return {
            "status": "pass",
            "strategy_id": strategy_id,
            "decision_source": "policy",
            "candidate_id": readiness["candidate_id"],
            "stage": state["stage"],
            "gate_status": state["gate_status"],
            "backtest_result_id": readiness["backtest_result_id"],
            "comparison_fingerprint": readiness["comparison_fingerprint"],
            "qualification_candidate_id": readiness["qualification_candidate_id"],
            "qualification_run_id": readiness["qualification_run_id"],
            "qualification_binding": readiness["qualification_binding"],
            "strategy_advancement_gate_fingerprint": readiness[
                "strategy_advancement_gate"
            ]["evidence_fingerprint"],
            "daily_strategy_artifact_binding": readiness[
                "daily_strategy_artifact_binding"
            ],
            "fee_schedule_binding": readiness["fee_schedule_binding"],
            "dataset_replay": readiness["dataset_replay"],
            "normalized_research": False,
            "publication_decision": decision,
            "publication_grant": grant,
            "entry_board_policy": grant["entry_board_policy"],
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_create_order": True,
            "does_not_authorize_execution": True,
            "does_not_change_capital_authority": True,
        }, []
    except (
        ValueError,
        KeyError,
        TypeError,
        LookupError,
        ImportError,
        AttributeError,
    ) as exc:
        return {
            "status": "blocked",
            "strategy_id": strategy_id,
            "decision_source": "policy",
        }, [str(exc)]


__all__ = [
    "RecommendationPublicationService",
    "resolve_policy_publication_binding",
]
