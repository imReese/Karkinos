"""start_server.sh dependency bootstrap behavior."""

from __future__ import annotations

from pathlib import Path


def test_start_server_bootstraps_frontend_dependencies_before_build():
    script = Path("scripts/start_server.sh").read_text()

    assert "ensure_frontend_dependencies" in script
    assert "npm install" in script
    assert "It installs missing frontend dependencies before building." in script
    assert script.index("ensure_frontend_dependencies") < script.index("npm run build")


def test_start_server_guides_local_data_source_configuration():
    script = Path("scripts/start_server.sh").read_text()

    assert "guide_data_source_configuration" in script
    assert "scripts/configure_data_source.py" in script
    assert script.index("guide_data_source_configuration") < script.index(
        "Starting Karkinos Web service"
    )


def test_start_server_no_live_path_avoids_empty_env_prefix_expansion():
    script = Path("scripts/start_server.sh").read_text()

    assert 'if [[ ${#ENV_PREFIX[@]} -gt 0 ]]; then\n\tif command -v setsid' in script
    assert 'env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"' in script
