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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Karkinos** (25023 symbols, 56475 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Karkinos/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Karkinos/clusters` | All functional areas |
| `gitnexus://repo/Karkinos/processes` | All execution flows |
| `gitnexus://repo/Karkinos/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
