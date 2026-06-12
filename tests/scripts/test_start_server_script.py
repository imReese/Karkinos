"""start_server.sh dependency bootstrap behavior."""

from __future__ import annotations

from pathlib import Path


def test_start_server_bootstraps_frontend_dependencies_before_build():
    script = Path("scripts/start_server.sh").read_text()

    assert "ensure_frontend_dependencies" in script
    assert "npm install" in script
    assert "It installs missing frontend dependencies before building." in script
    assert script.index("ensure_frontend_dependencies") < script.index("npm run build")
