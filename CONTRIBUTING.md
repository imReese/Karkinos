# Contributing

## Persistent dev and main

`main` remains the default, reviewed integration and release-source branch.
Use the long-lived `dev` branch for everyday work; do not recreate or delete it
per task. Normal integration is `dev` -> pull request -> green current
`Code CI gate` -> merge commit -> `main`. CI on the PR tests the integration
checkout; a green dev push alone is not merge approval. Main runs CI again for
its exact merged SHA before the existing candidate/release checks can pass.

Start with a clean working tree; commit or stash local work before switching:

```bash
git fetch origin
git switch dev  # first use: git switch --track origin/dev
git pull --ff-only origin dev
git merge --no-edit origin/main
# Make a focused change, run Local Checks, then commit selected files.
git push origin dev
gh pr create --base main --head dev --fill
```

Reuse an already-open dev-to-main PR instead of opening a second one. Inspect
its diff and latest checks, then use **Create a merge commit**. Do not squash
or rebase this long-lived branch: preserving ancestry avoids replaying already
merged commits in subsequent PRs. Do not select the delete-branch option.

After each merge, with local work committed or stashed:

```bash
git fetch origin
git switch dev
git pull --ff-only origin dev
git merge --no-edit origin/main
git push origin dev
```

Normally this fast-forwards dev to main. If development advanced meanwhile,
merge main without rewriting history; resolve conflicts explicitly and rerun
checks. Never use reset/force-push to synchronize either branch.

Dependabot version-update PRs target dev. Security-update PRs still target the
default main branch; review them through the same main CI gate and merge the
result back into dev. Existing PRs are not automatically retargeted by this
document. No dev push publishes a candidate or grants production authority.

### One-time GitHub settings (repository administrator)

The versioned `.github/rulesets/main.json` and `dev.json` are importable policy
templates. Committing them does **not** activate GitHub protection. Import each
under Settings -> Rules -> Rulesets -> New ruleset -> Import a ruleset, or use
the REST commands below once. Inspect existing rulesets first; update a matching
rule by its id rather than creating duplicates on subsequent changes.

```bash
gh api repos/imReese/Karkinos/rulesets --jq '.[] | {id, name, enforcement}'
gh api --method POST repos/imReese/Karkinos/rulesets --input .github/rulesets/dev.json
gh api --method POST repos/imReese/Karkinos/rulesets --input .github/rulesets/main.json
```

The main policy requires PRs, resolved conversations, an up-to-date branch, and
`Code CI gate` from the GitHub Actions app. It allows merge commits only and has
no bypass actors. Required external approval count is zero for the single-owner
project; the owner must still inspect the PR before merging. Both policies block
deletion and force-push. Dev deliberately permits normal pushes without requiring
a previous successful check: those pushes are what start its CI.

In Settings -> General -> Pull Requests, keep merge commits enabled, disable
automatic head-branch deletion, and enable the update-branch suggestion. Do not
enable required linear history for main, since it would forbid merge commits.
Other short-lived contributor/Dependabot branches may still use squash into dev.
These are administrative settings, not claims made by the source checkout.

Verify active settings after applying them:

```bash
gh api repos/imReese/Karkinos/rules/branches/main
gh api repos/imReese/Karkinos/rules/branches/dev
```

Until those endpoints return the required active rules, treat main as unprotected
and do not describe CI as an enforced merge barrier.

## Local Checks

Install the locked dependencies and run the same checks used by CI:

```bash
uv sync --extra server --extra dev --frozen
uv run python scripts/ci/check_python_quality.py --base origin/main
uv run python scripts/ci/check_docs_health.py
uv run python -m pytest tests/scripts/test_docs_health.py tests/strategy/test_strategy_docs.py tests/scripts/test_ci_preflight.py tests/test_ci_workflow.py tests/test_ci_safety_workflow.py tests/scripts/test_scripts_inventory.py
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
expensive jobs start. It runs on every PR and main/dev push, including docs-only
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
