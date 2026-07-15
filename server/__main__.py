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
        "--no-live", action="store_true", help="启动时不自动开启实时监控"
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="环境变量文件（默认读取 KARKINOS_ENV_FILE 或 ./.env）",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="校验有效配置后退出，不启动服务或连接外部系统",
    )
    args = parser.parse_args()

    from server.bootstrap import (
        load_runtime_config,
        load_runtime_environment_file,
        resolve_config_path,
    )
    from server.config import ServerConfig

    configured_env_file = os.environ.get("KARKINOS_ENV_FILE")
    env_file = args.env_file or configured_env_file or ".env"
    load_runtime_environment_file(
        env_file,
        required=args.env_file is not None or configured_env_file is not None,
    )

    config_overrides = {}
    if args.host is not None:
        config_overrides["host"] = args.host
    if args.port is not None:
        config_overrides["port"] = args.port
    if args.no_live:
        config_overrides["live_auto_start"] = False

    # 优先级：CLI > 已有进程环境 > .env > config.json > 默认值。
    # 配置错误直接阻止启动。
    config = load_runtime_config(ServerConfig, **config_overrides)
    if args.check_config:
        print(f"Karkinos configuration valid: {resolve_config_path()}")
        return
    host = config.host
    port = config.port
    reload = args.reload

    import uvicorn

    from server.app import create_app

    if reload:
        # Reload starts a child process, so forward only explicit CLI values.
        forwarded = {}
        if args.host is not None:
            forwarded["KARKINOS_HOST"] = args.host
        if args.port is not None:
            forwarded["KARKINOS_PORT"] = str(args.port)
        if args.no_live:
            forwarded["KARKINOS_LIVE_AUTO_START"] = "false"
        previous = {name: os.environ.get(name) for name in forwarded}
        os.environ.update(forwarded)
        try:
            uvicorn.run(
                "server.app:create_app",
                host=host,
                port=port,
                reload=True,
                factory=True,
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        return

    uvicorn.run(
        create_app(config_overrides=config_overrides, runtime_config=config),
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
