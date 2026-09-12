# Contributing

## Branches

`dev` is the normal development branch. `main` receives only the exact current
`dev` head after that SHA passes both the incremental `Dev CI gate` and the
exact-SHA `Full CI gate`. The trusted promotion controller then revalidates the
CI evidence, branch refs, and fast-forward ancestry before publishing
`Main promotion gate` and updating `main` with `force=false`.

Maintainers may work directly on `dev`. External contributions should use a
feature branch or fork and open a pull request targeting `dev`.

Never force-push, reset, or delete `dev` or `main`.

## Before changing code

Start with [docs/README.md](docs/README.md) and read only the documents relevant
to the change.

For substantial quantitative-domain or architecture work, consult
[docs/REFERENCES.md](docs/REFERENCES.md) before introducing a new project-specific
abstraction.

Keep changes focused. Do not combine unrelated cleanup, feature work, and
financial-semantic changes without a concrete reason.

## Development setup

```bash
git switch dev
git pull --ff-only origin dev
uv sync --locked --extra server --extra dev
npm ci --prefix web
```

For the normal development runtime:

```bash
./scripts/start_server.sh dev
```

See [scripts/README.md](scripts/README.md) for runtime commands.

## Validation

Run the narrowest relevant checks first.

Python quality:

```bash
uv run --locked python scripts/ci/check_python_quality.py --base origin/dev
```

Documentation integrity:

```bash
uv run --locked python scripts/ci/check_docs_integrity.py
```

Relevant Python tests:

```bash
uv run --locked python -m pytest <relevant-tests>
```

Web changes:

```bash
npm --prefix web run format:check
npm --prefix web run test
npm --prefix web run build
```

Use the broad Python product suite when the affected boundary or regression
risk justifies it:

```bash
uv run --locked python -m pytest
```

There is no separate pytest `acceptance` layer. Historical acceptance-named
tests run as normal product tests; delete or reclassify tests that only encode
project-management completion criteria rather than supported behavior.

`.github/workflows/ci.yml` is the single code-verification workflow. Pull
requests and pushes to `dev` run its conservative incremental mode and finish at
`Dev CI gate`. Promotion dispatches the exact current `dev` SHA through the same
workflow in full mode; that candidate's own CI definition must finish at
`Full CI gate` before `main` can move.

`.github/workflows/promote-dev.yml` is the privileged controller. It executes
trusted default-branch controller code only; it does not checkout or execute
candidate code with write credentials. It never falls back to an older green
ancestor and every branch/status write is preceded by exact evidence and ref
revalidation.

`candidate.yml` is currently retained only for the installed native-runtime
candidate/update path. It is not a code-CI or promotion authority. Stable
publication remains an explicit SemVer-tag operation in `release.yml`.

Do not weaken assertions, typing, financial invariants, or fail-closed behavior
merely to make a check pass.

## Tests

Tests should protect meaningful behavior and financial or research semantics.
Avoid tests that only enumerate private symbols, preserve obsolete repository
structure, or encode project-management acceptance criteria.

Use synthetic or sanitized fixtures. Tests must not require real brokerage
credentials, account exports, or personal financial data.

## Commits and pull requests

Use focused commits with messages that describe the actual change.

A pull request should explain:

- the problem being solved;
- the important design or behavior change;
- the validation that actually ran;
- any persisted-data, financial-semantic, or compatibility impact.

Do not claim tests or workflows that were not run.

## Sensitive data

Never commit credentials, real account exports, runtime databases, private logs,
or screenshots containing personal financial information.

If a secret is exposed, follow [SECURITY.md](SECURITY.md).
