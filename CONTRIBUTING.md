# Contributing

## Local Checks

Run the relevant checks before opening a pull request:

```bash
uv run python -m pytest tests/test_server_routes.py
uv run python -m pytest
npm --prefix web run format
npm --prefix web run build
npm --prefix web run test
```

The frontend format command writes changes. Review `git status --short` after
running it and do not include unrelated formatting noise in a focused change.

## Sensitive Files

Do not commit local secrets, runtime data, or generated artifacts:

- `.env*`
- `*.db`
- `*.sqlite`
- `*.duckdb`
- `data/store/`
- `logs/`
- `exports/`
- `screenshots/`
- `.agents/`
- `skills-lock.json`

Use `.env.example` and `config.example.json` as templates. Keep real tokens,
brokerage credentials, account exports, and personal financial data out of the
repository. Provider tokens can be supplied through ignored local environment
variables such as `TUSHARE_TOKEN` or an ignored local `config.json`; never commit
those values.

## Test Expectations

Changes that touch portfolio valuation, market data, stale quote handling,
manual quote refresh, trading approvals, backtest contracts, or API response
models need focused tests for the changed behavior.

Frontend changes should cover loading, error, empty, and stale/cache states when
those states are part of the feature.

Backend route or contract changes should include route-level tests and preserve
existing response compatibility unless the breaking change is intentional and
documented.
