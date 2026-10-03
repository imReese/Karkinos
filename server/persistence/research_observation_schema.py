"""Storage for independent research targets and their subsequent outcomes."""

from __future__ import annotations

_IMMUTABLE_TABLES = (
    "research_observation_publications",
    "research_observation_outcomes",
    "research_observation_operations",
)

V22_RESEARCH_OBSERVATIONS = (
    """
    CREATE TABLE research_observations (
        id TEXT PRIMARY KEY NOT NULL,
        source_backtest_result_id INTEGER NOT NULL,
        source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        code_binding_json TEXT NOT NULL CHECK(json_valid(code_binding_json)),
        policy_json TEXT NOT NULL CHECK(json_valid(policy_json)),
        universe_json TEXT NOT NULL CHECK(json_valid(universe_json)),
        started_at TEXT NOT NULL,
        lifecycle TEXT NOT NULL CHECK(lifecycle IN ('active', 'paused')),
        version INTEGER NOT NULL CHECK(version >= 0),
        last_blocker_json TEXT CHECK(last_blocker_json IS NULL
                                    OR json_valid(last_blocker_json))
    )
    """,
    """
    CREATE TABLE research_observation_publications (
        id TEXT PRIMARY KEY NOT NULL,
        observation_id TEXT NOT NULL REFERENCES research_observations(id),
        decision_session TEXT NOT NULL,
        published_at TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
        UNIQUE(observation_id, decision_session)
    )
    """,
    """
    CREATE TABLE research_observation_outcomes (
        publication_id TEXT NOT NULL REFERENCES research_observation_publications(id),
        horizon INTEGER NOT NULL CHECK(horizon > 0),
        measured_at TEXT NOT NULL,
        dataset_id TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
        PRIMARY KEY(publication_id, horizon)
    )
    """,
    """
    CREATE TABLE research_observation_operations (
        observation_id TEXT NOT NULL REFERENCES research_observations(id),
        request_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('start', 'advance', 'pause')),
        request_fingerprint TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        completed_at TEXT NOT NULL,
        PRIMARY KEY(observation_id, request_id)
    )
    """,
    """
    CREATE TRIGGER research_observations_source_guard
    BEFORE UPDATE OF id, source_backtest_result_id, source_json, code_binding_json,
                     policy_json, universe_json, started_at ON research_observations
    BEGIN
        SELECT RAISE(ABORT, 'research observation source is immutable');
    END
    """,
    """
    CREATE TRIGGER research_observations_delete_guard
    BEFORE DELETE ON research_observations
    BEGIN
        SELECT RAISE(ABORT, 'research observations are retained');
    END
    """,
    *(
        f"""
        CREATE TRIGGER {table}_{action.lower()}_guard
        BEFORE {action} ON {table}
        BEGIN
            SELECT RAISE(ABORT, 'research observation history is immutable');
        END
        """
        for table in _IMMUTABLE_TABLES
        for action in ("UPDATE", "DELETE")
    ),
)

V22_SCHEMA_OBJECTS = (
    ("table", "research_observations"),
    *(("table", table) for table in _IMMUTABLE_TABLES),
    ("trigger", "research_observations_source_guard"),
    ("trigger", "research_observations_delete_guard"),
    *(
        ("trigger", f"{table}_{action}_guard")
        for table in _IMMUTABLE_TABLES
        for action in ("update", "delete")
    ),
)
