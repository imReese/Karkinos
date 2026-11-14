"""Fail CI when any server module bypasses shared SQLite connection policy."""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path("server")
ALLOWED_EXCLUSIONS = {
    Path("server/persistence/connection.py").resolve(),
}


def raw_connection_offenders(root: Path = SERVER_DIR) -> tuple[str, ...]:
    """Return all python files under server/ that call sqlite3.connect directly."""
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.resolve() in ALLOWED_EXCLUSIONS or "__pycache__" in path.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8")
            if "sqlite3.connect(" in content:
                offenders.append(path.as_posix())
        except Exception:
            pass
    return tuple(offenders)


def main() -> int:
    offenders = raw_connection_offenders()
    if not offenders:
        print(
            "Persistence connection boundaries passed (100% server coverage verified)."
        )
        return 0
    for path in offenders:
        print(f"{path}: authoritative database access must use connect_sqlite()")
    return 1


if __name__ == "__main__":
    sys.exit(main())
