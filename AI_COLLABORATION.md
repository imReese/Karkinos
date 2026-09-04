# Karkinos AI Collaboration Policy

This is the repository-level source of truth for AI-assisted implementation,
review, diagnosis, and documentation work.

## Required context

Start with `docs/README.md`. Read only the canonical document needed for the
task:

- product intent and hard boundaries: `docs/GOAL.md`;
- data ownership, financial semantics, reliability, persistence, execution:
  `docs/ARCHITECTURE.md`;
- current priorities and sequencing: `docs/PLAN.md`;
- package ownership and refactoring: `docs/CODEBASE.md`;
- current user behavior and commands: `README.md` and `scripts/README.md`.

Historical roadmap/design files are not sources of current product intent.

## Current engineering priority

Until the Reliability Gate in `docs/PLAN.md` is complete, prioritize:

1. production reliability and replayable failure recovery;
2. point-in-time market data;
3. Alpha research and validation;
4. portfolio construction and realistic costs;
5. execution simulation / paper / shadow;
6. attribution and edge-degradation detection;
7. only then broader controlled-capital work.

Do not expand broker write authority, AI autonomy, or unrelated product surface
at the expense of this sequence.

## Financial data integrity

- Persisted, validated facts are authoritative; provider responses and runtime
  caches are inputs.
- GET/read paths do not contact providers or silently mutate facts.
- Derived results bind explicit dataset/snapshot identity and, when account
  bound, ledger cutoff/fingerprint.
- One financial concept has one canonical owner.
- Missing, stale, estimated, partial, conflicting, or unreconciled evidence is
  explicit.
- Fail closed on the affected action; do not turn an unrelated writer failure
  into an avoidable whole-product outage.
- A failed candidate publication must not destroy a verified last-good read
  pointer.

## Human authority and safety

- AI output, research results, reviews, and UI actions do not grant trading or
  capital authority.
- Strategy/research code must not call a broker directly.
- Real-money submission remains default-off and human-supervised.
- Broker credentials, account identifiers, private exports, screenshots,
  runtime databases, and secrets never enter source control.
- Destructive or authority-expanding actions require explicit owner direction.

## Engineering and validation

- Diagnose from source and persisted evidence before changing behavior.
- Preserve unrelated workspace changes.
- Add deterministic tests for affected invariants and direct consumers.
- For production-state bugs, prefer replay/characterization fixtures over only
  isolated unit tests.
- State what was actually validated; local CI is not evidence of a real broker
  or production provider.
- Inspect staged/unstaged changes before commit and confirm no private data is
  included.

## Documentation discipline

- Do not create a new top-level roadmap, implementation log, architecture,
  profit plan, or AI master design.
- Update `GOAL.md`, `ARCHITECTURE.md`, `PLAN.md`, or `CODEBASE.md` according to
  ownership.
- Put narrow, durable decisions in ADRs or code contracts/tests.
- Implementation history belongs in Git commits, PRs, and Releases.
- Compatibility stub documents must remain short and must not regain product
  content.

Commit, push, publish, or open a pull request only when the owner requests it.
