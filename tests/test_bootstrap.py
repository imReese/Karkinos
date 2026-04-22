from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

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
    config_path.write_text(
        '{"initial_cash": 321000, "strategy": "dual_ma"}'
    )
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
    monkeypatch.setenv("MYQUANT_CONFIG_PATH", str(custom_config))

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

    monkeypatch.setenv("MYQUANT_DATA_DIR", "/tmp/myquant-data")
    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    create_runtime_context(BacktestConfig())

    assert resolve_data_dir() == "/tmp/myquant-data"
    assert created["store_path"] == "/tmp/myquant-data"


def test_create_app_accepts_config_overrides():
    from server.app import create_app

    app = create_app({"live_auto_start": False})

    assert app.state.config_overrides == {"live_auto_start": False}


def test_create_app_serves_spa_index_for_client_routes(monkeypatch, tmp_path):
    from server import app as app_module

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>myquant-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    response = __import__("asyncio").run(
        static.get_response(
            "activity",
            {"type": "http", "method": "GET", "path": "/activity", "headers": []},
        )
    )

    assert response.status_code == 200
    assert response.path.endswith("index.html")


def test_create_app_keeps_missing_static_assets_as_404(monkeypatch, tmp_path):
    from server import app as app_module

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>myquant-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    response = __import__("asyncio").run(
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

    assert response.status_code == 404
