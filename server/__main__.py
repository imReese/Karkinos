"""python -m server 入口。"""

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="MyQuant Server")
    parser.add_argument(
        "--host", default=None, help="监听地址 (默认读 config.json 或 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="监听端口 (默认读 config.json 或 8000)"
    )
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument(
        "--no-live", action="store_true", help="启动时不自动开启实时监控"
    )
    args = parser.parse_args()

    # 尝试从 config.json 读取默认值
    try:
        from config import ServerConfig
        from server.bootstrap import load_runtime_config

        config = load_runtime_config(
            ServerConfig,
            **({"live_auto_start": False} if args.no_live else {}),
        )
    except Exception:
        config = None

    # 优先级：CLI 参数 > 环境变量 > config.json > 默认值
    env_host = os.environ.get("MYQUANT_HOST") or None
    env_port = int(os.environ.get("MYQUANT_PORT", "0")) or None
    host = args.host or env_host or (config.host if config else "0.0.0.0")
    port = args.port or env_port or (config.port if config else 8000)
    reload = args.reload

    import uvicorn
    from server.app import create_app

    if args.no_live:
        os.environ["MYQUANT_LIVE_AUTO_START"] = "false"
    else:
        os.environ.pop("MYQUANT_LIVE_AUTO_START", None)

    if reload:
        uvicorn.run(
            "server.app:create_app",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
        return

    uvicorn.run(
        create_app(
            config_overrides={"live_auto_start": False} if args.no_live else {}
        ),
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
