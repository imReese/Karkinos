"""TDX 手动检查入口测试；只替换原生 SDK，不访问真实数据服务。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "data" / "check_tdx_daily.py"
_DAY = "2026-09-14"
_PRIVATE = "private-value-that-must-not-appear"

_FAKE_SDK = """\
import json
import os
import time
from pathlib import Path

Path(os.environ["TDX_TEST_IMPORTED"]).write_text("imported")
secret = "private-value-that-must-not-appear"
os.write(1, secret.encode())
os.write(2, secret.encode())
mode = os.environ.get("TDX_TEST_MODE", "ok")
if mode == "native_error":
    raise OSError(secret)
if mode == "dependency_error":
    raise ModuleNotFoundError(secret, name=secret)
if mode == "crash":
    os._exit(17)
if mode == "timeout":
    time.sleep(30)


class tqs:
    @staticmethod
    def get_market_data(**kwargs):
        with open(os.environ["TDX_TEST_CALLS"], "a") as output:
            output.write(json.dumps(kwargs) + "\\n")
        if mode == "request_error":
            raise RuntimeError(secret)
        if mode == "bad_response":
            return None
        import pandas as pd
        values = {
            "Open": 10.31, "High": 10.52, "Low": 10.20, "Close": 10.48,
            "Volume": 123456, "Amount": 128.391242,
        }
        if mode == "empty":
            return {field: pd.DataFrame() for field in values}
        if mode == "bad_ohlc":
            values["Close"] = 1.0
        if mode == "missing_field":
            del values["Close"]
        session = "2026-09-13" if mode == "wrong_date" else kwargs["start_time"]
        return {
            field: pd.DataFrame(
                [[value]], index=[pd.Timestamp(session)], columns=kwargs["stock_list"]
            )
            for field, value in values.items()
        }


if mode == "signature_mismatch":
    def incompatible(field_list, stock_list, period, start_time, end_time,
                     count, dividend_type):
        raise AssertionError("must not be called")
    tqs.get_market_data = staticmethod(incompatible)
