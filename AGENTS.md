# Karkinos Repository Instructions

This is the authoritative repository entry point for AI-assisted work in
Karkinos. Read and follow `AI_COLLABORATION.md` before implementation, review,
diagnosis, documentation, or operational changes.

## Required context

1. Read `docs/KARKINOS_GOAL.md` and the relevant README sections.
2. Follow the task-specific source routing in `AI_COLLABORATION.md`.
3. Treat persisted financial facts, explicit snapshots, and ledger cutoffs as
   authoritative; provider responses and runtime caches are ingestion inputs.
4. Preserve human confirmation as the default for live-like workflows.

## Working rules

- Preserve unrelated and uncommitted workspace changes.
- Diagnose from source evidence before changing behavior.
- Keep each financial concept in one canonical implementation.
- Fail closed when evidence is missing, stale, estimated, conflicting, partial,
  or unreconciled.
- Add deterministic validation for affected invariants and direct consumers.
- State validation boundaries and trading-risk impact explicitly.
- Do not commit private account data, credentials, exports, screenshots,
  runtime databases, or secrets.
- Commit, push, publish, or open a pull request only when the owner requests it.

Local tool integrations may add stricter checks, but they must not weaken or
replace this file or `AI_COLLABORATION.md`.
