# Karkinos Repository Instructions

This is the authoritative repository entry point for AI-assisted work. Read
`AI_COLLABORATION.md` before implementation, review, diagnosis, documentation,
or operational changes.

## Required context

1. Start at `docs/README.md`.
2. Read `docs/GOAL.md`, `docs/ARCHITECTURE.md`, `docs/PLAN.md`, or
   `docs/CODEBASE.md` only as the task requires.
3. Treat persisted financial facts, explicit snapshots, and ledger cutoffs as
   authoritative; provider responses and runtime caches are ingestion inputs.
4. Preserve human confirmation as the default for live-like workflows.

## Working rules

- Preserve unrelated and uncommitted workspace changes.
- Diagnose from source evidence before changing behavior.
- Keep each financial concept in one canonical implementation.
- Fail closed on the affected action when evidence is missing, stale,
  conflicting, partial, or unreconciled; preserve verified last-good reads when
  a newer candidate write fails.
- Add deterministic validation for affected invariants and direct consumers.
- Use production-state replay fixtures for production-state incidents.
- Do not create parallel roadmaps, implementation logs, or master design docs.
- Do not commit private account data, credentials, exports, screenshots,
  runtime databases, or secrets.
- Commit, push, publish, or open a pull request only when the owner requests it.