"""


@pytest.fixture
def sdk_env(tmp_path: Path) -> dict[str, str]:
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "tdxaidata.py").write_text(_FAKE_SDK, encoding="utf-8")
    (vendor / "TdxAiData.ini").write_text("do not rewrite SDK configuration")
    return {
        **os.environ,
        "PYTHONPATH": str(vendor),
        "TDX_TEST_IMPORTED": str(tmp_path / "imported"),
        "TDX_TEST_CALLS": str(tmp_path / "calls.jsonl"),
        "KARKINOS_TDX_DATA_SERVICE_KEY": _PRIVATE,
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--date", _DAY, *args],
        cwd=Path(env["TDX_TEST_IMPORTED"]).parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


def _calls(env: dict[str, str]) -> list[dict[str, object]]:
    path = Path(env["TDX_TEST_CALLS"])
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_preflight_does_not_import_sdk_call_provider_or_create_output(
    tmp_path: Path, sdk_env: dict[str, str]
) -> None:
    output = tmp_path / "unused-output"
    completed = _run(sdk_env, "--output-dir", str(output))
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "preflight"
    assert report["network_attempted"] is False
    assert report["sdk_module"] == "tdxaidata"
    assert "not preverified" in report["credential_source"]
    assert not Path(sdk_env["TDX_TEST_IMPORTED"]).exists()
    assert not Path(sdk_env["TDX_TEST_CALLS"]).exists()
    assert not output.exists()
    assert _PRIVATE not in completed.stdout + completed.stderr


def test_missing_sdk_has_safe_actionable_preflight_failure(tmp_path: Path) -> None:
    # -S 排除已安装包，即使 CI 安装了真实 SDK，也能确定性验证缺包场景。
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--date", _DAY],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["error_code"] == "sdk_not_installed"


@pytest.mark.parametrize(
    "arguments",
    [
        ("--date", "9999-01-01"),
        ("--date", "20260914"),
        ("--symbol", "600000,000001"),
        ("--symbol", "600000.SH"),
        ("--timeout", "0"),
    ],
)
def test_invalid_request_is_rejected_before_loading_sdk(
    sdk_env: dict[str, str], arguments: tuple[str, ...]
) -> None:
    completed = _run(sdk_env, "--allow-network", *arguments)
    assert completed.returncode == 2
    assert not Path(sdk_env["TDX_TEST_IMPORTED"]).exists()
    assert not Path(sdk_env["TDX_TEST_CALLS"]).exists()


def test_existing_output_is_never_overwritten(
    tmp_path: Path, sdk_env: dict[str, str]
) -> None:
    sentinel = tmp_path / "existing-data"
    sentinel.write_text("keep")
    completed = _run(sdk_env, "--allow-network", "--output-dir", str(sentinel))
    assert completed.returncode == 2
    assert sentinel.read_text() == "keep"
    assert not Path(sdk_env["TDX_TEST_IMPORTED"]).exists()


def test_output_inside_checkout_is_rejected(sdk_env: dict[str, str]) -> None:
    completed = _run(sdk_env, "--output-dir", str(REPO_ROOT / "tdx-smoke-output"))
    assert completed.returncode == 2
    assert not Path(sdk_env["TDX_TEST_IMPORTED"]).exists()


@pytest.mark.parametrize("retain", [False, True])
def test_live_check_uses_default_sdk_loader_and_replays_real_pipeline(
    tmp_path: Path, sdk_env: dict[str, str], retain: bool
) -> None:
    output = tmp_path / "retained-check"
    arguments = ("--output-dir", str(output)) if retain else ()
    completed = _run(sdk_env, "--allow-network", *arguments)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "ok"
    assert report["quality"] == "pass"
    assert report["offline_replay"] is True
    assert report["row_count"] == 1
    assert report["artifacts_retained"] is retain
    assert report["independent_market_accuracy_check"] is False
    assert report["dataset_id"].startswith("sha256:")
    assert report["bar"]["symbol"] == "600000"
    assert report["bar"]["session_date"] == _DAY
    assert report["bar"]["amount_cny"] == "1283912.42000000"
    assert report["bar"]["available_at"] == report["bar"]["captured_at"]
    assert _PRIVATE not in completed.stdout + completed.stderr
    assert (Path(sdk_env["PYTHONPATH"]) / "TdxAiData.ini").read_text() == (
        "do not rewrite SDK configuration"
    )
    assert _calls(sdk_env) == [
        {
            "field_list": ["Open", "High", "Low", "Close", "Volume", "Amount"],
            "stock_list": ["600000.SH"],
            "period": "1d",
            "start_time": "20260914",
            "end_time": "20260914",
            "count": -1,
            "dividend_type": "none",
            "fill_data": False,
        }
    ]
    if retain:
        from data.dataset.catalog import DatasetCatalog
        from data.dataset.reader import read_daily_bar_dataset
        from data.storage.objects import ContentAddressedObjectStore

        ref = DatasetCatalog(output / "index").get(report["dataset_id"]).ref
        replayed = read_daily_bar_dataset(
            ContentAddressedObjectStore(output / "objects"), ref
        )
        assert replayed.row_count == 1
    else:
        assert report["output_dir"] is None
        assert not output.exists()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("request_error", "check_failed"),
        ("native_error", "sdk_unavailable_check_installation_and_native_library"),
        ("empty", "no_data_check_session_permissions_and_sdk_config"),
        ("wrong_date", "check_failed"),
        ("bad_ohlc", "check_failed"),
        ("signature_mismatch", "check_failed"),
        ("bad_response", "check_failed"),
        ("missing_field", "check_failed"),
        ("dependency_error", "sdk_unavailable_check_installation_and_native_library"),
        ("crash", "worker_failed"),
        ("timeout", "timeout"),
    ],
)
def test_live_failure_never_retries_publishes_success_or_exposes_sdk_logs(
    tmp_path: Path, sdk_env: dict[str, str], mode: str, code: str
) -> None:
    output = tmp_path / "failed-check"
    env = {**sdk_env, "TDX_TEST_MODE": mode}
    arguments = ("--timeout", "1") if mode == "timeout" else ()
    completed = _run(env, "--allow-network", "--output-dir", str(output), *arguments)
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["status"] == "error"
    assert report["error_code"] == code
    assert "dataset_id" not in report
    assert _PRIVATE not in completed.stdout + completed.stderr
    assert not (output / "index" / "catalog" / "datasets.sqlite3").exists()
    if Path(env["TDX_TEST_CALLS"]).exists():
        assert len(_calls(env)) == 1

    expected = {
        "request_error": [
            {"type": "TdxProviderError", "code": "tdx_get_market_data_failed"},
            {"type": "RuntimeError"},
        ],
        "native_error": [
            {"type": "TdxProviderUnavailableError", "code": "tdx_sdk_load_failed"},
            {"type": "OSError"},
        ],
        "dependency_error": [
            {
                "type": "TdxProviderUnavailableError",
                "code": "tdx_sdk_dependency_missing",
            },
            {"type": "ModuleNotFoundError"},
        ],
        "empty": [{"type": "DailyBarIngestionNoData"}],
        "wrong_date": [
            {
                "type": "TdxProviderResponseError",
                "code": "tdx_response_session_unexpected",
            },
        ],
        "bad_ohlc": [
            {"type": "ValueError", "code": "daily_bar_low_above_open_or_close"},
        ],
        "signature_mismatch": [
            {"type": "TdxProviderError", "code": "tdx_get_market_data_failed"},
            {
                "type": "TypeError",
                "code": "sdk_unexpected_keyword_argument",
                "argument": "fill_data",
            },
        ],
        "bad_response": [
            {"type": "TdxProviderResponseError", "code": "tdx_response_must_be_dict"},
        ],
        "missing_field": [
            {
                "type": "TdxProviderResponseError",
                "code": "tdx_response_field_missing",
                "field": "Close",
            },
        ],
    }
    if mode in expected:
        assert report["diagnostics"] == expected[mode]


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("tdx_smoke_diagnostics", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagnostics_never_echo_unknown_names_values_or_call_str() -> None:
    module = _load_smoke_module()
    unknown_type = type(_PRIVATE, (Exception,), {})

    class UnsafeValue:
        def __str__(self):
            raise AssertionError("must not stringify SDK values")

    cases = (
        (unknown_type(_PRIVATE), {"type": "Exception"}),
        (RuntimeError(UnsafeValue()), {"type": "RuntimeError"}),
        (
            ValueError("tdx_response_field_missing:" + _PRIVATE),
            {"type": "ValueError", "code": "tdx_response_field_missing"},
        ),
        (
            TypeError(f"unexpected keyword argument '{_PRIVATE}'"),
            {"type": "TypeError"},
        ),
        (ValueError("tdx_get_market_data_failed:" + _PRIVATE), {"type": "ValueError"}),
    )
    for exc, expected in cases:
        report = module._failure("ingestion", "check_failed", exc)
        assert report["diagnostics"] == [expected]
        assert _PRIVATE not in json.dumps(report)


def test_diagnostics_bound_exception_chains_and_respect_suppressed_context() -> None:
    module = _load_smoke_module()
    outer = RuntimeError(_PRIVATE)
    inner = TypeError(_PRIVATE)
    outer.__cause__ = inner
    inner.__cause__ = outer
    assert module._exception_diagnostics(outer) == [
        {"type": "RuntimeError"},
        {"type": "TypeError"},
    ]

    outer = RuntimeError(_PRIVATE)
    outer.__context__ = ValueError(_PRIVATE)
    assert len(module._exception_diagnostics(outer)) == 2
    outer.__suppress_context__ = True
    assert module._exception_diagnostics(outer) == [{"type": "RuntimeError"}]

    for _ in range(10):
        wrapper = RuntimeError(_PRIVATE)
        wrapper.__cause__ = outer
        outer = wrapper
    assert len(module._exception_diagnostics(outer)) == 4
