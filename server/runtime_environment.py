"""Server 和命令行共用的启动配置加载，不在导入时读取外部环境。"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

# 延续已有启动约定：这些可选配置的空字符串表示未配置。
EMPTY_ENV_MEANS_UNSET = frozenset(
    {
        "KARKINOS_TUSHARE_TOKEN",
        "KARKINOS_TDX_DATA_SERVICE_KEY",
        "KARKINOS_TDX_USER",
        "KARKINOS_AI_API_KEY",
        "KARKINOS_AI_PROVIDER",
        "KARKINOS_AI_MODEL",
        "KARKINOS_AI_BASE_URL",
        "KARKINOS_TELEGRAM_BOT_TOKEN",
        "KARKINOS_TELEGRAM_CHAT_ID",
        "KARKINOS_WECHAT_SENDKEY",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    """本次启动的只读环境快照；默认表示不包含配置值或文件路径。"""

    values: Mapping[str, str] = field(repr=False)
    env_file: Path = field(repr=False)
    file_loaded: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


def load_runtime_environment_file(
    path: str | Path = ".env",
    *,
    environ: MutableMapping[str, str] | None = None,
    required: bool = False,
) -> bool:
    """显式合并一个 dotenv 文件，已有非空进程配置优先。

    不向父目录搜索文件。先完整校验，再一次性更新目标，避免失败后
    留下半份配置。未传 environ 时，仅此启动入口会更新 os.environ。
    """
    from dotenv import dotenv_values

    dotenv_path = Path(path).expanduser()
    if not dotenv_path.exists():
        if required:
            raise ValueError("environment file does not exist")
        return False
    try:
        values = dotenv_values(dotenv_path, encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ValueError("environment file could not be loaded") from None
    if any(value is None for value in values.values()):
        raise ValueError("environment file variable has no value")
    target = os.environ if environ is None else environ
    updates = {
        name: value
        for name, value in values.items()
        if value is not None
        and (
            name not in target
            or (name in EMPTY_ENV_MEANS_UNSET and not target[name].strip())
        )
    }
    target.update(updates)
    return True


def load_runtime_environment(
    explicit_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    default_path: str | Path = ".env",
) -> RuntimeEnvironment:
    """选择文件并生成快照，不修改输入映射或当前进程环境。

    文件选择优先级为：显式路径 > KARKINOS_ENV_FILE > 入口提供的默认路径。
    相对路径在入口处立即解析，后续工作目录变化不影响本次配置。
    """
    values = dict(os.environ if environ is None else environ)
    configured_path = values.get("KARKINOS_ENV_FILE")
    selected = explicit_path if explicit_path is not None else configured_path
    path = (
        Path(selected if selected is not None else default_path).expanduser().resolve()
    )
    loaded = load_runtime_environment_file(
        path, environ=values, required=selected is not None
    )
    return RuntimeEnvironment(values=values, env_file=path, file_loaded=loaded)


def load_selected_runtime_environment_file(
    explicit_path: str | Path | None = None,
) -> bool:
    """保留 Server 的启动接口；通用的文件选择和合并只维护一份实现。"""
    snapshot = load_runtime_environment(explicit_path)
    os.environ.update(snapshot.values)
    return snapshot.file_loaded
