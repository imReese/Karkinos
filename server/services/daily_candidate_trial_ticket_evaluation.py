"""Ticket-level replay for daily-candidate operating trials."""

from __future__ import annotations

from typing import Any

from server.services.daily_candidate_trial_values import (
    aware_iso,
    elapsed_seconds,
    is_sha256,
    object_list,
    object_value,
    positive_float,
    shanghai_date,
)
from server.services.daily_decision_evidence_automation import (
    DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
    build_daily_candidate_strategy_gate_binding,
    daily_candidate_strategy_operating_constraints_blockers,
    manual_ticket_candidate_fingerprint,
)


class DailyCandidateTicketEvaluationMixin:
    """Validate candidate tickets against persisted and current safety bindings."""

    def _validate_ticket_candidates(self) -> None:
        market_quote_bindings = {
            str(item.get("intent_ref") or ""): item
            for item in object_list(self.snapshot.get("market_quote_bindings"))
            if str(item.get("intent_ref") or "")
        }
        strategy_gate_bindings = {
            str(item.get("action_id") or ""): item
            for item in object_list(self.snapshot.get("strategy_gate_bindings"))
            if str(item.get("action_id") or "")
        }
        if len(strategy_gate_bindings) != self.ticket_candidate_count:
            self.blockers.append("daily_candidate_strategy_gate_binding_count_mismatch")
        for index, ticket in enumerate(self.ticket_candidates):
            self._validate_ticket(
                index=index,
                ticket=ticket,
                market_quote_bindings=market_quote_bindings,
                strategy_gate_bindings=strategy_gate_bindings,
            )

    def _validate_ticket(
        self,
        *,
        index: int,
        ticket: dict[str, Any],
        market_quote_bindings: dict[str, dict[str, Any]],
        strategy_gate_bindings: dict[str, dict[str, Any]],
    ) -> None:
        prefix = f"manual_order_ticket_candidate_{index}"
        if ticket.get("schema_version") != DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION:
            self.blockers.append(f"{prefix}:contract_invalid")
        stored_fingerprint = str(ticket.get("ticket_candidate_fingerprint") or "")
        if not is_sha256(stored_fingerprint):
            self.blockers.append(f"{prefix}:fingerprint_invalid")
        elif stored_fingerprint != manual_ticket_candidate_fingerprint(ticket):
            self.blockers.append(f"{prefix}:fingerprint_mismatch")
        if str(ticket.get("plan_date") or "") != self.run_date:
            self.blockers.append(f"{prefix}:plan_date_mismatch")
        intent_ref = str(ticket.get("intent_id") or ticket.get("action_id") or "")
        if not intent_ref:
            self.blockers.append(f"{prefix}:intent_identity_missing")
        if str(ticket.get("side") or "").lower() not in {"buy", "sell"}:
            self.blockers.append(f"{prefix}:side_invalid")
        if str(ticket.get("asset_class") or "").strip().lower() != "stock":
            self.blockers.append(f"{prefix}:asset_class_outside_daily_candidate_scope")
        if positive_float(ticket.get("quantity")) is None:
            self.blockers.append(f"{prefix}:quantity_invalid")
        if positive_float(ticket.get("limit_price")) is None:
            self.blockers.append(f"{prefix}:limit_price_invalid")

        self._validate_ticket_market_quote(
            prefix=prefix,
            intent_ref=intent_ref,
            ticket=ticket,
            quote_binding=market_quote_bindings.get(intent_ref),
        )
        ticket_paper = object_value(ticket.get("paper_shadow"))
        if str(ticket_paper.get("run_id") or "") != str(
            self.snapshot.get("paper_shadow_run_id") or ""
        ):
            self.blockers.append(f"{prefix}:paper_shadow_run_mismatch")
        if str(ticket_paper.get("input_fingerprint") or "") != str(
            self.paper.get("input_fingerprint") or ""
        ):
            self.blockers.append(f"{prefix}:paper_shadow_fingerprint_mismatch")
        if ticket_paper.get("status") != "within_expectations":
            self.blockers.append(f"{prefix}:paper_shadow_status_not_clear")
        if ticket_paper.get("divergence_status") != "within_expectations":
            self.blockers.append(f"{prefix}:paper_shadow_divergence_not_clear")
        if str(ticket.get("prior_execution_closure_fingerprint") or "") != (
            self.execution_closure_fingerprint
        ):
            self.blockers.append(f"{prefix}:execution_closure_mismatch")

        evidence_refs = {
            str(item) for item in ticket.get("evidence_refs") or [] if str(item)
        }
        self._validate_ticket_strategy_binding(
            prefix=prefix,
            ticket=ticket,
            evidence_refs=evidence_refs,
            strategy_binding=strategy_gate_bindings.get(
                str(ticket.get("action_id") or "")
            ),
        )
        if object_value(ticket.get("account_truth_binding")) != (
            self.account_truth_binding
        ):
            self.blockers.append(f"{prefix}:account_truth_binding_mismatch")
        if not any(ref.startswith("strategy_advancement:") for ref in evidence_refs):
            self.blockers.append(f"{prefix}:strategy_advancement_ref_missing")
        if not any(ref.startswith("reviewed_fee_schedule:") for ref in evidence_refs):
            self.blockers.append(f"{prefix}:reviewed_fee_schedule_ref_missing")
        if not any(ref.startswith("risk:") for ref in evidence_refs):
            self.blockers.append(f"{prefix}:risk_ref_missing")
        if str(self.snapshot.get("account_truth_ref") or "") not in evidence_refs:
            self.blockers.append(f"{prefix}:account_truth_ref_mismatch")
        self._validate_ticket_authority(prefix=prefix, ticket=ticket)

    def _validate_ticket_market_quote(
        self,
        *,
        prefix: str,
        intent_ref: str,
        ticket: dict[str, Any],
        quote_binding: dict[str, Any] | None,
    ) -> None:
        market_quote = object_value(ticket.get("market_quote"))
        if market_quote.get("price") != ticket.get("limit_price"):
            self.blockers.append(f"{prefix}:market_quote_price_mismatch")
        if shanghai_date(market_quote.get("timestamp")) != self.run_date:
            self.blockers.append(f"{prefix}:market_quote_date_mismatch")
        if not str(market_quote.get("source") or "").strip():
            self.blockers.append(f"{prefix}:market_quote_source_missing")
        quote_age = elapsed_seconds(
            later=self.decision_window.get("decision_generated_at"),
            earlier=market_quote.get("timestamp"),
        )
        if quote_age is None:
            self.blockers.append(f"{prefix}:market_quote_age_invalid")
        elif quote_age > DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            self.blockers.append(f"{prefix}:market_quote_too_old")
        if market_quote.get("age_seconds_at_decision") != quote_age:
            self.blockers.append(f"{prefix}:market_quote_age_mismatch")
        if market_quote.get("max_age_seconds") != DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS:
            self.blockers.append(f"{prefix}:market_quote_max_age_invalid")
        if quote_binding is None:
            self.blockers.append(f"{prefix}:market_quote_snapshot_missing")
            return
        if quote_binding.get("price") != market_quote.get("price"):
            self.blockers.append(f"{prefix}:market_quote_snapshot_price_mismatch")
        if str(quote_binding.get("source") or "") != str(
            market_quote.get("source") or ""
        ):
            self.blockers.append(f"{prefix}:market_quote_snapshot_source_mismatch")
        if aware_iso(quote_binding.get("timestamp")) != aware_iso(
            market_quote.get("timestamp")
        ):
            self.blockers.append(f"{prefix}:market_quote_snapshot_time_mismatch")

    def _validate_ticket_strategy_binding(
        self,
        *,
        prefix: str,
        ticket: dict[str, Any],
        evidence_refs: set[str],
        strategy_binding: dict[str, Any] | None,
    ) -> None:
        if strategy_binding is None:
            self.blockers.append(f"{prefix}:strategy_gate_binding_missing")
            return
        if object_value(ticket.get("strategy_gate_binding")) != strategy_binding:
            self.blockers.append(f"{prefix}:strategy_gate_ticket_binding_mismatch")
        if strategy_binding.get("schema_version") != (
            DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION
        ):
            self.blockers.append(f"{prefix}:strategy_gate_binding_contract_invalid")

        ticket_constraints = object_value(ticket.get("strategy_operating_constraints"))
        binding_constraints = object_value(
            strategy_binding.get("strategy_operating_constraints")
        )
        if ticket_constraints != binding_constraints:
            self.blockers.append(
                f"{prefix}:strategy_operating_constraints_binding_mismatch"
            )
        daily_artifact_binding = object_value(
            strategy_binding.get("daily_strategy_artifact_binding")
        )
        constraint_blockers = daily_candidate_strategy_operating_constraints_blockers(
            binding_constraints,
            expected_candidate_id=str(
                daily_artifact_binding.get("winner_candidate_id") or ""
            ),
            expected_backup_fingerprint=str(
                daily_artifact_binding.get("backup_artifact_fingerprint") or ""
            ),
        )
        self.blockers.extend(f"{prefix}:{item}" for item in constraint_blockers)
        constraint_fingerprint = str(
            binding_constraints.get("evidence_fingerprint") or ""
        )
        if not constraint_blockers and is_sha256(constraint_fingerprint):
            self.strategy_operating_constraint_refs.add(
                f"strategy_operating_constraints:{constraint_fingerprint}"
            )

        for ref_field in (
            "strategy_ref",
            "strategy_advancement_ref",
            "reviewed_fee_schedule_ref",
        ):
            if str(strategy_binding.get(ref_field) or "") not in evidence_refs:
                self.blockers.append(f"{prefix}:{ref_field}_binding_mismatch")
        for fingerprint_field in (
            "comparison_fingerprint",
            "dataset_replay_fingerprint",
        ):
            if not is_sha256(strategy_binding.get(fingerprint_field)):
                self.blockers.append(f"{prefix}:{fingerprint_field}_invalid")
        for field, blocker in (
            ("human_approval_id", "strategy_human_approval_missing"),
            ("baseline_snapshot_id", "baseline_snapshot_id_missing"),
            ("candidate_snapshot_id", "candidate_snapshot_id_missing"),
        ):
            if not str(strategy_binding.get(field) or ""):
                self.blockers.append(f"{prefix}:{blocker}")
        boundary_checks = (
            ("persisted_facts_only", True, "strategy_persisted_facts_invalid"),
            ("provider_contact_performed", False, "strategy_provider_boundary_invalid"),
            (
                "paper_shadow_evaluation_only",
                True,
                "strategy_paper_shadow_boundary_invalid",
            ),
            ("authorizes_execution", False, "strategy_execution_boundary_invalid"),
            ("changes_capital_authority", False, "strategy_capital_boundary_invalid"),
        )
        for field, expected, blocker in boundary_checks:
            if strategy_binding.get(field) is not expected:
                self.blockers.append(f"{prefix}:{blocker}")
        self._validate_current_strategy_binding(
            prefix=prefix,
            strategy_binding=strategy_binding,
        )

    def _validate_current_strategy_binding(
        self,
        *,
        prefix: str,
        strategy_binding: dict[str, Any],
    ) -> None:
        strategy_ref = str(strategy_binding.get("strategy_ref") or "")
        strategy_id = strategy_ref.removeprefix("strategy:")
        if not strategy_ref.startswith("strategy:") or not strategy_id:
            self.blockers.append(f"{prefix}:current_strategy_identity_invalid")
            return
        if strategy_id not in self.current_strategy_gates:
            try:
                self.current_strategy_gates[strategy_id] = self.strategy_gate_resolver(
                    self.db,
                    strategy_id,
                    as_of_date=self.run_date,
                )
            except Exception:
                self.current_strategy_gates[strategy_id] = (
                    {},
                    ["strategy_gate_resolution_failed"],
                )
        current_gate, current_gate_blockers = self.current_strategy_gates[strategy_id]
        if current_gate_blockers:
            self.blockers.extend(
                f"{prefix}:current_{blocker}" for blocker in current_gate_blockers
            )
            return
        current_binding, current_binding_blockers = (
            build_daily_candidate_strategy_gate_binding(
                candidate={
                    "evidence": {
                        "strategy": {
                            "strategy_id": strategy_id,
                            "order_generation_gate": current_gate,
                        }
                    }
                },
                plan_date=self.run_date,
                expected_strategy_ref=strategy_ref,
                expected_advancement_ref=str(
                    strategy_binding.get("strategy_advancement_ref") or ""
                ),
                expected_fee_review_ref=str(
                    strategy_binding.get("reviewed_fee_schedule_ref") or ""
                ),
                action_id=strategy_binding.get("action_id"),
            )
        )
        self.blockers.extend(
            f"{prefix}:current_{blocker}" for blocker in current_binding_blockers
        )
        if not current_binding_blockers and current_binding != strategy_binding:
            self.blockers.append(f"{prefix}:current_strategy_gate_binding_mismatch")

    def _validate_ticket_authority(
        self,
        *,
        prefix: str,
        ticket: dict[str, Any],
    ) -> None:
        checks = (
            (
                "manual_confirmation_required",
                True,
                "manual_confirmation_boundary_invalid",
            ),
            ("creates_oms_order", False, "oms_creation_boundary_invalid"),
            ("authorizes_execution", False, "execution_authority_boundary_invalid"),
            ("broker_submission_enabled", False, "broker_submission_boundary_invalid"),
            (
                "does_not_change_capital_authority",
                True,
                "capital_authority_boundary_invalid",
            ),
        )
        for field, expected, blocker in checks:
            if ticket.get(field) is not expected:
                self.blockers.append(f"{prefix}:{blocker}")
        invalidation_conditions = ticket.get("invalidation_conditions")
        if (
            not isinstance(invalidation_conditions, list)
            or not invalidation_conditions
            or any(not str(item).strip() for item in invalidation_conditions)
        ):
            self.blockers.append(f"{prefix}:invalidation_conditions_invalid")
