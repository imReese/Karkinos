# Contributing

## Branches

`dev` is the integration/development branch. `main` is the last-known-green
source state. A trusted controller promotes only the exact current dev HEAD with
a successful `Promotion Gate`, and only when main is its ancestor. It re-reads
both refs before updating main with `force=false` and confirms the result.

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
./scripts/dev
```

Development uses its own config, data, and logs under
`~/.karkinos/development`. Set `KARKINOS_DEV_HOME` to use another isolated
development workspace. Use a Git worktree or separate clone to run another
source revision. See [scripts/README.md](scripts/README.md) for runtime commands.

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

Repository/workflow/ruleset contracts belong under `tests/engineering/`. They
protect the engineering system, not financial product behavior, and should not
be used to inflate or describe product-test coverage.

## CI and promotion

`.github/workflows/ci.yml` verifies every dev push and pull request. All mandatory
checks must succeed for `Promotion Gate`, including trading safety, normal
product tests, quality and secret scanning. A path classifier cannot skip major
correctness suites.

Manual dispatch on `dev` reruns its current commit's ordinary CI for debugging.
The complete browser suite, Docker smoke, and deep audits run separately in
`.github/workflows/nightly.yml`.

`.github/workflows/promote-dev.yml` executes trusted default-branch code only.
It reads the exact current dev commit's gate through the GitHub API and never
executes candidate code with branch-write credentials. It never falls back to
an older green ancestor or dispatches another verification protocol.

`candidate.yml` builds an exact promoted main commit and signs a manifest binding
its native archive checksums and container digest. `release.yml` verifies the
immutable SemVer tag, exact commit, manifest, artifact digests, and attestations,
then publishes the already-built bytes. New candidates use manifest v3; installed
readers preserve read-only compatibility with already-published v2 manifests and
v1 selection sidecars.

Do not weaken assertions, typing, financial invariants, or fail-closed behavior
merely to make a check pass.

## Repository governance

Tracked files under `.github/rulesets/` are desired state, not an implicit
GitHub administration mechanism. Editing them does not change server-side
branch or tag protection.

`.github/workflows/governance.yml` is intentionally read-only. It compares the
tracked desired rulesets with the GitHub server and reports drift. Normal CI and
scheduled automation must never silently repair repository security settings.
Applying or changing rulesets is an explicit repository-owner operation; after
such a change, read the server state back and require the governance verifier to
pass before claiming the protection is live.

Local/manual drift check:

```bash
GITHUB_TOKEN=... python tools/verify_repository_rulesets.py \
  --repository imReese/Karkinos
```

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
