"""python -m server: prepare persistent state before starting runtime writers."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any


def _report_startup_failure(exc: BaseException) -> None:
    """Notify the development parent even if Uvicorn's reloader stays alive."""
    configured = os.environ.get("KARKINOS_STARTUP_STATUS_FILE")
    token = os.environ.get("KARKINOS_STARTUP_STATUS_TOKEN")
    if not configured or not token:
        return
    path = Path(configured)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        # No exception text, environment values or credentials in the IPC record.
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(
                {"token": token, "state": "failed", "error_type": type(exc).__name__},
                output,
            )
        os.replace(temporary, path)
    except OSError:
        pass  # The original startup error must remain the primary exception.
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def create_runtime_app(**kwargs: Any):
    """Uvicorn factory with an explicit startup-failure channel to its parent."""
    try:
        from server.app import create_app

        app = create_app(**kwargs)
    except BaseException as exc:
        _report_startup_failure(exc)
        raise
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        started = False
        try:
            async with original(application) as state:
                started = True
                yield state
        except BaseException as exc:
            if not started:
                _report_startup_failure(exc)
            raise

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Karkinos Server")
    parser.add_argument("--host", default=None, help="监听地址 (默认读配置)")
    parser.add_argument("--port", type=int, default=None, help="监听端口 (默认读配置)")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument(
        "--reload-exclude",
        action="append",
        default=[],
        help="热重载排除的 glob；可重复传入",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="环境变量文件（默认读取 KARKINOS_ENV_FILE 或 ./.env）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="--database-status 使用 JSON 输出",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-config", action="store_true", help="仅校验配置")
    mode.add_argument(
        "--check-state",
        action="store_true",
        help="准备并校验隔离状态副本（会执行迁移；保留发布工具兼容）",
    )
    mode.add_argument(
        "--database-status",
        action="store_true",
        help="只读诊断数据库，不创建或升级数据库",
    )
    mode.add_argument(
        "--prepare-database",
        action="store_true",
        help="备份并准备数据库后退出，不启动服务",
    )
    mode.add_argument(
        "--research-worker",
        action="store_true",
        help="启动受管研究 worker，不启动 HTTP 服务",
    )
    mode.add_argument(
        "--data-worker",
        action="store_true",
        help="启动受管数据 worker，不启动 HTTP 服务",
    )
    mode.add_argument(
        "--replay-state",
        action="store_true",
        help="在一次性状态副本上验证迁移、读取、任务和重启",
    )
    args = parser.parse_args()
    if args.json and not args.database_status:
        parser.error("--json requires --database-status")
    if (args.data_worker or args.research_worker) and (
        args.host is not None or args.port is not None or args.reload
    ):
        parser.error("worker mode cannot be combined with --host, --port, or --reload")

    from server.bootstrap import (
        load_runtime_config,
        load_selected_runtime_environment_file,
        resolve_config_path,
    )
    from server.config import ServerConfig
    from server.runtime_paths import resolve_data_dir

    load_selected_runtime_environment_file(args.env_file)
    database_path = Path(resolve_data_dir()) / "app.db"
    if args.database_status:
        from server.persistence.migration_lifecycle import inspect_database

        status = inspect_database(database_path)
        if args.json:
            print(json.dumps(status.as_dict(), ensure_ascii=False, sort_keys=True))
        else:
            print(status.explain())
        if status.blocked:
            raise SystemExit(2)
        return

    overrides = {}
    if args.host is not None:
        overrides["host"] = args.host
    if args.port is not None:
        overrides["port"] = args.port
    config = load_runtime_config(ServerConfig, **overrides)
    if args.check_config:
        print(f"Karkinos configuration valid: {resolve_config_path()}")
        return
    if args.check_state:
        from server.state_preflight import preflight_persistent_state

        preflight_persistent_state()
        print("Karkinos persisted state compatible")
        return
    if args.replay_state:
        if os.environ.get("KARKINOS_STATE_CLONE") != "1":
            parser.error("--replay-state requires an explicitly isolated state clone")
        from server.state_replay import replay_persistent_state

        print(json.dumps(replay_persistent_state(create_runtime_app), sort_keys=True))
        return

    from server.persistence.database_identity import ensure_database_identity
    from server.persistence.initializer import database_runtime, initialize_database

    ensure_database_identity(
        database_path.parent,
        workspace_role=os.environ.get("KARKINOS_WORKSPACE_ROLE"),
    )

    # This runs in the parent, before Uvicorn/reloader or any worker is spawned.
    # Ordinary uncommitted development code is allowed; the actual migration
    # definitions and source identity are archived when preparation is needed.
    try:
        initialize_database(database_path)
        if args.prepare_database:
            print(f"Karkinos database ready: {database_path}")
            return
        with database_runtime(database_path):
            _run_runtime(args, config, overrides)
    except (RuntimeError, OSError, sqlite3.DatabaseError) as exc:
        _report_startup_failure(exc)
        print(f"Karkinos startup refused:\n{exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _run_runtime(
    args: argparse.Namespace,
    config: Any,
    overrides: dict[str, Any],
) -> None:
    if args.data_worker:
        import asyncio

        from server.workers.data_worker import run_data_worker
        from server.workers.supervisor import watch_supervisor_lifetime

        watch_supervisor_lifetime()
        asyncio.run(run_data_worker(config))
        return
    if args.research_worker:
        import asyncio

        from server.workers.ai_shadow_research_worker import (
            run_ai_shadow_research_worker,
        )

        asyncio.run(run_ai_shadow_research_worker(config))
        return

    import uvicorn

    from server.workers.supervisor import supervised_data_worker

    if args.reload:
        forwarded = {}
        if args.host is not None:
            forwarded["KARKINOS_HOST"] = args.host
        if args.port is not None:
            forwarded["KARKINOS_PORT"] = str(args.port)
        previous = {name: os.environ.get(name) for name in forwarded}
        os.environ.update(forwarded)
        try:
            with supervised_data_worker(
                enabled=config.market_calendar_auto_sync,
                env_file=args.env_file,
            ):
                uvicorn.run(
                    "server.__main__:create_runtime_app",
                    host=config.host,
                    port=config.port,
                    reload=True,
                    reload_excludes=args.reload_exclude or None,
                    factory=True,
                )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        return

    with supervised_data_worker(
        enabled=config.market_calendar_auto_sync,
        env_file=args.env_file,
    ):
        uvicorn.run(
            create_runtime_app(config_overrides=overrides, runtime_config=config),
            host=config.host,
            port=config.port,
            reload=False,
        )


if __name__ == "__main__":
    main()
