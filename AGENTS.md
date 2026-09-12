# Karkinos Agent Guide

Karkinos is a local-first quantitative research and investing platform for the China market. Its core research, portfolio, simulation, and financial workflows do not depend on a hosted account or cloud control plane; external services may provide data or optional capabilities.

Its primary value is helping the user discover, validate, combine, deploy, monitor, and retire investment edge. Lines of code, abstraction count, test count, acceptance machinery, and infrastructure complexity are not project goals.

## 1. Find the right context

Start at `docs/README.md` and read only what the task requires.

* Product intent and hard boundaries: `docs/GOAL.md`
* Durable architecture and domain ownership: `docs/ARCHITECTURE.md`
* Current priorities, scope, and frozen areas: `docs/PLAN.md`
* Codebase ownership, technical debt, and engineering quality: `docs/ENGINEERING.md`
* Mature-project design references: `docs/REFERENCES.md`

For UI work, consult `design.md` when relevant.

For user-facing behavior or runtime operations, consult `README.md` and `scripts/README.md`.

`AGENTS.md` is a map, not the complete design manual. Use progressive disclosure: do not load every document by default, and do not create duplicate sources of truth.

If documents conflict, follow the canonical document that owns the subject. Surface conflicts that would materially affect product behavior, financial semantics, persisted compatibility, or current scope.

## 2. Durable invariants

* Research value takes priority over architectural sophistication.
* Research data must preserve point-in-time semantics, including distinct market/event time, information-availability time, and capture time.
* Reproducible research must bind enough data, code, parameters, and time boundaries to replay the result.
* One financial concept has one canonical owner, but it may have multiple derived representations. Projections, DTOs, caches, reports, materialized views, and UI models must not become competing calculation or write owners.
* Provider responses, caches, model outputs, UI state, and AI output do not become authoritative financial facts or grant capital authority by themselves.
* Alpha and Model outputs begin as forecasts, scores, expected returns, probabilities, or equivalent research outputs; do not collapse the research layer into direct `Signal -> Order`.
* Real-money authority remains default-off, bounded, observable, pausable, revocable, and human-supervised. Strategy and research code never call a broker directly.
* Live-trading safety constraints are durable boundaries, not current implementation scope. Do not build broker, live-execution, or capital-authority infrastructure unless `docs/PLAN.md` explicitly places it in scope.
* Missing, stale, conflicting, or unverified state blocks the affected action without unnecessarily disabling unrelated functionality.

## 3. Engineering discipline

Understand before editing. Identify the canonical owner, direct consumers, derived representations, persisted or replay-sensitive contracts, and the real user or research workflow affected.

Prefer solutions in this order:

1. delete code that is no longer needed;
2. reuse an existing implementation;
3. simplify an existing implementation;
4. use a plain function or explicit typed value;
5. add a new abstraction only when the previous options are insufficient.

New classes, services, repositories, protocols, schemas, tables, workers, or frameworks require a stable domain reason or concrete current consumers. Future flexibility alone is not sufficient.

Do not translate requirements, acceptance criteria, milestones, review checklists, or internal process vocabulary one-for-one into production abstractions.

Do not build production evidence, manifest, acceptance, conformance, or compatibility frameworks merely to prove project completion. Runtime evidence is appropriate only when the product genuinely requires financial, research, or data provenance.

Internal abstractions do not receive compatibility by default. Preserve compatibility where real persisted data, public contracts, external integrations, user workflows, or financial semantics require it.

Business semantics belong to their owning domain. FastAPI, React, SQLite, providers, and other implementation technologies are outer delivery or adapter concerns unless the canonical architecture explicitly says otherwise.

Do not pre-create future workers, services, tables, ports, or extension points merely to make an architecture look complete.

Keep changes focused. Prefer the smallest correct change, avoid opportunistic expansion of adjacent subsystems, and keep structural refactors separate from financial-semantic changes when practical.

Do not preserve accidental complexity merely because obsolete tests depend on it. Simplify the design and migrate or delete tests that encode obsolete implementation structure.

Current scope and frozen areas belong only to `docs/PLAN.md`.

When a repository-wide rule can be checked reliably, prefer enforcing it through linting, type checking, architecture checks, or CI rather than adding more prose rules.

## 4. Prefer established designs

For substantial quantitative-domain or architecture work, consult `docs/REFERENCES.md` before inventing a Karkinos-specific concept.

Use mature projects to understand established concepts, boundaries, and trade-offs rather than copying another project's architecture mechanically.

External reference research is advisory and non-blocking. If external repositories are unavailable, search is incomplete, or no exact analogue exists, continue from repository facts and canonical docs with the smallest reversible correct design. Do not compensate for missing references by inventing broader abstractions.

Routine bug fixes, local UI changes, straightforward refactors, and ordinary maintenance do not require external architecture research.

Broad audits and reference research may use parallel read-only investigation when useful. Do not have multiple agents independently create competing abstractions for the same domain.

## 5. Validate according to risk

Tests should verify meaningful behavior, financial semantics, persistence compatibility, simulation correctness, and real product workflows rather than mirror implementation structure.

Test count is not a project goal. Do not mechanically add tests for reversible, low-impact changes that merely restate the implementation.

Run the narrowest relevant checks first and broaden verification only when the affected boundary, a failure, or unresolved risk requires it.

Use `docs/ENGINEERING.md` for the current test strategy and local validation commands. `.github/workflows/ci.yml` is authoritative for full `main` CI behavior.

Changes to runtime or UI behavior should validate the corresponding real product journey when practical rather than relying only on mocked contracts.

Never weaken assertions, type checking, financial invariants, or fail-closed behavior merely to make checks pass.

Report only checks that actually ran.

## 6. Git and safety

`dev` is the normal development branch for Karkinos.

Development changes should normally be based on the latest `dev` and integrate into `dev`. Isolated Git worktrees or temporary agent workspaces are workspace-isolation mechanisms only; they do not define a separate development workflow.

The trusted promotion workflow may fast-forward only the **current** `dev` head after that exact SHA's official `Dev CI gate` succeeds. A red or pending tip waits; never promote an older green ancestor and never run stale `main` CI definitions against newer `dev` source as authorization.

Never force-push, reset, or delete `dev` or `main`.

Preserve unrelated workspace changes. Do not clean, reset, or overwrite another worktree to complete the current task.

Perform commits, pushes, merges, releases, tags, publishing, or PR creation only when the task explicitly requests the corresponding Git write.

Never commit secrets, credentials, private account exports, real personal financial data, production or runtime databases, private logs, or screenshots.

Use sanitized deterministic fixtures for tests and replay.

## 7. Definition of done

A task is complete when the actual user, research, or reliability problem is solved with the simplest correct design, required financial and persistence semantics are preserved, and verification appropriate to the risk has passed.

The relevant real product workflow should work when applicable.

More code, tests, gates, abstractions, infrastructure, or documentation do not by themselves demonstrate higher quality.
