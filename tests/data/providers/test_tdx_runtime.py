"""TDX 凭据适配测试；不调用真实原生库或数据服务。"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
from pathlib import Path

import pytest

from data.providers import tdx_runtime
from data.providers.tdx_runtime import (
    TdxRuntimeConfigurationError,
    TdxRuntimeSettings,
    prepare_tdx_runtime,
)


@pytest.fixture
def sdk_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "installed-sdk"
    source.mkdir()
    for name in (
        "TdxAiData.dll",
        "mfc100.dll",
        "msvcp100.dll",
        "msvcr100.dll",
        "libTdxAiData.so",
        "libTdxAiData.dylib",
    ):
        (source / name).write_bytes(b"native-library-placeholder")
    (source / "TdxAiData.ini").write_text(
        "[TcHqHost]\nHostNum=1\n[TcDsHost]\nHostNum=1\n[Token]\ntoken=old-installed-token\nuser=old-user\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tdx_runtime, "_sdk_library_directory", lambda: source)
    return source


def test_settings_are_explicit_frozen_and_do_not_expose_credentials() -> None:
    settings = TdxRuntimeSettings.from_environment(
        {"KARKINOS_TDX_DATA_SERVICE_KEY": "private-value"}
    )
    assert settings.configured
    assert "private-value" not in repr(settings)
    assert not TdxRuntimeSettings.from_environment({}).configured
    with pytest.raises(AttributeError):
        settings.user = "changed"  # type: ignore[misc]
    with pytest.raises(
        TdxRuntimeConfigurationError, match="tdx_data_service_key_missing"
    ):
        TdxRuntimeSettings().require_credentials()


@pytest.mark.parametrize(
    "value", ["abc\n[Token]\ntoken=other", "abc\rdef", "abc\x00def"]
)
def test_control_characters_cannot_inject_ini_values(value: str) -> None:
    with pytest.raises(TdxRuntimeConfigurationError) as caught:
        TdxRuntimeSettings(data_service_key=value)
    assert value not in str(caught.value)


def test_private_runtime_preserves_installation_and_parent_environment(
    sdk_files: Path,
) -> None:
    installed = {p.name: p.read_bytes() for p in sdk_files.iterdir()}
    environment, cwd = dict(os.environ), Path.cwd()
    # 百分号不应触发 ConfigParser 的插值，临时目录中只留下本次注入的凭据。
    settings = TdxRuntimeSettings(data_service_key="private%value", user="test-user")
    with prepare_tdx_runtime(settings) as library:
        config_path = library.parent / "TdxAiData.ini"
        config = configparser.ConfigParser(interpolation=None)
        config.read(config_path, encoding="utf-8")
        assert config["Token"]["token"] == "private%value"
        assert config["Token"]["user"] == "test-user"
        assert "old-installed-token" not in config_path.read_text()
        assert library.read_bytes() == b"native-library-placeholder"
        assert library.parent != sdk_files
        if os.name == "posix":
            assert config_path.stat().st_mode & 0o777 == 0o600
            assert library.parent.stat().st_mode & 0o777 == 0o700
    assert not library.parent.exists()
    assert dict(os.environ) == environment
    assert Path.cwd() == cwd
    assert {p.name: p.read_bytes() for p in sdk_files.iterdir()} == installed


def test_runtimes_do_not_share_credentials_and_cleanup_on_exception(
    sdk_files: Path,
) -> None:
    with prepare_tdx_runtime(TdxRuntimeSettings("first")) as first:
        with pytest.raises(RuntimeError):
            with prepare_tdx_runtime(TdxRuntimeSettings("second")) as second:
                assert first.parent != second.parent
                assert "first" in (first.parent / "TdxAiData.ini").read_text()
                assert "second" in (second.parent / "TdxAiData.ini").read_text()
                raise RuntimeError("worker failed")
        assert not second.parent.exists()
        assert first.exists()
    assert not first.parent.exists()


def test_missing_sdk_files_fail_before_initializing_native_code(
    sdk_files: Path,
) -> None:
    (sdk_files / "TdxAiData.ini").unlink()
    with pytest.raises(TdxRuntimeConfigurationError, match="runtime_files_missing"):
        with prepare_tdx_runtime(TdxRuntimeSettings("test-value")):
            pytest.fail("must not yield a runtime")


def test_actual_pinned_sdk_reads_injected_ini_from_library_directory() -> None:
    # 使用发行包真实 Python 封装，仅替换 ctypes 原生函数并禁止网络。
    # 这样不会只靠一个同样写错的 Fake SDK 来证明初始化约定。
    source = r"""
import configparser
import ctypes
import os
import socket
from pathlib import Path

def deny_network(*args, **kwargs):
    raise AssertionError("SDK contract test must not use network")
socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.getaddrinfo = deny_network
runtime = Path(os.environ["TDX_AI_DATA_LIB"]).parent
class NativeFunction:
    def __init__(self, name):
        self.name = name
    def __call__(self, *args):
        if self.name == "start":
            assert Path.cwd() == runtime
            config = configparser.ConfigParser(interpolation=None)
            config.read("TdxAiData.ini", encoding="utf-8")
            assert config["Token"]["token"] == "native-contract-test"
            assert args == (b"",)
        return 0
class NativeLibrary:
    def __getattr__(self, name):
        function = NativeFunction(name)
        setattr(self, name, function)
        return function
def load_library(path, **kwargs):
    assert Path(path).parent == runtime
    return NativeLibrary()
ctypes.CDLL = load_library
ctypes.WinDLL = load_library
from tdxaidata import tqs
# 公开接口触发 SDK 的真实初始化和 INI 读取；原生替身不返回行情数据。
assert tqs.get_market_data(field_list=["Open"], stock_list=["600000.SH"],
                           period="1d", start_time="20260914", end_time="20260914") == {}
"""
    cwd = Path.cwd()
    with prepare_tdx_runtime(TdxRuntimeSettings("native-contract-test")) as library:
        result = subprocess.run(
            [sys.executable, "-c", source],
            env={**os.environ, "TDX_AI_DATA_LIB": str(library)},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert Path.cwd() == cwd
