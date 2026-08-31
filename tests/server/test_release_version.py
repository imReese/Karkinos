import json
import tomllib
from pathlib import Path

import server
from server.app import create_app


def test_backend_and_web_publish_the_same_release_version():
    project_root = Path(__file__).parents[2]
    web_package = json.loads(
        (project_root / "web" / "package.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert server.__version__ == "0.3.5"
    assert web_package["version"] == server.__version__
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "server.__version__"
    }
    assert create_app({"live_auto_start": False}).version == server.__version__
