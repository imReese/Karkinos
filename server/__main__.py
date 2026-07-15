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
    args = parser.parse_args()

    from server.bootstrap import load_runtime_config
    from server.config import ServerConfig

    config_overrides = {}
    if args.host is not None:
        config_overrides["host"] = args.host
    if args.port is not None:
        config_overrides["port"] = args.port
    if args.no_live:
        config_overrides["live_auto_start"] = False

    # 优先级：CLI 参数 > 环境变量 > config.json > 默认值。
    # 配置错误直接阻止启动。
    config = load_runtime_config(ServerConfig, **config_overrides)
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
        create_app(config_overrides=config_overrides),
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
