# Karkinos AI Collaboration Policy

This is the repository-level source of truth for AI-assisted implementation, review, diagnosis, and documentation work.

## Required context

Start with `docs/README.md`. Read only the canonical document needed for the task:

- product intent and hard boundaries: `docs/GOAL.md`;
- target architecture, data ownership, reliability, persistence, execution: `docs/ARCHITECTURE.md`;
- current priorities and sequencing: `docs/PLAN.md`;
- package ownership and refactoring: `docs/CODEBASE.md`;
- UI information architecture and authority presentation: `design.md`;
- current user behavior and commands: `README.md` and `scripts/README.md`.

Historical roadmap/design files and frozen broker references are not sources of current product intent.

## Current engineering priority

Until the relevant gates in `docs/PLAN.md` are complete, prioritize:

1. production reliability and replayable failure recovery;
2. architecture seams: durable jobs, worker isolation, narrow ports, dataset catalog;
3. point-in-time market data;
4. research/Alpha experiments and validation;
5. portfolio construction and unified simulation;
6. shadow operation, attribution, and edge-degradation detection;
7. only then broader controlled-capital work.

Do not expand broker write authority, bespoke AI automation, or unrelated product surface at the expense of this sequence.

## Financial data integrity

- Persisted, validated facts are authoritative; provider responses and runtime caches are inputs.
- GET/read paths do not contact providers or silently mutate facts.
- Research outputs bind immutable Dataset/Artifact identities; account-bound outputs additionally bind financial snapshot/ledger identity.
- One financial concept has one canonical owner.
- Market/event time, information availability time, and Karkinos capture time are not interchangeable.
- Missing, stale, estimated, partial, conflicting, or unreconciled evidence is explicit.
- Fail closed on the affected action; do not turn an unrelated writer failure into an avoidable whole-product outage.
- A failed candidate publication must not destroy a verified last-good read pointer.

## Human authority and safety

- AI output, research results, reviews, and UI actions do not grant trading or capital authority.
- Strategy/research code must not call a broker directly.
- Real-money submission remains default-off and human-supervised.
- Broker credentials, account identifiers, private exports, screenshots, runtime databases, and secrets never enter source control.
- Destructive or authority-expanding actions require explicit owner direction.

## Engineering and validation

- Diagnose from source and persisted evidence before changing behavior.
- Preserve unrelated workspace changes.
- Add deterministic tests for affected invariants and direct consumers.
- For production-state bugs, prefer replay/characterization fixtures over only isolated unit tests.
- Structural refactors and financial-semantic changes should be separate slices.
- New code should depend on narrow ports and the target ownership in `CODEBASE.md`, not expand compatibility facades.
- State what was actually validated; local CI is not evidence of a real broker or production provider.
- Inspect staged/unstaged changes before commit and confirm no private data is included.

## Documentation discipline

- Do not create a new top-level roadmap, implementation log, architecture, profit plan, or AI master design.
- Update `GOAL.md`, `ARCHITECTURE.md`, `PLAN.md`, `CODEBASE.md`, or `design.md` according to ownership.
- Put narrow, durable decisions in ADRs or code contracts/tests.
- Topic docs explain stable interfaces/operations; they do not define roadmap.
- Implementation history belongs in Git commits, PRs, and Releases.
- Compatibility stub documents must remain short and must not regain product content.

Commit, push, publish, or open a pull request only when the owner requests it.
