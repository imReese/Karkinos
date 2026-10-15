"""Standing opt-in for one local, target-only research observation."""

from uuid import NAMESPACE_URL, UUID, uuid5

from server.contracts.content_identity import content_fingerprint

OBSERVATION_AUTOMATION_SCHEMA = "karkinos.research_observation_automation.v1"
OBSERVATION_AUTOMATION_PREFIX = "research-observation:"
OBSERVATION_DATASET_SELECTION = "latest_verified_exact_prefix.v1"


def reserved_forward_identity(reservation_id, grant):
    key = "reserved-forward:" + content_fingerprint(
        {
            "reservation_id": reservation_id,
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
        }
    )
    request_id = key + ":observation"
    return key, str(uuid5(NAMESPACE_URL, f"karkinos:research-observation:{request_id}"))


def observation_automation_policy_id(observation_id: str) -> str:
    return f"{OBSERVATION_AUTOMATION_PREFIX}{observation_id}"


def observation_automation_policy_valid(value: object, observation_id: str) -> bool:
    try:
        generation = value.get("generation") if isinstance(value, dict) else None
        if not isinstance(generation, str) or str(UUID(generation)) != generation:
            return False
    except ValueError:
        return False
    return (
        isinstance(observation_id, str)
        and bool(observation_id)
        and isinstance(value, dict)
        and value.get("schema_version") == OBSERVATION_AUTOMATION_SCHEMA
        and value.get("observation_id") == observation_id
        and type(value.get("enabled")) is bool
        and type(value.get("paper_settlement_enabled", False)) is bool
        and type(value.get("dataset_preparation_enabled", False)) is bool
        and value.get("dataset_selection") == OBSERVATION_DATASET_SELECTION
        and value.get("local_data_only") is True
        and value.get("account_authority") is False
    )
