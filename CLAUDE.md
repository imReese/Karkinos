# Karkinos Claude Guide

`AGENTS.md` is the primary repository instruction file. Read it first and follow
it for task routing, engineering invariants, validation, Git workflow, security,
and documentation ownership.

Then read `AI_COLLABORATION.md` for the deeper repository-wide AI policy. Do not
copy those rules into this file; they remain authoritative at their owning
sources.

For each task:

1. Route the task through the canonical docs listed in `AGENTS.md` instead of
   loading the whole documentation tree.
2. Inspect the owning implementation, direct callers, and relevant tests before
   proposing changes.
3. Prefer small evidence-backed slices over broad rewrites or speculative
   abstractions.
4. For persisted financial state, authority, risk, execution, release, or worker
   behavior, preserve fail-closed semantics and add deterministic replay/safety
   coverage where applicable.
5. Use `.github/workflows/ci.yml` as the source of truth for CI and report only
   checks that actually ran.
6. Preserve unrelated workspace changes and private data boundaries.
7. Commit, push, merge, publish, tag, release, or open PRs only when the owner
   explicitly requests that action.

If this file conflicts with `AGENTS.md`, follow `AGENTS.md`. If an engineering
rule needs more detail, follow the canonical document or code/test owner linked
from `AGENTS.md` rather than expanding this adapter.