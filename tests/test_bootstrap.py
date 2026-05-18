from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import BacktestConfig, ServerConfig
from core.types import AssetClass, Symbol
from server.bootstrap import (
    build_strategy,
    build_watchlist,
    create_runtime_context,
    load_runtime_config,
    resolve_config_path,
    resolve_data_dir,
)


def test_load_runtime_config_prefers_json_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"initial_cash": 321000, "strategy": "dual_ma"}')
    monkeypatch.chdir(tmp_path)

    config = load_runtime_config()

    assert config.initial_cash == Decimal("321000")
    assert config.strategy == "dual_ma"


def test_build_watchlist_maps_asset_classes():
    config = BacktestConfig(
        assets=[
            {"symbol": "600519", "asset_class": "stock"},
            {"symbol": "510300", "asset_class": "etf"},
            {"symbol": "Au99.99", "asset_class": "gold"},
        ]
    )

    watchlist = build_watchlist(config)

    assert watchlist == [
        (Symbol("600519"), AssetClass.STOCK),
        (Symbol("510300"), AssetClass.FUND),
        (Symbol("Au99.99"), AssetClass.GOLD),
    ]


def test_build_strategy_uses_registered_params():
    config = BacktestConfig(strategy="dual_ma", short_period=7, long_period=31)
    event_bus = type(
        "Bus",
        (),
        {"subscribe": lambda *args: None, "publish": lambda *args: None},
    )()

    strategy = build_strategy(config, event_bus)

    assert strategy.short_period == 7
    assert strategy.long_period == 31


def test_create_runtime_context_builds_data_manager_with_default_store(monkeypatch):
    created = {}

    class FakeStore:
        def __init__(self, base_path="data/store"):
            created["store_path"] = base_path

    class FakeDataManager:
        def __init__(self, sources, store=None, default_source="akshare"):
            created["sources"] = sources
            created["store"] = store
            created["default_source"] = default_source

        @staticmethod
        def get_instrument(sym, ac):
            return (sym, ac)

    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    context = create_runtime_context(BacktestConfig())

    assert created["store_path"] == "data/store"
    assert created["store"].__class__ is FakeStore
    assert created["default_source"] == "akshare"
    assert context.watchlist[0][0] == Symbol("600519")


def test_main_uses_loaded_runtime_config_from_json(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"initial_cash": 200000, "start_date": "2025-01-02", "end_date": "2025-01-05", "assets": [{"symbol": "600519", "asset_class": "stock"}], "strategy": "dual_ma"}'
    )
    monkeypatch.chdir(tmp_path)

    import main

    captured = {}

    class FakeHandler:
        total_bars = 1

    class FakeManager:
        def get_bars(self, *args, **kwargs):
            return FakeHandler()

    class FakeEngine:
        def __init__(self, strategy, instruments, data_handlers, initial_cash):
            captured["initial_cash"] = initial_cash

        def run(self):
            return SimpleNamespace(
                initial_cash=Decimal("200000"),
                final_equity=Decimal("200000"),
                total_return=Decimal("0"),
                duration_days=3,
                equity_curve=[],
            )

    runtime = SimpleNamespace(
        data_manager=FakeManager(),
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
        instruments={Symbol("600519"): ("600519", AssetClass.STOCK)},
    )

    monkeypatch.setattr(main, "create_runtime_context", lambda config: runtime)
    monkeypatch.setattr(main, "build_strategy", lambda config, event_bus: object())
    monkeypatch.setattr(main, "BacktestEngine", FakeEngine)
    monkeypatch.setattr(main, "generate_report", lambda result: "ok")

    main.main()

    assert captured["initial_cash"] == Decimal("200000")


def test_load_runtime_config_allows_live_auto_start_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"live_auto_start": true}')
    monkeypatch.chdir(tmp_path)

    config = load_runtime_config(ServerConfig, live_auto_start=False)

    assert config.live_auto_start is False


