"""Durable data-root identity contracts."""

from __future__ import annotations

import json

import pytest

from server.persistence.database_identity import (
    IDENTITY_FILE,
    ensure_database_identity,
    read_database_identity,
)


def test_identity_is_created_once_and_reused(tmp_path) -> None:
    data = tmp_path / "data"
    first = ensure_database_identity(data, workspace_role="development")
    second = ensure_database_identity(data, workspace_role="development")

    assert second == first
    assert read_database_identity(data) == first
    payload = json.loads((data / IDENTITY_FILE).read_text(encoding="utf-8"))
    assert payload["database_uuid"] == first.database_uuid
    assert payload["workspace_role"] == "development"
    assert (data / IDENTITY_FILE).stat().st_mode & 0o777 == 0o600


def test_identity_rejects_workspace_role_mismatch(tmp_path) -> None:
    data = tmp_path / "data"
    ensure_database_identity(data, workspace_role="stable")

    with pytest.raises(RuntimeError, match="database_identity_role_mismatch"):
        ensure_database_identity(data, workspace_role="development")


def test_identity_rejects_symlinked_record(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    target = tmp_path / "identity.json"
    target.write_text("{}", encoding="utf-8")
    (data / IDENTITY_FILE).symlink_to(target)

    with pytest.raises(RuntimeError, match="database_identity_path_invalid"):
        read_database_identity(data)


def test_identity_rejects_corrupted_record(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / IDENTITY_FILE).write_text(
        '{"database_uuid":"not-a-uuid"}\n', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="database_identity_invalid"):
        read_database_identity(data)
