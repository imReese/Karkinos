# Contributing

## Persistent branches

Use `dev` for normal development. `main` follows exact verified dev commits;
there is no routine PR, squash, merge commit, branch deletion, or merge-back.
Do not edit the running source checkout. Stop the service before updating it,
or use a separate main worktree for running and dev worktree for development.

```bash
git switch dev
git pull --ff-only origin dev
# edit, check, commit
git push origin dev
```

## Daily promotion

`Promote verified dev` runs daily at 03:17 Asia/Tokyo (18:17 UTC), and can be
started manually from Actions on main. GitHub schedules can be delayed.
The trusted main script walks at most 100 first-parent dev commits, newest
first. It chooses the newest descendant of main whose latest official dev
push CI run/attempt succeeded and whose Code CI gate and acceptance job passed.
A failed or pending tip can remain on dev while an earlier verified ancestor
is promoted. API errors, incomplete listings, changed identities, divergence,
and an exhausted search bound stop the run instead of guessing.

Promotion uses the exact SHA and a server-side non-force ref update. It never
executes the dev checkout with write credentials, creates a PR, opens trading
authority, creates a tag, or changes a local service. A concurrent dev/main
change or newer CI attempt invalidates the selection. Server protection is
never bypassed.

The built-in GITHUB_TOKEN cannot trigger another push workflow, so the job
explicitly dispatches the existing CI and Candidate workflows on main with
the selected SHA. CI rejects a dispatch that does not match its main checkout.
Release source verification accepts the latest exact main push or explicit
CI dispatch, not a green run on dev or a previous successful attempt. A failed
dispatch after the ref update is repairable on the next run. Existing failed
runs are not silently retried into green; use Actions rerun after diagnosis.
No personal access token is needed for ordinary source promotion. A server
permission/rules rejection remains an error; workflow-file changes can require
an owner-authorized token with the appropriate workflow permission.

## GitHub protection (one-time administrator setting)

Import `.github/rulesets/main.json` and `.github/rulesets/dev.json` in Settings
-> Rules -> Rulesets, replacing any previous PR-required main policy. The main
policy requires Code CI gate from GitHub Actions, prohibits force-push and
deletion, and has no bypass actors. Dev permits normal pushes to start CI but
also prohibits history loss. Do not enable a PR requirement for this workflow.
Templates in Git are not active GitHub settings. Inspect the actual rulesets:

```bash
gh api repos/imReese/Karkinos/rulesets
# Only when these rules do not exist, create them with administrator access:
gh api --method POST repos/imReese/Karkinos/rulesets --input .github/rulesets/main.json
gh api --method POST repos/imReese/Karkinos/rulesets --input .github/rulesets/dev.json
```

Keep automatic head-branch deletion disabled. Dependabot version updates target
dev; security updates can target default main and require synchronization into
dev before further fast-forward promotion. Never reset a divergent branch.

## Local checks

```bash
uv sync --locked --extra server --extra dev
uv run --locked python scripts/ci/check_python_quality.py --base origin/main
uv run --locked python scripts/ci/check_docs_health.py
uv run --locked python -m pytest tests/scripts/test_ci_preflight.py tests/test_ci_workflow.py tests/test_ci_safety_workflow.py tests/scripts/test_scripts_inventory.py tests/tools/test_main_promotion.py tests/scripts/test_main_source_runtime.py tests/test_verify_release_source_ci.py
uv run --locked python -m pytest
npm --prefix web run format:check
npm --prefix web run build
npm --prefix web run test
```

The quality entrypoint includes local staged, unstaged and untracked Python
changes. An unavailable revision fails rather than silently skipping checks.
In dev CI, Python quality is checked against main, not only the previous dev
push, so a later small commit cannot hide an earlier unpromoted formatting
failure. Ruff, Black, isort, mypy and architecture results are independent;
any failure fails the command. Checks do not rewrite files.

Preflight precedes full backend/frontend, safety, dependency, Docker and browser
checks. Acceptance binds test evidence. The final Code CI gate rejects failed,
cancelled, skipped and missing results. Main retains per-commit CI evidence.

## Sensitive files and test expectations

Never commit `.env*`, credentials, private account exports, runtime databases,
`data/store/`, `.run/`, logs, screenshots or generated reports. Use templates
without overwriting existing private configuration. Keep tokens out of arguments.

Financial data, risk, trading authority, valuation and API changes need focused
deterministic tests and must preserve human confirmation and fail-closed gates.
Frontend changes should cover loading, error, empty and stale/cache states.
Do not mistake passing local CI for validation against a real broker/provider.
