"""TDX SDK 的进程启动配置适配，不负责读取 .env 或执行行情请求。

已核对 tdxaidata 1.0.2：TDX_AI_DATA_LIB 可以指定动态库，SDK 会切换到
库目录并读取 TdxAiData.ini。调用方必须在子进程使用这里生成的路径，
由父进程管理临时目录生命周期；不得在 Server 进程初始化该 SDK。
"""

from __future__ import annotations

import configparser
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

TDX_KEY_ENV = "KARKINOS_TDX_DATA_SERVICE_KEY"
TDX_USER_ENV = "KARKINOS_TDX_USER"


class TdxRuntimeConfigurationError(ValueError):
    """启动配置不完整或 SDK 布局尚未验证；错误消息不包含秘密值。"""


@dataclass(frozen=True, slots=True)
class TdxRuntimeSettings:
    """从本次启动快照中提取的 TDX 配置，不包含其他服务的凭据。"""

    data_service_key: str = field(default="", repr=False)
    user: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        for name in ("data_service_key", "user"):
            value = getattr(self, name)
            # 原生 INI 只接收单行文本，禁止通过换行或控制字符注入新配置。
            if not isinstance(value, str) or any(
                ord(character) < 32 or ord(character) == 127 for character in value
            ):
                raise TdxRuntimeConfigurationError(f"tdx_{name}_invalid")
            object.__setattr__(self, name, value.strip())

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> TdxRuntimeSettings:
        """只解析调用方传入的映射，不自行读取进程全局变量或文件。"""
        return cls(
            data_service_key=values.get(TDX_KEY_ENV, ""),
            user=values.get(TDX_USER_ENV, ""),
        )

    @property
    def configured(self) -> bool:
        return bool(self.data_service_key)

    def require_credentials(self) -> None:
        if not self.configured:
            raise TdxRuntimeConfigurationError("tdx_data_service_key_missing")


def _sdk_library_directory() -> Path:
    """只读发行包元数据，不导入 SDK，也不加载动态库。"""
    try:
        distribution = metadata.distribution("tdxaidata")
    except metadata.PackageNotFoundError:
        raise TdxRuntimeConfigurationError("tdx_sdk_not_installed") from None
    if distribution.version != "1.0.2":
        raise TdxRuntimeConfigurationError("tdx_sdk_runtime_version_unsupported")
    return Path(distribution.locate_file("tdxaidata/lib")).resolve()


@contextmanager
def prepare_tdx_runtime(
    settings: TdxRuntimeSettings,
) -> Iterator[Path]:
    """为一个受管子进程准备临时 SDK 目录，退出上下文后清理。

    返回应写入子进程 TDX_AI_DATA_LIB 的绝对路径，不修改 os.environ。
    不把秘密放在参数、返回报告、site-packages 或保留的数据输出目录中。
    Key 更新后下一次调用会生成新的配置，不共享 SDK 的进程内单例。
    """
    settings.require_credentials()
    source = _sdk_library_directory()
    if os.name == "nt":
        names = ("TdxAiData.dll", "mfc100.dll", "msvcp100.dll", "msvcr100.dll")
    elif sys.platform == "darwin":
        names = ("libTdxAiData.dylib",)
    elif sys.platform.startswith("linux"):
        names = ("libTdxAiData.so",)
    else:
        raise TdxRuntimeConfigurationError("tdx_sdk_platform_unsupported")
    template = source / "TdxAiData.ini"
    if not template.is_file() or any(not (source / name).is_file() for name in names):
        raise TdxRuntimeConfigurationError("tdx_sdk_runtime_files_missing")

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # 保留供应商配置键的大小写，不假设原生解析器不区分大小写。
    try:
        with template.open(encoding="utf-8-sig") as input_file:
            config.read_file(input_file)
        # 仅接受已核对版本的模板结构，不能把安装目录中未知配置带入运行环境。
        if config.defaults() or set(config.sections()) != {
            "TcHqHost",
            "TcDsHost",
            "Token",
        }:
            raise TdxRuntimeConfigurationError("tdx_sdk_config_template_invalid")
    except (OSError, UnicodeError, configparser.Error):
        raise TdxRuntimeConfigurationError("tdx_sdk_config_template_invalid") from None
    config.remove_section("Token")
    config.add_section("Token")
    config.set("Token", "token", settings.data_service_key)
    if settings.user:
        config.set("Token", "user", settings.user)

    # 必须由父进程持有上下文，SDK 崩溃或请求超时也会执行目录清理。
    with tempfile.TemporaryDirectory(prefix="karkinos-tdx-runtime-") as temporary:
        runtime = Path(temporary).resolve()
        runtime.chmod(0o700)
        for name in names:
            shutil.copyfile(source / name, runtime / name)
            (runtime / name).chmod(0o700)
        path = runtime / "TdxAiData.ini"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            config.write(output, space_around_delimiters=False)
        yield runtime / names[0]
