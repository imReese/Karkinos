"""Research domain services.

High-cohesion domain modules:
- `corporate_action_jobs`: Scheduled corporate action intake and dataset adjustment jobs
- `datasets`: Research dataset lifecycle, verification, and manifest registration
- `dataset_inputs`: Dataset loading, slicing, and validation for research simulations
- `factors`: Factor analytics, momentum, and cross-sectional factor evaluation
- `factory`: Research service factory and dependency injection
- `final_evaluation`: Sealed qualification, reservation, and final promotion evaluations
- `forecasts`: Forward directional forecasts and rule evaluations
- `instruments`: Research instrument representation and identification
- `observations`: Research observation lifecycle and advancement tracking
- `observation_automation`: Automated forward observation scheduling and execution
- `observation_data_preparation`: Forward observation dataset preparation jobs
- `observation_inputs`: Forward observation dataset and window bindings
- `paper_books`: Simulated forward paper book tracking and settlements
- `strategy_contribution`: Strategy portfolio contribution analytics
- `strategy_promotion_pipeline`: Governance and gating for strategy promotion to live candidate
- `strategy_promotion_support`: Promotion evaluation support, checks, and criteria
"""

from __future__ import annotations

__all__ = [
    "corporate_action_jobs",
    "dataset_inputs",
    "datasets",
    "factors",
    "factory",
    "final_evaluation",
    "forecasts",
    "instruments",
    "observation_automation",
    "observation_data_preparation",
    "observation_inputs",
    "observations",
    "paper_books",
    "strategy_contribution",
    "strategy_promotion_pipeline",
    "strategy_promotion_support",
]
