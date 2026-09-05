"""python -m server 入口。"""

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Karkinos Server")
    parser.add_argument(
        "--host", default=None, help="监听地址 (默认读 config.json 或 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口 (默认读 config.json 或 8000)",
    )
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
    validation_mode = parser.add_mutually_exclusive_group()
    validation_mode.add_argument(
        "--check-config",
        action="store_true",
        help="校验有效配置后退出，不启动服务或连接外部系统",
    )
    validation_mode.add_argument(
        "--check-state",
        action="store_true",
        help="校验配置并预检本地持久状态后退出",
    )
    validation_mode.add_argument(
        "--research-worker",
        action="store_true",
        help="启动独立、受管的 AI 收盘后研究 worker（不启动 HTTP 服务）",
    )
    validation_mode.add_argument(
        "--data-worker",
        action="store_true",
        help="启动独立数据 worker（不启动 HTTP 服务）",
    )
    validation_mode.add_argument(
        "--replay-state",
        action="store_true",
        help="在一次性状态副本上验证迁移、读取、任务和重启",
    )
    args = parser.parse_args()

    from server.bootstrap import (
        load_runtime_config,
        load_selected_runtime_environment_file,
        resolve_config_path,
    )
    from server.config import ServerConfig

    load_selected_runtime_environment_file(args.env_file)

    config_overrides = {}
    if args.host is not None:
        config_overrides["host"] = args.host
    if args.port is not None:
        config_overrides["port"] = args.port
    # 优先级：CLI > 已有进程环境 > .env > config.json > 默认值。
    # 配置错误直接阻止启动。
    config = load_runtime_config(ServerConfig, **config_overrides)
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
        import json

        from server.state_replay import replay_persistent_state

        def replay_app_factory():
            from server.app import create_app

            return create_app()

        print(json.dumps(replay_persistent_state(replay_app_factory), sort_keys=True))
        return
    if args.data_worker:
        if args.host is not None or args.port is not None or args.reload:
            parser.error(
                "--data-worker cannot be combined with --host, --port, or --reload"
            )
        import asyncio

        from server.workers.data_worker import run_data_worker
        from server.workers.supervisor import watch_supervisor_lifetime

        watch_supervisor_lifetime()
        asyncio.run(run_data_worker(config))
        return
    if args.research_worker:
        if args.host is not None or args.port is not None or args.reload:
            parser.error(
                "--research-worker cannot be combined with --host, --port, or --reload"
            )
        import asyncio

        from server.workers.ai_shadow_research_worker import (
            run_ai_shadow_research_worker,
        )

        asyncio.run(run_ai_shadow_research_worker(config))
        return
    host = config.host
    port = config.port
    reload = args.reload

    import uvicorn

    from server.app import create_app
    from server.workers.supervisor import supervised_data_worker

    if reload:
        # Reload starts a child process, so forward only explicit CLI values.
        forwarded = {}
        if args.host is not None:
            forwarded["KARKINOS_HOST"] = args.host
        if args.port is not None:
            forwarded["KARKINOS_PORT"] = str(args.port)
        previous = {name: os.environ.get(name) for name in forwarded}
        os.environ.update(forwarded)
        try:
            with supervised_data_worker(
                enabled=config.market_calendar_auto_sync, env_file=args.env_file
            ):
                uvicorn.run(
                    "server.app:create_app",
                    host=host,
                    port=port,
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
        enabled=config.market_calendar_auto_sync, env_file=args.env_file
    ):
        uvicorn.run(
            create_app(config_overrides=config_overrides, runtime_config=config),
            host=host,
            port=port,
            reload=False,
        )


if __name__ == "__main__":
    main()
