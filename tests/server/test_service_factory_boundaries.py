from pathlib import Path
from types import SimpleNamespace

import pytest

from server.ai_runtime.capture import CaptureSelectionError
from server.ai_runtime.provider_connectivity import ConnectivityConfigurationError
from server.services.ai_context_capture_factory import (
    database_path as capture_database_path,
)
from server.services.strategy_research_factory import (
    database_path as research_database_path,
)


@pytest.mark.parametrize(
    "resolver",
    [capture_database_path, research_database_path],
)
def test_new_service_factories_use_the_public_database_path(resolver, tmp_path):
    public_path = tmp_path / "app.db"

    assert resolver(SimpleNamespace(path=public_path)) == Path(public_path)


@pytest.mark.parametrize(
    ("resolver", "error_type"),
    [
        (capture_database_path, CaptureSelectionError),
        (research_database_path, ConnectivityConfigurationError),
    ],
)
def test_new_service_factories_fail_closed_without_public_database_path(
    resolver,
    error_type,
    tmp_path,
):
    with pytest.raises(error_type, match="database path is unavailable"):
        resolver(SimpleNamespace(_path=tmp_path / "private.db"))
