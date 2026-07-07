# Karkinos Strategy Extensions

This directory is for local, private research strategies. Karkinos discovers
extension metadata from files named `*.strategy.json` in this directory, or from
the directory pointed to by `KARKINOS_STRATEGY_EXTENSION_DIR`.

Keep private strategy code, account details, exports, logs, screenshots, and
broker credentials out of git. The default `.gitignore` ignores local extension
files; commit only sanitized templates.

An extension manifest must use `schema_version: "karkinos.strategy.v1"` and
declare a stable `strategy_id`, display metadata, a `class_path` in
`module:ClassName` format, and typed parameters. Extension manifests cannot
declare live trading, broker submission, auto-trading, or real-money execution
capabilities. Strategy Lab output remains research evidence until existing
risk gates, paper/shadow review, signal journaling, and manual confirmation
boundaries are satisfied.

Private strategy scripts must not import broker gateway or broker connector
modules, and must not call broker-style submission or cancellation methods
directly. Bridge actions belong behind policy, risk, OMS, gateway, and
reconciliation services. Run `uv run pytest tests/test_strategy_broker_boundary.py`
after adding or reviewing strategy code to check the local strategy tree and
sanitized templates. Pass explicit paths to the scanner for private strategies
stored outside this repo.

When a private strategy script is stored directly in this extension directory,
the manifest can use the local module name in `class_path`, for example
`my_strategy:MyStrategy`. Karkinos validates the manifest during
discovery and loads the class lazily only when a research backtest instantiates
that registered extension strategy.

To start from the committed template:

```bash
cp strategy/extensions/template.py.example strategy/extensions/my_strategy.py
cp strategy/extensions/template.strategy.json.example \
  strategy/extensions/my_strategy.strategy.json
```

Then edit the copied files locally. The copied files stay ignored by git.