def test_load_runtime_config_supports_env_config_path(tmp_path, monkeypatch):
    custom_config = tmp_path / "runtime-config.json"
    custom_config.write_text('{"strategy": "dual_ma", "initial_cash": 555000}')
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(custom_config))

    config = load_runtime_config()

    assert resolve_config_path() == custom_config
    assert config.initial_cash == Decimal("555000")


def test_create_runtime_context_supports_env_data_dir(monkeypatch):
    created = {}

    class FakeStore:
        def __init__(self, base_path="data/store"):
            created["store_path"] = base_path

    class FakeDataManager:
        def __init__(self, sources, store=None, default_source="akshare"):
            created["store"] = store

        @staticmethod
        def get_instrument(sym, ac):
            return (sym, ac)

    monkeypatch.setenv("KARKINOS_DATA_DIR", "/tmp/karkinos-data")
    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    create_runtime_context(BacktestConfig())

    assert resolve_data_dir() == "/tmp/karkinos-data"
    assert created["store_path"] == "/tmp/karkinos-data"


def test_create_app_accepts_config_overrides():
    from server.app import create_app

    app = create_app({"live_auto_start": False})

    assert app.state.config_overrides == {"live_auto_start": False}


def _cors_middleware_options(app):
    middleware = next(
        item for item in app.user_middleware if item.cls.__name__ == "CORSMiddleware"
    )
    return middleware.kwargs


def test_create_app_uses_local_dev_cors_defaults(monkeypatch):
    from server.app import create_app

    monkeypatch.delenv("KARKINOS_CORS_ALLOWED_ORIGINS", raising=False)

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert cors_options["allow_credentials"] is True


def test_create_app_accepts_cors_origins_from_config_file(
    tmp_path,
    monkeypatch,
):
    from server.app import create_app

    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"cors_allowed_origins": ["https://karkinos.example.com"]}'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KARKINOS_CORS_ALLOWED_ORIGINS", raising=False)

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == ["https://karkinos.example.com"]
    assert cors_options["allow_credentials"] is True


def test_create_app_accepts_cors_origins_from_env(monkeypatch):
    from server.app import create_app

    monkeypatch.setenv(
        "KARKINOS_CORS_ALLOWED_ORIGINS",
        "https://karkinos.example.com, http://localhost:5173",
    )

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == [
        "https://karkinos.example.com",
        "http://localhost:5173",
    ]
    assert cors_options["allow_credentials"] is True


def test_create_app_disables_cors_credentials_for_explicit_wildcard():
    from server.app import create_app

    app = create_app({"cors_allowed_origins": ["*"]})
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == ["*"]
    assert cors_options["allow_credentials"] is False


def test_create_app_serves_spa_index_for_client_routes(monkeypatch, tmp_path):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    for route in ["", "portfolio", "activity", "risk", "market", "settings"]:
        response = __import__("asyncio").run(
            static.get_response(
                route,
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/{route}" if route else "/",
                    "headers": [],
                },
            )
        )

        assert response.status_code == 200
        assert response.path.endswith("index.html")


def test_create_app_does_not_fallback_reserved_backend_namespaces(
    monkeypatch, tmp_path
):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    for route in ["api/missing", "ws/missing"]:
        with pytest.raises(StarletteHTTPException) as exc_info:
            __import__("asyncio").run(
                static.get_response(
                    route,
                    {
                        "type": "http",
                        "method": "GET",
                        "path": f"/{route}",
                        "headers": [],
                    },
                )
            )

        assert exc_info.value.status_code == 404


def test_create_app_keeps_missing_static_assets_as_404(monkeypatch, tmp_path):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    with pytest.raises(StarletteHTTPException) as exc_info:
        __import__("asyncio").run(
            static.get_response(
                "assets/missing.js",
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/assets/missing.js",
                    "headers": [],
                },
            )
        )

    assert exc_info.value.status_code == 404


def _run_staticfile_threadpool_inline(monkeypatch):
    import starlette.staticfiles as staticfiles

    async def run_sync_inline(func, *args, **kwargs):
        return func(*args)

    monkeypatch.setattr(staticfiles.anyio.to_thread, "run_sync", run_sync_inline)
