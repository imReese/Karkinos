# Contributing

## Local Checks

Install the locked dependencies and run the same checks used by CI:

```bash
uv sync --extra server --extra dev --frozen
uv run python scripts/ci/check_python_quality.py --base origin/main
uv run python scripts/ci/check_docs_health.py
uv run python -m pytest tests/scripts/test_docs_health.py tests/strategy/test_strategy_docs.py tests/scripts/test_ci_preflight.py tests/test_ci_workflow.py
uv run python -m pytest tests/test_server_routes.py
uv run python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

The quality command includes staged, unstaged, and untracked Python changes.
Use `--base HEAD~1 --head HEAD` to check a committed change exactly as CI does.
Omitting `--base` checks all tracked and untracked Python files; an unavailable
revision fails explicitly instead of silently skipping checks. Ruff, Black,
isort, mypy, and architecture checks report independently; any failure fails
the command. Checks do not rewrite files. Run formatters explicitly when needed
and inspect `git diff` before committing.

## CI Gates

```text
Python quality + repository contracts + hygiene + secret scan
  -> backend / frontend / trading safety / dependency audit / Docker / browser
  -> acceptance evidence
  -> Code CI gate
  -> existing candidate / release source verification
```

The first stage catches documentation consumers and workflow contracts before
expensive jobs start. It runs on every PR and main push, including docs-only
changes. Successful preflight still requires the full existing validation;
there are no path-based test exemptions or relaxed coverage thresholds.

`Code CI gate` lists every required job result and rejects failure, cancellation,
skips, and missing results. Its name and `Repository acceptance audit` remain
stable for release verification. PR updates cancel obsolete PR runs; main keeps
per-commit CI evidence. Candidate and stable publication still require successful
CI for the exact source SHA, not the latest unrelated green run.

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
