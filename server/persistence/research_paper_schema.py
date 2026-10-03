"""An independent paper book and its immutable daily accounting history."""

_HISTORY_TABLES = ("research_paper_steps", "research_paper_operations")

V24_RESEARCH_PAPER_BOOKS = (
    """
    CREATE TABLE research_paper_books (
        id TEXT PRIMARY KEY NOT NULL,
        observation_id TEXT NOT NULL UNIQUE REFERENCES research_observations(id),
        source_json TEXT NOT NULL CHECK(json_valid(source_json)),
        policy_json TEXT NOT NULL CHECK(json_valid(policy_json)),
        code_binding_json TEXT NOT NULL CHECK(json_valid(code_binding_json)),
        instruments_json TEXT NOT NULL CHECK(json_valid(instruments_json)),
        initial_cash TEXT NOT NULL,
        started_at TEXT NOT NULL,
        evaluation_start TEXT NOT NULL,
        paused_at TEXT,
        lifecycle TEXT NOT NULL CHECK(lifecycle IN ('active', 'paused')),
        version INTEGER NOT NULL CHECK(version >= 0)
    )
    """,
    """
    CREATE TABLE research_paper_steps (
        book_id TEXT NOT NULL REFERENCES research_paper_books(id),
        session TEXT NOT NULL,
        book_version INTEGER NOT NULL CHECK(book_version > 0),
        dataset_id TEXT NOT NULL,
        input_json TEXT NOT NULL CHECK(json_valid(input_json)),
        projection_json TEXT NOT NULL CHECK(json_valid(projection_json)),
        settled_at TEXT NOT NULL,
        PRIMARY KEY(book_id, session)
    )
    """,
    """
    CREATE TABLE research_paper_operations (
        book_id TEXT NOT NULL REFERENCES research_paper_books(id),
        request_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('start', 'settle', 'pause')),
        request_fingerprint TEXT NOT NULL,
        result_json TEXT NOT NULL CHECK(json_valid(result_json)),
        completed_at TEXT NOT NULL,
        PRIMARY KEY(book_id, request_id)
    )
    """,
    """
    CREATE TRIGGER research_paper_books_source_guard
    BEFORE UPDATE OF id, observation_id, source_json, policy_json, code_binding_json,
                     instruments_json, initial_cash, started_at, evaluation_start
    ON research_paper_books
    BEGIN
        SELECT RAISE(ABORT, 'research paper source is immutable');
    END
    """,
    """
    CREATE TRIGGER research_paper_books_delete_guard
    BEFORE DELETE ON research_paper_books
    BEGIN
        SELECT RAISE(ABORT, 'research paper books are retained');
    END
    """,
    *(
        f"""
        CREATE TRIGGER {table}_{action.lower()}_guard
        BEFORE {action} ON {table}
        BEGIN
            SELECT RAISE(ABORT, 'research paper history is immutable');
        END
        """
        for table in _HISTORY_TABLES
        for action in ("UPDATE", "DELETE")
    ),
)

V24_SCHEMA_OBJECTS = (
    ("table", "research_paper_books"),
    *(("table", table) for table in _HISTORY_TABLES),
    ("trigger", "research_paper_books_source_guard"),
    ("trigger", "research_paper_books_delete_guard"),
    *(
        ("trigger", f"{table}_{action}_guard")
        for table in _HISTORY_TABLES
        for action in ("update", "delete")
    ),
)
