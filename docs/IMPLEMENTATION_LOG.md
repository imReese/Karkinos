# Karkinos Implementation Log

This file keeps historical implementation progress out of the strategic goal
page and roadmap. Entries are factual implementation notes, not user-facing
roadmap promises.

## Cross-Cutting Reliability

- 2026-07-14: AI-native Phase 1.16 adds the separate, explicit, revocable
  historical-memory promotion required after Phase 1.15. Assumptions: human
  acceptance is not memory permission; historical conclusions are not current
  facts; and recall eligibility is not automatic retrieval or prompt injection.
  Only a currently replay-valid Phase 1.15 accepted review can be promoted. The
  new target binds the exact review/analysis/report, Phase 1.13 retrieval and
  source-promotion selections, current context and evidence references,
  provider/model/prompt, quality/cost fingerprints, and audit hashes. The
  normalized report is copied into isolated Phase 1.16 storage and explicitly
  requires current-evidence rebinding. Exact restart/concurrent duplicates
  reuse one promotion; a second final promotion fails closed. Revocation adds
  one terminal event and deletes nothing. Source, report, review, evidence, or
  audit drift hides content and removes recall eligibility. Phase 1.12 schema
  and rows remain unchanged, and no source workflow artifact is inserted.
  Deterministic validation covers promotion, restart/concurrency, rejected
  review, source revocation, explicit revocation, artifact/audit drift, lazy
  reads, protected financial tables, exact confirmations, route error mapping,
  and main-app registration: 69 Phase 1.11–1.16 chain tests, all 238 AI runtime/
  route tests, all 1,582 backend tests at 86.48% coverage, and 98 trading-safety
  tests pass. Under Node 24.14.0, all 420 Web tests, Prettier format check, and
  production build pass; changed Python files pass Black and isort.
  Promotion/revocation invoke no model and cannot affect current facts,
  automatic recall, Decision, trade plans, OMS, ledger, risk, broker actions,
  permissions, capital, or execution authority.

- 2026-07-14: AI-native Phase 1.15 separates human acceptance of a Phase 1.14
  promoted-memory external report from both schema success and memory
  promotion. Assumptions: the Phase 1.13 retrieval remains historical research
  input rather than a current fact or export grant; a structurally valid model
  report is not reviewed research; and accepting reviewed research is not
  permission to create or recall memory. The new explicit POST records one
  final accept/revision/reject disposition with a four-part human quality
  rubric, factual/unsupported-claim counts, and reviewer-supplied pricing or an
  explicit unpriced reason. It reuses the Phase 1.11 canonical report,
  citation, token, latency, reasoning-presence, and deterministic cost evidence
  while composing a new target over the Phase 1.13 retrieval/promotion/
  selection fingerprints and Phase 1.14 report/provider/model/prompt/tool/audit
  bindings. Exact restart and concurrent duplicates reuse one review and one
  hash-chained event; a second final decision fails closed. Revocation,
  evidence, artifact, usage, source, or audit drift preserves history but
  removes eligibility. Isolated Phase 1.15 tables reference the Phase 1.14
  analysis without modifying Phase 1.11, 1.13, or 1.14 schemas. Deterministic
  validation: 58 Phase 1.11–1.15 chain tests, the complete 1,571-test backend
  suite at 86.44% coverage, and 97 trading-safety tests passed. Under Node
  24.14.0, all 420 Web tests, Prettier format check, and the production build
  passed; changed Python files pass Black and isort. GitNexus's name-only CLI
  could not disambiguate `create_router`; the exact file-scoped graph query
  found two direct callers, no execution process, and MEDIUM route-registration
  risk. No HIGH/CRITICAL symbol was edited. Review performs no model call,
  creates no memory or automatic recall, and cannot affect Decision, trade
  plans, financial state, provider promotion, broker actions, capital, submit/
  cancel capability, or execution authority.

- 2026-07-14: AI-native Phase 1.14 adds the first explicit external consumer
  of the versioned Phase 1.13 promoted-memory retrieval. Assumptions: retrieval
  is neither automatic recall nor data-export permission; historical memory is
  a hypothesis source rather than a current fact; and a model report remains
  non-authoritative until a separate human review. The new POST requires the
  exact reviewed-memory/current-evidence export confirmation. Every
  claim/debate/report stage rereads every bound current canonical evidence row
  through local deny-by-default tools before a provider-neutral edge receives
  sanitized evidence, selected memory, and prior normalized artifacts. It
  reuses prompt v2, closed-world citation validation, the deterministic
  orchestrator, and provider/model/role separation. DeepSeek-compatible
  requests keep thinking/high effort; provider-side tools, raw reasoning/body
  persistence, automatic recall, and automatic retry remain disabled. New
  analysis/model-call tables reference the Phase 1.13 retrieval directly;
  Phase 1.8 retrieval-v1 and Phase 1.10 analysis tables are unchanged.
  Deterministic validation: 215 AI-runtime/route tests, 96 trading-safety
  tests, and the complete 1,559-test backend suite passed at 86.43% coverage.
  Under Node 24.14.0, all 420 Web tests, Prettier format check, and the
  production build passed; Black and isort checks passed. A real three-stage
  DeepSeek smoke used only a sanitized synthetic portfolio and completed all
  calls with reasoning present but not persisted. Its normalized report
  reconciled holding contributions to account P&L, verified zero account-truth
  residuals, and explicitly flagged ambiguous weight semantics plus weak
  historical-memory specificity instead of inventing certainty. GitNexus's
  name-only CLI could not disambiguate the modified `create_router`; an exact
  graph query found two direct callers and no execution process, giving medium
  route-registration risk. No HIGH/CRITICAL symbol was edited. The boundary
  cannot create memory, Decision input, trade plan, financial mutation, broker
  action, capital change, submit/cancel ability, or execution authority.

- 2026-07-14: AI-native Phase 1.13 adds an isolated, versioned retrieval for
  exact Phase 1.12 promoted external-research memory ids plus one existing
  persisted current context. Assumptions: promotion is not automatic-recall or
  data-export permission; historical conclusions remain non-current; and every
  source canonical tool must map to exactly one current `complete` evidence
  record under a replay-valid valuation/ledger identity. The boundary reuses
  the established current-context validator without changing Phase 1.8 request
  fields, fingerprints, tables, or replay. It stores only a new immutable
  retrieval row and one hash-chained event. Revocation or source/current/audit
  drift preserves history but hides selected memory content. Validation: 205
  AI-runtime/route tests, 95 trading-safety tests, and the complete 1,549-test
  backend suite passed with 86.46% coverage. Under Node 24.14.0, all 420 Web
  tests, Prettier format check, and the production build passed; Black and
  isort checks passed. Deterministic cases cover explicit confirmation,
  current evidence rebinding, partial evidence, restart,
  concurrent duplicate commands, request/source/current/audit drift, terminal
  revocation, v1 fingerprint compatibility, and unchanged protected OMS/
  ledger/risk/kill-switch/capital/Decision tables. Risk impact: the existing
  Phase 1.8 service was rated HIGH and `create_app` CRITICAL by GitNexus, so
  neither was edited. One medium-risk route aggregator with two direct callers
  and no execution process includes the new sub-router. Phase 1.13 performs no
  provider/model call, semantic search, automatic prompt injection, Decision
  handoff, financial mutation, broker action, capital change, or authority
  grant.

- 2026-07-14: AI-native Phase 1.12 adds an explicit, revocable promotion from
  one currently eligible Phase 1.11 external-analysis review into a new
  historical-research memory artifact. Assumptions: research acceptance is not
  memory permission; a promotion needs its own human identity, rationale, exact
  no-current-fact/no-Decision/no-trade confirmation, and idempotency key. The
  artifact copies only the normalized report and safe provenance metadata and
  binds source review/report/context/retrieval/evidence plus provider/model/
  prompt fingerprints. Raw reasoning and provider responses remain absent.
  Source or audit drift hides content and removes recall eligibility; a
  terminal human revocation appends a second hash-chained event without
  deleting history. Reviewed-memory retrieval v1 is unchanged, and Phase 1.12
  adds no automatic recall or external-model consumption. Validation: 52
  focused Phase 1.8–1.12 regression tests, 94 trading-safety tests, and the
  complete 1,537-test backend suite passed with 86.48% coverage. Under Node
  24.14.0, all 420 Web tests, Prettier format check, and the production build
  passed; Black and isort checks passed. Deterministic cases cover restart,
  concurrent duplicate commands, source/report/audit/artifact/revocation drift,
  terminal revocation, content hiding, unchanged source workflow artifacts,
  and unchanged protected OMS/ledger/risk/kill-switch/capital/Decision tables.
  Risk impact: extending retrieval v1 was rejected after GitNexus rated its
  request contract HIGH (eight direct callers, 105 upstream symbols). The
  isolated route aggregator has two direct callers and no execution process;
  the delivered boundary calls no model or provider and cannot create current
  facts, provider promotion, financial mutation, broker action, capital change,
  or execution authority.

- 2026-07-14: AI-native Phase 1.7 hardens the external saved-backtest report
  contract after the first bounded provider trial exposed timeout, JSON-wrapper,
  and `claims` shape failures. Assumptions: the configured model's reasoning
  mode remains enabled according to its edge configuration; OpenAI-compatible
  JSON mode guarantees syntax more reliably than the application-specific
  report schema; and provider-side tools are unnecessary because the local
  orchestrator already performs the single permission-checked
  `research_evidence.read`. Prompt v3 adds an exact structural example,
  quantitative evidence-review rubric, prompt-injection boundary, required
  input-path/value citations, an 8,192-token bounded output budget, and a
  60-second human-started call timeout. Local parsing now accepts a reviewed,
  bounded set of wrapper, nested, common, and Chinese field variants while
  marking missing item evidence as `reference_only` instead of inventing a
  summary. Truncation and missing final content after reasoning have distinct
  fail-closed codes. Raw `reasoning_content` is never stored; only presence,
  character count, and finish metadata may enter provenance. Validation: 20
  focused external-report tests, 108 AI/route tests, 89 trading-safety tests,
  and the complete 1,473-test backend suite passed; Black and isort checks
  passed. Deterministic coverage verifies the prompt/output contract, unchanged
  no-tools boundary, reasoning-body exclusion, nested Chinese/common alias
  normalization, evidence warnings, unchanged protected financial tables, and
  idempotent restart/concurrency behavior. No real provider call or financial
  evidence export was made during this hardening run. Risk impact: GitNexus
  rated the request method and decoder LOW; the service class was MEDIUM due to
  route/application imports, with only its route builder and test helper as
  direct callers. No HIGH/CRITICAL impact or execution process was reported.

- 2026-07-15: AI-native Phase 1.7 upgrades the real-model edge to prompt v4
  after a current prompt-v3 trial over saved backtest #5 reached the old
  60-second limit and two pre-hard-deadline v4 trials eventually timed out
  without a report, showing that urllib's socket timeout was not an end-to-end
  wall-clock deadline. Assumptions: reasoning remains useful and
  must not be disabled merely to make JSON validation pass; the existing local
  `research_evidence.read` is the only tool needed because provider-side tools
  would widen the trust boundary without adding evidence; and this compact
  report needs a bounded final budget rather than an open-ended reasoning run.
  DeepSeek-compatible requests now explicitly set `thinking=enabled` and
  `reasoning_effort=high`, omit unsupported sampling controls, cap completion
  output at 4,096 tokens, place the exact schema/example/self-check in the
  trusted system contract, and use a 180-second cancellable end-to-end HTTPS
  deadline. Non-DeepSeek OpenAI-compatible edges retain deterministic
  `temperature=0`. The new async transport closes the request on deadline and
  still caps response bodies at 1 MiB; there is no automatic retry. Validation:
  34 provider-connectivity/external-report/route tests and 197 AI/runtime-route
  tests passed, including
  deterministic cancellation, response parsing, explicit thinking options,
  local-tool evidence export, prompt contract, restart/concurrency, raw
  reasoning exclusion, and unchanged protected financial/authority tables.
  The complete backend suite passed 1,585 tests at 86.47% coverage, the
  trading-safety marker passed 98 tests, and Node 24.14.0 passed all 420 Web
  tests, formatting, and the production build; Black, isort, and diff checks
  also passed.
  After the hard-deadline implementation loaded, the next production v4 request
  was blocked before provider I/O because the current immutable valuation
  snapshot was unavailable, as required. A separate
  frozen-evidence smoke was not executed because local safety policy requires
  a new informed owner approval before private strategy/performance evidence
  may be sent to DeepSeek; therefore this change does not claim a successful
  live v4 report yet. Risk impact: GitNexus rated the provider and service
  classes MEDIUM (route builder and focused tests are the direct consumers),
  with no HIGH/CRITICAL result and no Portfolio, Decision, OMS, ledger, risk,
  broker, capital, or execution process in the affected flow.

- 2026-07-14: AI-native Phase 1.7 adds one human-started,
  provider-neutral saved-backtest external-report boundary at
  `POST /api/ai/external-research/backtest-reports`. Assumptions: selecting a
  result does not itself authorize export; the caller must use an exact phrase
  that explicitly consents to sending that saved result's strategy/window,
  persisted performance, after-cost/cost evidence, research gate, and recorded
  limitations to the configured external model. Account alias/holdings,
  valuation/ledger identity, Account Truth, Operations, paper/shadow, OMS,
  risk, capital, broker, and permission facts are excluded from the external
  payload. Canonical research capture v2 projects the saved metrics without
  recalculation and derives `analysis_ready`; incomplete evidence blocks before
  network I/O. The deterministic orchestrator authorizes exactly one
  `research_evidence.read`, while the provider receives no tools. Valid output
  becomes one locally identity-bound, cited, non-authoritative `REPORT`; it is
  not memory, an account fact, Decision input, trade-plan draft, or authority.
  An atomic run claim prevents concurrent duplicate charges, terminal retries
  are read-only, changed idempotency input fails closed, and malformed raw
  provider bodies are not stored. Validation: 126 focused AI/route tests,
  88 trading-safety tests, and the complete 1,470-test backend suite passed;
  Black and isort checks passed.
  Under Node 24.14.0, all 420 Web tests, Prettier format check, and the
  TypeScript/Vite production build passed. Deterministic cases cover exact
  restart, concurrent duplicate, evidence incompleteness, provider output
  wrapping/normalization, malformed output, secret/raw-body exclusion, audit
  replay, and unchanged OMS/ledger/risk/capital tables. A bounded live trial on
  saved backtest result 5 produced no accepted report: successive explicit
  requests ended as provider timeout, non-JSON output, and schema-invalid
  claims. Each failure is terminal and audited, no raw response body or report
  artifact was stored, and further external evidence export was paused pending
  renewed owner consent under the clearer Phase 1.7 phrase. Risk impact:
  GitNexus rated `_research_evidence_projection` LOW with no indexed upstream
  callers and `create_app` LOW with `server.__main__.main` as its sole direct
  production caller. The route has no scheduler/startup invocation and cannot
  mutate financial state, execution state, kill switch, capital authority, or
  broker submit/cancel capability.

- 2026-07-13: AI-native Phase 1.2 adds one explicitly human-started,
  model-free canonical context capture command at
  `POST /api/ai/research-contexts/capture`. Assumptions: the caller supplies a
  local operator label and exact acknowledgement; this is explicit intent, not
  cryptographic user authentication. Portfolio and Account State reuse one
  canonical Portfolio snapshot, Operations reuses its persisted-fact builder,
  Research Evidence and paper/shadow require exact persisted ids, and Account
  Truth reuses its canonical persisted-evidence projection. The valuation
  snapshot must already be persisted and replayable; snapshot id, ledger cutoff,
  or ledger fingerprint drift fails closed. Content-addressed evidence is
  checkpointed before context assembly so restart after a later audit-stage
  failure resumes the original records without re-reading time-varying sources.
  Completed runs reject changed idempotency input, resist late concurrent
  failure overwrite, and rebuild their context during replay to detect stored
  payload drift. Validation: all 47 AI-runtime tests, seven route-contract
  tests, the complete 1,398-test backend suite, and 84 trading-safety tests
  passed. Under Node 24.14.0, all 413 Web tests, Prettier format check, and the
  TypeScript/Vite production build passed. Focused projection/Operations/
  Account Truth regressions also passed, and Black/isort checks cover every
  changed Python file. Risk impact: GitNexus reported CRITICAL for the reused
  `get_portfolio` path (eight direct callers across six execution flows), so its
  calculation was moved unchanged into a canonical builder and the original
  route remains a delegating compatibility boundary; Account State, Operations,
  and `create_app` changes were LOW risk. The POST writes only `ai_*` evidence,
  context, and capture-lifecycle audit rows. It starts no workflow, invokes no
  provider/model, refreshes no market/broker facts, and cannot mutate OMS,
  ledger, risk decisions, reconciliation, kill switch, capital authorization,
  broker submission, or cancellation state. No research-task UI or authenticated
  multi-user identity is claimed in this phase.

- 2026-07-13: AI-native Phase 1.1 adds the immutable canonical-evidence read
  boundary without connecting a production AI provider or capture workflow.
  Assumptions: an explicit future capture caller must supply an already-built
  canonical Portfolio, Account State, Operations, Research Evidence, Account
  Truth, or paper/shadow payload; the AI boundary never recalculates those
  concepts. Every record binds one exact valuation snapshot, ledger cutoff,
  ledger fingerprint, source schema, as-of, completeness status, and content
  fingerprint. Duplicate content is idempotent across restart; changed content
  receives a new reference. Partial, stale, estimated, or unreconciled evidence
  remains readable for diagnosis but is explicitly non-authoritative.
  Validation: 32 AI-runtime tests, the complete 1,376-test backend suite, and
  82 trading-safety tests passed. Under Node 24.14.0, all 413 Web tests,
  Prettier format check, and the TypeScript/Vite production build passed;
  Black and isort checks also passed. Deterministic cases cover restart,
  duplicate capture, content changes, stored-payload tampering, snapshot/ledger
  drift, partial evidence, context escape, wrong-tool/refresh arguments,
  orchestrator consumption, audit replay, and unchanged protected financial
  tables. Risk impact: GitNexus marks the reused portfolio projection CRITICAL
  (3 direct callers, 12 affected processes) and account-state projection HIGH
  (4 direct callers), so neither was modified. The new boundary is additive and
  LOW risk: it writes only `ai_canonical_evidence`, registers no route,
  scheduler, startup hook, background model task, real provider, or API key,
  and cannot contact providers or modify OMS, ledger, risk decisions, kill
  switch, capital authorization, broker submission, or cancellation state.

- 2026-07-13: The canonical portfolio projection now distinguishes current,
  closed, and evidence-review position facts, so a fully sold asset no longer
  appears in current holdings, allocation, grouped allocation, Overview counts,
  Cockpit, live holdings, or current equity-series diagnostics. Assumptions:
  portfolio quantities use the existing six-decimal fund precision; absolute
  residuals at or below half a quantity quantum (`0.0000005`) are economically
  zero, while real positive and negative positions remain current. A zero
  quantity with non-zero available/frozen quantity or more than half a cent of
  market-value/unrealized-PnL evidence is excluded from current holdings and
  exposed under `position_review_items`; clean closures remain available under
  `closed_positions`. Cumulative realized PnL continues to aggregate every
  persisted projected position fact, including closures, and ledger entries,
  fees, valuation snapshot identity, and ledger cutoff remain unchanged.
  Pending-fund orders and account-truth reconciliation evidence retain their
  existing separate review surfaces and are not promoted into current holdings.
  Validation: `uv run pytest -q tests/server/test_position_presence.py
  tests/server/test_projection_service.py tests/server/test_valuation_snapshot.py`
  passed 24 tests; the focused Portfolio route selection passed 36 tests; the
  complete backend suite passed 1,342 tests. Under Node 24.17.0, the Overview
  test file passed 32 tests, the complete Web suite passed 407 tests across 40
  files, `npm run format:check` passed, and `npm run build` completed the
  TypeScript/Vite production build. Black, isort, and `git diff --check` also
  passed. Deterministic fixtures cover a 200-share buy followed by two
  100-share sells, retained sell activity/fees/realized PnL, tiny residuals,
  real long/short quantities, review-required inconsistent evidence, shared
  Portfolio/Overview/Allocation/Cockpit counts, and unchanged valuation/ledger
  identity. Risk impact: GitNexus reports CRITICAL for `PortfolioSnapshot`
  (13 direct, 43 total dependants) and `get_portfolio` (8 direct consumers), and
  HIGH for account-state and current-equity projections. The implementation is
  an additive read-model partition over persisted facts only; it does not
  contact a provider, refresh quotes implicitly, delete history, mutate OMS,
  ledger, risk, kill switch, or capital authorization, or add submit/cancel or
  live-broker authority.

- 2026-07-13: Stage 3.19 replaces implicit runtime-connector reads with a
  persisted-fact controlled-execution operator view and broker-neutral
  lifecycle evidence boundary. Assumptions: database rows are the only
  authoritative inputs for bounded-session capital, headroom, expiry,
  admissions, submissions, reconciliation, gate, and pause visibility;
  broker lifecycle health comes only from explicitly ingested generic
  collector runs; `provider` is provenance rather than adapter selection; a
  third-party adapter remains default-unregistered until separately reviewed
  and explicitly authorized. Missing, stale, expired, paused, unreconciled,
  blocked, unavailable, or truncated evidence fails closed. The legacy runtime
  snapshot endpoint is a labelled migration entry returning canonical lifecycle
  evidence and no live cash, position, order, or fill facts. Validation: 117
  focused backend and acceptance-audit tests, the complete 1,339-test backend
  suite, 406 frontend tests, Decision Cockpit's 54 focused tests, Prettier, and
  the TypeScript/Vite production build passed. Deterministic fakes prove empty
  defaults, pause/reconciliation visibility, collector restart and blocked
  evidence, adapter-call rejection, and zero broker/financial-state side
  effects. Risk impact: CRITICAL at the broker-health/alert orchestration
  boundary (`list_connector_health` has five direct callers across two
  processes; connector alert scanning feeds `scan_alerts`), HIGH for the
  compatibility query path, and MEDIUM for Automation Cockpit. The change
  removes provider contact from reads and adds only fail-closed projections: it
  cannot issue/renew/resume/widen authority, submit/cancel, mutate Account
  Truth, OMS, fills, ledger, risk, kill switch, or scale capital automatically;
  no QMT SDK/runtime or official provider-support claim is added.

- 2026-07-13: Stage 4.4 closes the capital-scaling execution-provenance gap
  with a required `execution_scope` fact in evidence-window v2. Assumptions:
  the computed operating sample owns the canonical reviewed order set; every
  order must bind either one persisted controlled-session rate admission or one
  current clear exact-batch reconciliation record; an expired or revoked
  session may remain valid historical evidence only when immutable identity and
  the admission-time effective/expiry window still match; a batch must be
  wholly contained in the review sample and is re-resolved against current OMS,
  transition, fill, and reconciliation facts. Unbound, competing, orphan,
  cross-window, drifted, invalid, or truncated sources block the window. V1
  windows/reviews remain append-only history but cannot satisfy the v2 resolver;
  migration is an explicit recomputation into a new record, not an in-place
  rewrite. Validation: the capital-scaling/service/route group passed 222 tests
  and the complete backend suite passed 1332 tests. Deterministic cases cover
  exact-batch success, missing binding, later batch-source drift, a matching
  historical runtime admission, and legacy v1 rejection. Risk impact: HIGH;
  GitNexus reports 10 direct/67 total dependents for the evidence-window service
  and 11 direct/59 total for the review-audit service, while the resolver is
  MEDIUM with 7 direct/13 total dependents. The change is additive fail-closed:
  it reads persisted facts, adds no QMT/provider adapter or public admission
  route, and cannot issue/renew/resume/widen authority, mutate Account Truth,
  OMS, fills, ledger, risk, kill switch, or submit/cancel a broker order.

- 2026-07-13: Refreshed the complete Python, frontend, build-tool, and container
  dependency baseline to current stable releases. Assumptions: application
  installs remain reproducible from `uv.lock` and `web/package-lock.json`;
  Python 3.12 remains the declared minimum, while Node 24 LTS is the canonical
  frontend runtime across `.nvmrc`, strict npm engine metadata, CI, and Docker.
  The production image validates Python 3.14 without introducing a non-LTS
  Node runtime.
  Dependency freshness does not grant broker, OMS, ledger, risk, kill-switch,
  or capital authority. The migration includes Click 8.4, PyArrow 25, Pydantic
  2.13, Uvicorn 0.51, Vite 8/Rolldown, TypeScript 7, Vitest 4, jsdom 29, and
  Tailwind 4's dedicated Vite plugin. Validation: 1327 backend tests passed independently
  on Python 3.12 and 3.14; 406 frontend tests, the TypeScript/Vite production
  build, two Playwright fail-closed browser scenarios, clean lockfile installs,
  and Python/npm production dependency audits all passed. The clean frontend
  install, build, 406 tests, and two browser scenarios were rerun on Node
  24.17.0; strict engine enforcement rejected Node 26 as intended. Local Docker
  smoke awaits the GitHub runner because Docker Desktop was not running. Risk
  impact: MEDIUM due to the broad runtime/toolchain surface and Tailwind/Vite
  major migrations; the Node runtime normalization itself is LOW risk and
  changes build/development compatibility only. The changes add no QMT/provider
  adapter, live submission/cancel route, strategy-direct broker path, or
  automatic capital expansion.

- 2026-07-13: Stage 3.18 binds internal bounded-session order-rate admission to
  one exact fresh persisted live-gate snapshot. Assumptions: a snapshot is a
  sanitized derived gate fact rather than Account Truth itself; 30 seconds is
  the existing live-gate freshness window; admission remains internal evidence
  and cannot be treated as broker authority. Admission v2 fingerprints the
  snapshot id, fingerprint, session identity, and observation time. Preview
  rejects missing/failed, stale, future, blocked, or identity-drifted sources,
  while the SQLite writer transaction re-reads the latest snapshot so a newer
  blocked fact wins over a clear preview. Existing session, reservation,
  expiry/revocation/pause, order-scope, shared-rate, replay, and concurrency
  gates remain unchanged. Validation: the focused high-risk suite passed 136
  tests and the complete backend suite passed 1327 tests; deterministic tests
  cover provider closure, stale/blocked/identity drift, transaction
  replacement, revocation, rate/budget exhaustion, concurrency, sanitization,
  and zero OMS/fill/ledger effects. Risk impact: HIGH because the limiter has
  12 direct and 65 total
  GitNexus dependents. The change only adds fail-closed requirements and exposes
  no public admit, broker contact, submit/cancel, strategy-direct path, OMS/
  ledger mutation, session widening/resume, or capital scaling.

- 2026-07-13: Stage 3.17 binds broker-neutral collector operational evidence to
  lifecycle clearance. Assumptions: collector adoption is scoped by provider,
  gateway, and account alias; scopes with no collector history retain the
  explicit offline-import path; after adoption, a direct import cannot bypass
  collector health; different-run duplicate evidence cannot mask the latest
  effective failure. The canonical resolver now derives a sanitized read-only
  binding from persisted run/state rows. A prepared restart, blocked disconnect
  or partial batch, unbound observation, or run/state inconsistency adds one
  fail-closed blocker consumed by reconciliation, signed clearance, interlock,
  and the serialized next-order gate. Validation: deterministic unit and
  transaction tests cover healthy binding, restart prepare/commit, duplicate
  semantics, direct-import bypass rejection, partial/disconnected re-blocking,
  clearance race rejection, post-clearance next-order rejection, and the
  optional no-history path. Validation: 63 focused lifecycle/collector/import/
  reconciliation/clearance/submission/route tests passed; the full backend
  suite passed 1,320 tests; Black, isort, Python compilation, and `git diff
  --check` cover formatting, syntax, and patch integrity. Risk impact: HIGH
  because the clearance predicate feeds controlled-submission flows. The
  change only adds conditions that can reject or invalidate eligibility. It
  adds no SDK, provider contact, default adapter, submit/cancel/live permission,
  strategy-direct path, or OMS/fill/ledger/risk/kill-switch/capital mutation.

- 2026-07-13: CI now enforces an 85% statement-coverage floor across all
  production Python packages, uploads `coverage.xml`, and runs independent
  production dependency audits for the locked Python/server environment and npm
  runtime dependencies. The measured clean-HEAD baseline is 87% with 1,276
  passing tests. An unused ECharts dependency with a published moderate XSS
  advisory was removed so npm audit can fail on moderate-or-higher findings.
  The Python audit also drove targeted lock upgrades for FastAPI, Starlette,
  idna, lxml, urllib3, and soupsieve; FastAPI's new nested included-router
  representation required test-only route introspection compatibility, while
  the HTTP contracts and production route implementations remained unchanged.
  Dependabot monitors uv/Python, npm, GitHub Actions, and Docker base images
  weekly without auto-merge.
  Assumption: a two-point margin protects against meaningful regression while
  leaving room for small platform-specific coverage differences; dependency
  PRs remain subject to manual review and the full safety CI. Validation:
  `pytest --cov` in a clean `git archive` workspace (`1,276 passed`, 86.68%);
  `uv run --extra dev pip-audit` (`No known vulnerabilities found`); `npm
  --prefix web audit --omit=dev --audit-level=moderate` (`0 vulnerabilities`);
  GitHub `Production dependency audit`. Risk impact: verification and dependency
  maintenance only. No account fact, risk gate, paper/shadow state, OMS,
  reconciliation, broker gateway, kill switch, or execution authority changes;
  no dependency update is automatically merged or deployed.

- 2026-07-13: Two GitHub-hosted protections remain explicitly unavailable for
  this private personal repository: the branch-protection/rulesets APIs reject
  required-check configuration with HTTP 403 unless the account is upgraded or
  the repository is made public, and the code-scanning API rejects CodeQL with
  HTTP 403 because GitHub Code Security is not enabled. No failing or silently
  skipped CodeQL workflow was added, and repository visibility was not changed.
  When the hosting capability becomes available, the current named CI jobs can
  be selected as required checks and CodeQL can be enabled for Python and
  JavaScript/TypeScript. This is a hosting limitation, not a claim that static
  analysis or branch enforcement is already active.

- 2026-07-13: CI now runs a small Playwright browser-safety suite against the
  built React app served by the real FastAPI runtime. It opens Decision,
  Trading, and Account Truth review surfaces, verifies the kill-switch control
  is visible, and rechecks capital authority, per-order bridge, and controlled
  submission defaults from the browser context. Assumption: these few critical
  paths provide stable release protection without turning the whole UI suite
  into brittle end-to-end duplication; detailed component behavior remains in
  Vitest. Validation: `npm --prefix web run build`; `npm --prefix web run
  test:e2e`; GitHub `Browser safety smoke`. Risk impact: read-only browser and
  status checks only. The test starts the scheduler disabled and cannot grant
  authority, create orders, submit to a broker, mutate OMS/ledger state, or
  bypass manual confirmation. Vitest is explicitly scoped to `web/src` so the
  Playwright suite cannot be collected by the unit-test runner, and JUnit
  evidence uploads even when a test command fails.

- 2026-07-13: CI now builds and starts the actual Docker deployment artifact.
  The runtime image uses Node 24 for the React build, pins uv 0.11.28, installs
  the Python environment from `uv.lock` with `uv sync --frozen`, and runs as the
  unprivileged `karkinos` user. The smoke check starts with live scheduling
  disabled and asserts that capital runtime authority, per-order bridge broker
  submission/live gateway, automatic/strategy-direct submission, recovery
  resubmission, and production gateway registration all remain disabled.
  Assumption: a generated minimal `{}` local config and an isolated data volume
  owned by the image's non-root runtime UID/GID represent the safest deployable
  default; private account/provider facts are not needed for startup
  verification. Validation: `.venv/bin/python -m pytest
  tests/scripts/test_verify_docker_runtime.py`; GitHub `Docker runtime smoke`
  build/start/HTTP/non-root checks. Local Docker daemon was unavailable, so the
  Linux image build is intentionally verified by Actions. Risk impact: the
  deployment becomes more reproducible and gains fail-closed assertions; no
  broker adapter, credential, account fact, OMS/ledger mutation, or execution
  authority is added.

- 2026-07-13: CI now has an independent fail-closed trading-safety gate and
  incremental Python formatting/import checks. The `trading_safety` marker
  covers Account Truth gating, manual/default automation controls, paper/shadow
  isolation, OMS transitions, session automatic pause, strategy/broker
  separation, prior-batch reconciliation, one-shot controlled submission, and
  signed reconciliation clearance. Assumption: historical Python formatting
  debt is not rewritten alongside active main-thread financial changes, so
  Black/isort enforcement applies to changed Python files and prevents new
  drift while preserving the existing worktree. Validation: `.venv/bin/python
  -m pytest -m trading_safety`; `.venv/bin/black --check` and
  `.venv/bin/isort --check-only` on the phase's changed Python files. Risk
  impact: tests only tighten verification; no production authority, account
  fact, risk, OMS, reconciliation, broker, ledger, or kill-switch behavior is
  changed.

- 2026-07-13: CI acceptance evidence is now verified instead of trusting only
  static completion flags. The strict export checks that all 352 declared
  evidence paths stay inside the repository and exist, rejects validation
  commands outside the deterministic allowlist, binds passing backend and
  frontend JUnit reports by SHA-256, and uploads the resulting JSON artifact.
  Assumption: one full backend suite and one full frontend suite are the
  authoritative CI executions; individual manifest commands remain human-
  readable reproduction recipes and are structurally validated rather than
  redundantly executed hundreds of times. Validation: `.venv/bin/python -m
  pytest tests/test_acceptance_audit_verification.py
  tests/test_acceptance_audit_cli.py tests/test_ci_workflow.py`; `npm --prefix
  web run test -- --reporter=junit`; strict structural export for all audits.
  Risk impact: LOW for trading authority because this changes only CI/reporting
  evidence. It does not alter account facts, risk gates, OMS, broker submission,
  reconciliation, kill switch, ledger state, or manual-confirmation defaults.

- 2026-07-13: Stable control-plane identifiers no longer encode roadmap stage
  numbers. Per-order broker-soak promotion bindings, controlled-session bridge
  blockers, acceptance criterion keys, and the capital-authorization policy
  audit selector now use durable domain terminology. Contract schema versions
  advance where public status, dossier, envelope, or attestation identifiers
  changed, so older signed evidence fails closed instead of being silently
  reinterpreted. A rule- and path-scoped Gitleaks allowlist covers only the
  historical false-positive acceptance key that caused full-history CI scans to
  fail; default secret rules remain enabled. Assumption: roadmap headings and
  milestone-specific acceptance-builder names may retain Stage labels because
  they describe historical slices rather than runtime contracts. Validation:
  `uv run pytest -q tests/test_per_order_confirmation.py
  tests/test_controlled_session_envelope.py tests/test_acceptance_audit.py
  tests/test_acceptance_audit_cli.py`; Gitleaks v8.30.1 full-history and working-
  tree scans. Risk impact: HIGH contract-surface sensitivity because session
  blocker codes feed runtime-authority, budget, and pause workflows; no gate is
  removed or relaxed, renamed blockers remain fail-closed, and no broker/OMS/
  ledger/capital authority is added.

- 2026-07-13: Stage 3.15/3.16 supersedes the QMT-specific naming with a
  broker-neutral lifecycle and collector-ingestion boundary. Assumptions:
  `provider` is provenance only; any real SDK/callback/poll/local-file adapter
  is a default-unregistered edge component requiring separate review and user
  authorization; a collector batch is local input rather than authoritative
  Account Truth or execution authority. The canonical export is now
  `karkinos.broker_order_lifecycle_export.v1`, with generic service, blocker,
  acknowledgement, CLI, and persisted-table terminology. The retired
  `karkinos.qmt_order_lifecycle_export.v1` contract is rejected by the normal
  importer and isolated behind an explicit offline migration command; existing
  historical rows are never silently rewritten. Stage 3.16 adds a strict local
  batch contract with deployment/release/user-authorization evidence,
  connection/batch status, cursor and callback telemetry, and two-phase
  lifecycle-prepare/run-commit recovery. Deterministic fake/fixture tests cover
  restart replay, exact idempotency, different-run duplicates, cursor conflicts,
  regressions/gaps, duplicate/out-of-order callback telemetry, disconnect,
  partial batches, deployment drift, preview integrity, and absent-database read
  behavior. Validation: 162 focused lifecycle/collector/reconciliation/import/
  config/gateway/soak/controlled-session tests passed; 84 acceptance-audit tests
  passed; the full backend suite passed 1,313 tests. Black/isort, Python
  compilation, `git diff --check`, and the documented GitNexus fallback cover
  formatting, syntax, and patch scope. Risk
  impact: lifecycle repository reach is CRITICAL and parser/config paths include
  HIGH-impact symbols, so the migration only narrows authority. No SDK, provider
  contact, strategy-direct path, submit/cancel, OMS/fill/ledger/risk/kill-switch/
  capital mutation, scheduler, default adapter registration, or support claim is
  added. This entry supersedes the provider-specific product direction recorded
  immediately below while preserving it as historical audit context.

- 2026-07-13 (superseded naming; retained for audit): Stage 3.15 added a QMT
  exact-order lifecycle evidence foundation
  without registering a broker connection. Assumptions: an external read-only
  collector, not Karkinos, normalizes one QMT order into the strict
  `karkinos.qmt_order_lifecycle_export.v1` contract; `source_sequence` is
  monotonic across one provider/gateway/account-alias scope; both broker and
  client order ids are independently observed; persisted lifecycle facts are
  supporting evidence rather than Account Truth, OMS state, ledger facts, or
  execution authority. The CLI previews by default and requires `--record`
  plus an exact non-authority acknowledgement. It hashes raw account ids,
  omits local paths, rejects credentials, malformed/stale/timezone-free facts,
  status/quantity/fill inconsistency, sequence/account/identity/contract drift,
  and preview mutation. One canonical persisted resolver and full-fill
  predicate feed execution reconciliation, the signed-clearance transaction,
  interlock preview, and the next-order submit transaction. A partial/cancel/
  conflicting observation committed before clearance rejects that clearance
  under the shared SQLite writer lock; one committed after an older clearance
  reopens reconciliation and makes that intent unresolved before another
  external call. Full lifecycle evidence still cannot clear without the Stage
  3.14 broker statement, fresh Account Truth, exact identities, and human
  signature. Validation: 53 focused lifecycle/reconciliation/clearance/
  interlock/submission tests passed; 81 acceptance-audit tests passed; the full
  backend suite passed 1,296 tests. Black, isort, Python compilation, and
  `git diff --check` cover the changed code and patch surface. Risk impact:
  GitNexus marks `ExecutionReconciliationService` HIGH (24 direct, 80 total,
  one lifespan process) and its classifier HIGH; it reports the SQLite submit
  and clearance methods LOW/zero upstream because database method calls are not
  resolved, but their semantic risk is CRITICAL because they gate real-fill OMS
  mutation and the next broker call. The implementation only narrows authority:
  production still has no QMT collector, default write adapter, release
  provider, executable cancel, strategy-direct/automatic submit, automatic
  ledger mutation, session widening, capital expansion, or pilot enablement.

- 2026-07-13: Stage 3.14 order-identity hardening removes the remaining manual
  symbol/side mapping from controlled full-fill clearance. Assumptions:
  `broker_order_id` and `client_order_id` are imported evidence only; both
  must match the persisted controlled submit intent exactly, all selected rows
  must still come from one validated import and total the full OMS quantity,
  and a read-only connector or legacy CSV without both identities remains
  incomplete and cannot clear. Canonical broker-statement and persisted
  broker-evidence schemas advance to v2; unsafe identifiers, one-sided identity
  reuse, quantity drift, cross-import aggregation, and post-rejection trade
  evidence fail closed. Validation: 45 focused broker-statement, repository,
  connector, execution-reconciliation, and signed-clearance tests passed; 81
  acceptance-audit tests passed; the full backend suite passed 1,281 tests.
  Black, isort, and `git diff --check` cover the changed Python and patch
  surface. Risk impact: CRITICAL-sensitive because this evidence can feed the
  signed transaction that records real fills, advances OMS, and releases the
  global submission interlock. The change only narrows that boundary: it adds
  no gateway registration, default broker submission, strategy-direct path,
  automatic execution, partial-fill/cancel inference, production-ledger write,
  session widening, or capital expansion.

- 2026-07-13: Stage 3.14 adds separately signed exact-full-fill reconciliation
  clearance. Assumptions: selected trade events are an operator-reviewed mapping
  to one controlled broker order because the generic CSV contract has no broker
  order id; every event must come from one validated import, aggregate to the
  exact OMS quantity, and match Account Truth from the same import/file no older
  than 120 seconds with clear gates, zero unresolved reconciliation, and covered
  ledger evidence. A distinct Ed25519 action signs the exact clearance. One
  SQLite `BEGIN IMMEDIATE` transaction re-reads source fingerprints, records
  evidence-linked real fills, transitions OMS `submitted -> accepted -> filled`,
  persists clearance and terminal no-action reconciliation, and releases the
  cross-order interlock. It does not mutate the production ledger. Partial
  totals, cross-import aggregation, superseded evidence, wrong signature domain,
  and conflicting concurrency fail closed; exact concurrent retries are
  idempotent. Validation: `uv run pytest -q
  tests/test_controlled_submission_reconciliation_clearance.py
  tests/test_execution_reconciliation_service.py
  tests/test_controlled_broker_submission.py tests/test_operator_approval.py
  tests/server/test_controlled_broker_submission_routes.py`; `uv run pytest -q
  tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py`; full suite
  `uv run pytest -q`. Risk impact: CRITICAL-sensitive because the transaction
  creates real fill evidence, advances terminal OMS state, and releases a global
  submission interlock. Safety is bounded by fresh Account Truth, exact source
  fingerprints, separate human signature, transaction serialization, no
  production adapter/release provider by default, no automatic or strategy-
  direct submit, no partial-fill/cancel inference, no automatic ledger write,
  and no capital/session widening.

- 2026-07-13: Stage 3.13 adds a fail-closed unreconciled-submission interlock
  and operator visibility. Assumptions: a broker acknowledgement proves only
  receipt, not fill or reconciliation; `prepared`, `submitted`, and
  `submission_unknown` therefore remain globally exclusive until a future
  signed clearance binds exact broker/Account Truth evidence, while a
  definitive rejection/not-found safely releases the interlock. Preview reports
  sanitized unresolved ids and the same check runs under SQLite `BEGIN
  IMMEDIATE`, preventing different-order concurrency from issuing two external
  calls. Execution reconciliation classifies controlled intent/OMS/broker
  evidence, unknown outcomes create critical query-only alerts, and Operations
  exposes the recovery task. Operations/alerts select only each order's latest
  reconciliation item; superseded unknown items remain in historical runs but
  no longer masquerade as the current open task. Validation: `uv run pytest -q
  tests/test_controlled_broker_submission.py
  tests/test_execution_reconciliation_service.py tests/test_automation_alerts.py
  tests/test_operations_today.py tests/server/test_controlled_broker_submission_routes.py
  tests/server/test_execution_reconciliation_routes.py
  tests/server/test_operations_routes.py tests/server/test_automation_routes.py`.
  Risk impact: this changes HIGH-risk automation alerts and the critical
  submission/database boundary, but only toward additional blocking. It does
  not register a production gateway, submit automatically, resubmit unknown
  orders, cancel at the broker, infer fills, mutate OMS from broker evidence,
  write the production ledger, clear reconciliation, or widen capital/session
  authority.

- 2026-07-13: Stage 3.12 adds a default-closed one-shot controlled broker
  submission foundation. Assumptions: an explicitly injected gateway must
  support idempotent client order ids, side-effect-free dry-run, fresh health,
  one exact submit call, and query-by-client-id; a separately owned signed
  release source must attest broker agreement, connector testing, program-
  trading reporting review, risk-control review, and manual-each-order mode.
  SQLite atomically persists the submit intent and OMS `submission_pending`
  transition before broker contact; accepted/rejected/unknown outcomes remain
  distinct, and unknown recovery waits 30 seconds and only queries—never
  resubmits. Validation: `uv run pytest -q tests/test_controlled_broker_submission.py
  tests/test_per_order_confirmation.py tests/test_operator_approval.py
  tests/server/test_controlled_broker_submission_routes.py
  tests/server/test_per_order_confirmation_routes.py`. Risk impact: this is the
  first code path capable of calling an explicitly injected broker write
  gateway and therefore is HIGH/CRITICAL-sensitive. Production injects neither
  the write gateway nor release provider by default; manual final signature,
  Account Truth/risk/paper-shadow/reconciliation/kill-switch gates remain
  mandatory, while strategy-direct/automatic submission, broker cancel,
  fill/ledger mutation, session-wide authority, and automatic scale-up remain
  unavailable.

- 2026-07-12: Overview's review queue now deduplicates the Operations manual
  handoff and the daily trading-plan card when both represent the exact same
  manual order-intent review. Quote diagnostics also treat the canonical
  normalized quote status as authoritative: an optional provider error or
  stale-reason annotation cannot turn a persisted `confirmed` close/NAV into
  an artificial user action, while missing, stale, estimated, error, and fund
  estimate sources still require review. Manual-confirmation summaries join
  each intent to canonical holding/market instrument metadata by exact symbol,
  showing readable names with codes and quantities for the first three orders
  plus a remaining count. Validation: 406 Web tests and the production Web
  build passed. Risk impact: this changes presentation and action counting
  only; it does not relax market-data gates, confirm orders, mutate OMS/ledger
  state, contact a broker, or bypass manual confirmation.

- 2026-07-12: Decision candidates now pass through one deterministic
  account-level portfolio allocator before daily-plan and batch-risk
  construction. Raw strategy targets remain auditable as
  `raw_target_weight`; executable targets are capped by the configured
  single-position limit, cash reserve, current holdings, persisted prices, and
  board-lot rules. Quantities are target-position deltas rather than total
  target holdings, buy cash is consumed sequentially, and expected sell
  proceeds are not reused before settlement. Daily order intents now carry the
  exact risk-decision and Account Truth import references; persisted
  paper/shadow orders are reattached to their matching Decision action, while
  all paper, shadow, and backtest orders/fills are excluded from production
  strategy-PnL attribution. Assumptions: allocation uses only the canonical
  persisted valuation snapshot; A-share buys use 100-share lots; fund
  redemptions may use fractional current quantities; no simulated fill grants
  production execution authority. Validation: 1,141 backend tests, 405 Web
  tests, production Web build, and a real-account deterministic rerun with five
  passed risk decisions, five manual-confirmation intents, five simulated
  orders/fills, and zero production-attributed simulated fills. Risk impact:
  this removes false concentration/cash blockers and false evidence gaps while
  preserving Account Truth, risk, manual-confirmation, kill-switch, disabled
  broker submission, and production-ledger gates.

- 2026-07-12: Decision, daily trading-plan, and batch pre-trade risk reads now
  use the same persisted immutable valuation snapshot and ledger projection as
  Portfolio instead of scheduler portfolio/quote memory. Candidate action
  tasks are restricted to the valuation trade date (or the latest dated batch
  when no valuation exists) and deterministically deduplicated by symbol and
  strategy. Account Truth manual reviews now bind the exact reconciliation
  item fingerprint, append review history, become visibly stale after source
  facts change, and cannot override material mismatches. Broker evidence that
  predates the latest local ledger fact fails closed. Assumptions: naive action
  and ledger timestamps are China-market facts interpreted in Asia/Shanghai;
  missing persisted valuation evidence cannot be replaced by scheduler memory.
  Validation: `uv run pytest -q`, `cd web && npm test -- --run`, and
  `cd web && npm run build`. Risk impact: this intentionally increases
  Account Truth and execution-gate blocking when evidence is stale or merely
  annotated, while preserving manual confirmation, disabled broker submission,
  production-ledger immutability, and kill-switch precedence.

- 2026-07-12: Financial data paths now use persisted observations and
  content-addressed valuation policy v2. The snapshot freezes confirmed
  close/NAV, previous-close baselines, original intraday observations, ledger
  cutoff, ingestion-run references, and exact effective timestamps. Holdings,
  intraday/daily equity, Overview, and Explainability share one canonical daily
  performance calculation; known fees are attributed rather than labeled as
  residual; missing baselines propagate unavailable rather than zero; current
  prices cannot leak into historical reconstruction; and closed instruments no
  longer degrade later dates. Quote-run completion, ledger insertion, broker
  settlement, and startup publish replayable snapshots, while a publication
  pointer blocks newer unpublished facts with HTTP 503. Assumptions: naive
  China-market timestamps use `Asia/Shanghai`; a persisted `1d` bar is confirmed
  close/NAV evidence; same-day sells remain fail-closed until canonical lot
  attribution exists. Validation: 1,131 backend tests, 36 affected Web tests,
  production Web build, real-account cross-surface accounting invariants,
  snapshot-id replay, and `git diff --check` passed. Risk impact: valuation and
  quote adaptation affect HIGH/CRITICAL portfolio paths, so all direct surfaces
  were migrated and tested together. This change adds no broker-write path,
  execution authority, or automatic real-money order behavior.

## v1.8 Progress

- 2026-07-13: Stage 3.11 adds a separately signed paused-session replacement
  protocol without an in-place resume or broker path. Ordinary issuance now
  blocks an unexpired paused session in the same authorization/account/strategy
  scope. Replacement requires a fresh attestation and atomic reservation, a
  continuous suffix of at least two post-pause clear gate snapshots spanning
  60 seconds with the newest no older than 30 seconds, and a distinct Ed25519
  `replace_paused_controlled_session` approval plus signature possession. Any
  blocked observation restarts the window; the write transaction rejects a
  newer superseding snapshot. Authorization/account/strategy/operator,
  order/symbol scope, reserved gross/buy/turnover/order count, per-symbol
  amount, request rate, and session duration cannot widen. One SQLite
  `BEGIN IMMEDIATE` transaction records replacement/revocation evidence,
  revokes the predecessor, and inserts the new salted-token-hash session;
  exact retries do not reissue the token and conflicting handoffs cannot both
  succeed. Assumptions: expired or explicitly revoked sessions are terminal and
  may be followed by a genuinely new signed chain; source-drift pauses that
  cannot regain clear evidence require explicit revocation rather than bypass;
  the predecessor budget reservation remains immutable and continues counting
  through its original window, so replacement allocation is conservative.
  Validation: 124 focused authority, approval, envelope, reservation, pause,
  live-gate, rate, and route tests passed; the full backend suite passed 1,232
  tests; all 33 acceptance audits report 328/328 complete; and Black, isort,
  and `git diff --check` passed. Risk impact: GitNexus reports CRITICAL for
  shared `AppDatabase` (340 direct dependants and
  app lifespan), HIGH for runtime authority (6 direct dependants) and operator
  approval (19), and LOW for input/route/audit registration. Changes add
  isolated append-only tables/methods and exact signed-domain mapping; no
  existing broker gateway, OMS, production ledger, capital evaluator, or
  strategy execution flow is modified. This adds no broker submit/cancel,
  public runtime admit, renew/widen, automatic capital increase, raw credential
  storage, or strategy-direct broker access.

- 2026-07-12: Stage 3.10 adds persisted live-gate snapshots and automatic-pause
  orchestration without broker execution. A monitoring-only resolver retains
  enough persistent identity to pause an enabled session after upstream source
  drift but explicitly grants no runtime authority. Snapshot capture reduces
  Account Truth, signed-envelope risk/paper-shadow/reconciliation/gateway
  evidence, materialized quote freshness, persisted runtime admissions and
  rate rejections, and kill-switch state to a typed allowlist; missing or
  invalid facts fail toward pause. Exact observations reuse an append-only
  fingerprint-bound row, snapshots expire after 30 seconds, quotes after 120
  seconds, and three rate rejections in 60 seconds trip the spike gate. The
  explicitly started scheduler evaluates enabled sessions, and the sole POST
  evaluation route requires that session's token and can only preserve or
  reduce authority. Assumptions: persisted admissions represent initial
  order-count consumption; loss/drawdown use remaining budgets from the current
  attestation until broker-execution and production-ledger sources exist; any
  missing replacement fact pauses. Validation: focused live-gate, pause,
  authority, route, and scheduler tests passed 56 tests; the full backend suite
  passed 1,221 tests; all 32 acceptance audits report 320/320 complete; and
  Black, isort, and `git diff --check` passed. Risk impact: prior GitNexus
  analysis reports MEDIUM for `AppDatabase`
  (4 direct callers), runtime authority (2), automatic pause (2), and scheduler
  (3), and LOW for app lifecycle/route registration; no HIGH/CRITICAL symbol is
  changed. This adds no broker submit/cancel, OMS/production-ledger mutation,
  session issue/resume/renew/widen, automatic capital change, or strategy-direct
  broker path.

- 2026-07-12: Stage 3.9 adds separately signed, expiring runtime-session
  authority without adding broker authority. Issuance re-resolves one exact
  current envelope attestation and atomic reservation, binds account, strategy,
  orders, window, and rate, then requires a distinct Ed25519
  `issue_controlled_session` approval plus possession of its matching signature
  over the deterministic issuance fingerprint. Public verification/history
  responses omit signature bytes, so an approval id alone cannot consume the
  token; the earlier attestation approval cannot be reused. SQLite
  `BEGIN IMMEDIATE` allows one session per reservation and serializes exact or
  concurrent retries. A high-entropy capability token is returned only once;
  only a salted SHA-256 hash is stored, and internal rate admission requires
  token authentication. Resolution rechecks expiry, pause state, and the
  current reservation/attestation chain. A separate signed
  `revoke_controlled_session` action plus matching signature possession persists
  one allowlisted-reason event and changes enabled to revoked without a resume
  transition. Admission rechecks
  persistent enabled state, fingerprints, expiry, and pause inside its own
  write transaction, preventing a stale authenticated provider from racing
  revocation. Assumptions: losing the one-time token requires a separately
  reviewed future recovery flow rather than token replay; one reservation may
  never issue a replacement session; expiry is computed without mutating the
  immutable issuance row; and future resume must be a new signed protocol, not
  an update to enabled. Validation: focused authority/rate/route/approval/
  envelope tests passed; the full backend suite passed 1,210 tests; all 31
  acceptance audits report 312/312 complete; and Black, isort, and
  `git diff --check` passed. Risk impact: GitNexus reports MEDIUM for
  `AppDatabase` (4 direct dependants), `OperatorApprovalService` (6), runtime
  limiter (2), envelope (2), and budget reservation (2); route models and
  `create_app` are LOW; no HIGH/CRITICAL symbol changed. This enables bounded
  internal runtime authority only. It adds no public runtime admit, session
  resume/renew/widen, automatic capital change, OMS/production-ledger mutation,
  gateway contact, broker submit/cancel, or strategy-direct broker path.

- 2026-07-12: Stage 3.8 adds a durable automatic-pause controller while
  retaining default closure. An internal evaluation binds an exact current,
  enabled, authority-verified session and reservation to a sanitized allowlist
  of Account Truth, risk, prior reconciliation, paper/shadow, gateway health,
  market data, budget, rate, kill-switch, loss/drawdown, rejection,
  account-change, and consecutive-error facts. Missing gate-provider evidence
  for an identified session fails toward pause; missing or invalid session
  identity is rejected and audited because no safe target exists. SQLite
  `BEGIN IMMEDIATE` stores the first immutable pause event and a one-way
  `paused` runtime state; exact/concurrent repeats reuse it, identity drift
  fails closed, and later clear gates cannot auto-resume. Runtime rate admission
  checks the durable state inside its own write transaction before retry/window
  logic, blocking a stale provider. Production uses no session/gate providers
  and exposes only read-only status/state/event routes. Assumptions: the first
  pause cause is authoritative for the state; provider snapshots are allowlist-
  sanitized; session providers expose only currently enabled identities; and a
  future resume requires a distinct signed operator review. Validation commands:
  `uv run pytest tests/test_controlled_session_automatic_pause.py
  tests/server/test_controlled_session_automatic_pause_routes.py -q`, the full
  backend suite (1,196 passed), all 30 acceptance audits (304/304), formatters,
  and `git diff --check` passed.
  Risk impact: GitNexus reported MEDIUM for `AppDatabase` (4 direct dependants)
  and `ControlledSessionEnvelopeService` (2), LOW for the runtime limiter (2)
  and `create_app` (1), with no HIGH/CRITICAL change. This adds no session
  issuance/resume, OMS/ledger mutation, broker contact, order submission/
  cancellation, capital expansion, or automatic real-money execution.

- 2026-07-12: Stage 3.7 adds a real internal runtime order-rate admission
  ledger while keeping production closed until authenticated session issuance
  exists. A candidate admission must resolve a current enabled and
  authority-verified bounded session; bind exact session/reservation
  fingerprints, verified budget reservation, clear upstream/kill-switch gates,
  authorization/account/strategy, in-scope order and unique request id; fall
  inside the server-validated effective/expiry window; and use a positive rate
  no greater than 600 orders/minute. SQLite `BEGIN IMMEDIATE`
  serializes a server-time 60-second sliding window shared by authorization and
  account, applies the strictest overlapping-session rate, and permits only one
  contender for the final slot. Exact retries reuse one immutable admission;
  order/request replay conflicts and rate failures become append-only rejection
  evidence. Production explicitly sets `session_provider=None` and exposes only
  read-only status/history routes, so no public admission mutation exists.
  Assumptions: server UTC epoch milliseconds are authoritative; events exactly
  60 seconds old leave the window; all strategies sharing one authorization and
  account also share its rate; 600/minute is a defensive implementation ceiling
  rather than a recommended trading rate; and future session issuance/revocation
  must provide database-backed current state before the limiter can be wired.
  Validation: 118 focused service/route/acceptance tests passed, including real
  concurrent last-slot contention, exact boundary, shared strictest-rate,
  replay, pause/expiry, provider-failure, and route exposure cases; the new
  `controlled_session_runtime_rate_limiter` audit reports 7/7 complete; all 29
  registered audits report 297/297 criteria complete; `.venv/bin/pytest -q`
  passed 1,170 tests; and Black, isort, and `git diff --check` passed. Risk
  impact: GitNexus reports MEDIUM for `AppDatabase` and
  `ControlledSessionEnvelopeService`, with 4 and 2 direct dependants, and LOW
  for `create_app` with 1 direct caller; new limiter symbols are not yet indexed.
  No HIGH/CRITICAL symbol was changed. The envelope blocker is renamed to
  `runtime_order_rate_limiter_not_wired_to_authenticated_session`; automatic
  pause, authenticated session issuance/resume/revoke, live gateway, broker
  submission, OMS/production-ledger mutation, and capital scale-up remain
  disabled.
- 2026-07-12: Stage 3.6 binds explicit per-symbol runtime limits into the
  proposal-only controlled-session envelope and its atomic budget reservation.
  The request must provide one positive value (maximum four decimal places) for
  exactly every projected symbol. Each limit is capped by both the recorded
  capital evaluation's `symbol_capital_limit` and effective capital, must cover
  the conservative gross projection, and is included in the signed envelope
  and attestation identity. The reservation persists projected/capacity maps in
  fixed 0.0001 CNY units. Under the existing SQLite `BEGIN IMMEDIATE` lock,
  overlapping reservations are summed independently per symbol; same-symbol
  contention above the strictest signed limit fails, disjoint symbols may
  proceed only while shared capital/cash/turnover/order budgets remain clear,
  and legacy overlapping rows without symbol evidence fail closed.
  Assumptions: the current capital-evaluation contract exposes one conservative
  `symbol_capital_limit`, so this initial stage applies that ceiling to every
  symbol already inside the signed policy scope; the operator may choose a
  lower explicit value for any symbol, while future Account Truth facts may
  tighten but never implicitly widen it; gross buy/sell values are not netted;
  and symbol reservations have no release semantics before their window ends.
  Validation: focused envelope/reservation/route/acceptance coverage passed 118
  tests, including real two-thread same-symbol contention, disjoint-symbol, and
  legacy-missing-evidence cases; the new `controlled_session_symbol_budget`
  audit reports 7/7 complete; all 28 registered audits report 290/290 criteria
  complete; `.venv/bin/pytest -q` passed 1,150 tests; and Black, isort, and
  `git diff --check` passed. Risk impact: GitNexus
  reports MEDIUM for `ControlledSessionEnvelopeService`,
  `ControlledSessionBudgetReservationService`, and `AppDatabase`, with only 2,
  2, and 4 direct dependants respectively; request models and the acceptance
  registry are LOW. No HIGH/CRITICAL symbol was changed. A clear map removes
  only `per_symbol_runtime_limits_not_bound`; runtime rate limiting, automatic
  pause, authenticated session issuance/resume/revoke, live gateway, broker
  submission, OMS/production-ledger mutation, and scale-up remain disabled.
- 2026-07-11: Stage 3.5 adds an atomic, non-authorizing controlled-session
  budget reservation after the exact signed envelope is re-resolved. The
  attestation now persists its exact prior-batch fingerprint and can be
  revalidated against current capital evidence, Account Truth, per-order
  gateway dry-runs, prior-batch reconciliation, kill switch, time window, and
  currently trusted Ed25519 approval. The new
  `/api/automation/controlled-sessions/budget-reservations` service fingerprints
  the immutable authorization/account scope, China trading day, exact window,
  conservative gross/cash/turnover amounts, order count, and capacities. SQLite
  `BEGIN IMMEDIATE` serializes overlapping reservations; exact reruns reuse one
  immutable row, one attestation cannot reserve twice, and unavailable capital,
  cash, daily turnover, or order count fails before insert. Rejected attempts
  are append-only events. Assumptions: positive monetary amounts are rounded up
  to fixed 0.0001 CNY units; authorization id plus account alias is the shared
  pool even when strategy ids differ; capital/cash/order-count reservations
  overlap only for intersecting windows, while turnover remains conservatively
  held for the whole China trading day; explicit release/cancel semantics do
  not yet exist, so a reservation cannot be reused for another envelope; and a
  reservation is budget state rather than runtime authority. Validation:
  focused controlled-session/acceptance coverage passed 103 tests; the Stage
  3.5 standalone suite passed 7 tests, including a real two-thread contention
  test where only one over-capacity request succeeds; the new
  `controlled_session_budget_reservation` audit reports 7/7 complete; all 27
  registered audits report 283/283 criteria complete; `uv run pytest -q`
  equivalent `.venv/bin/pytest -q` passed 1,110 tests; and Black, isort, and
  `git diff --check` passed. Risk impact:
  GitNexus reports LOW for `ControlledSessionEnvelopeService` (2 direct
  dependants), `AppDatabase` (4 direct dependants), `create_app` (1 direct
  caller), and `AUDIT_REGISTRY` (no direct dependants); new reservation symbols
  are not yet indexed. This stage clears the atomic-reservation evidence
  blocker only for a future issuance dossier. It does not issue/enable/resume a
  session, mutate OMS/production ledger, contact a broker, submit/cancel, grant
  or scale capital authority, or let strategy code reach a broker. The existing
  HIGH OMS and CRITICAL broker-gateway services remain unchanged.
- 2026-07-11: Stage 3.4 adds a short-lived session-start Account Truth gate and
  binds it into the proposal-only controlled-session envelope. The new
  `/api/automation/session-start-account-truth` service rebuilds a sanitized
  current source from the latest broker import, reconciliation, current ledger
  projection, and manual-review decisions; requires clear reconciliation, a
  passing gate, fresh data, zero unresolved mismatches, a valid source
  fingerprint, explicit zero-authority boundaries, and a source no more than
  120 seconds old; and records clear/rejected attempts append-only. Resolution
  re-runs the source and expires records after 120 seconds. The session request
  and recorded `session_bounded` capital evaluation must carry the same typed
  `session_start_account_truth:<fingerprint>` reference, evidence connector, and
  account alias. Missing/failed providers, connector/account mismatch, source
  drift, or expiry changes the envelope fingerprint, restores
  `session_account_truth_snapshot_not_bound`, and invalidates the prior signed
  approval. Assumptions: 120 seconds is the initial conservative start-gate
  window and may be tightened after real broker timing evidence; the latest
  reconcilable import must be available before session review; the Account
  Truth source itself does not independently expose the account alias, so the
  alias relationship still relies on capital-authorization v2 same-account
  binding and the signed Stage 1 promotion evidence; append-only sequential
  reuse does not replace a later concurrent database uniqueness review.
  Validation: 11 standalone service/route tests and 41 combined session-start/
  envelope tests passed; the broader affected regression group passed 355
  tests; the new `session_start_account_truth_binding` audit reports 7/7
  complete; all 26 registered acceptance audits remain complete; and
  `uv run pytest -q` passed 1,090 tests. Risk impact: GitNexus reports LOW for
  `ControlledSessionEnvelopeService` (2 direct dependants), its request models,
  and `create_app` (1 direct caller); the new Account Truth service/route and
  binding symbols are not yet indexed. A clear record removes only the session
  Account Truth evidence blocker. It does not reserve budget, issue/enable/
  resume a session, mutate Account Truth/OMS/production ledger, change capital
  authority, contact a broker, submit/cancel, or scale capital. The existing
  HIGH OMS and CRITICAL broker-gateway services remain unchanged.
- 2026-07-11: Stage 3.3 binds an exact set of short-lived runtime gateway
  verifications into each proposal-only controlled-session envelope. The request
  must map every OMS order id to one unique verification fingerprint, and the
  recorded `session_bounded` capital evaluation must contain exactly the same
  typed `execution_gateway_verification:<fingerprint>` set. Every preview and
  attestation re-resolves every source through the runtime registry and uses the
  same shared allowlisted binding as Stage 2.5 to match gateway, read-only
  connector, account alias, OMS order id, canonical order fingerprint,
  sanitized dry-run order terms, and disabled authority/submission assertions.
  Missing, extra, reused, non-canonical, expired, drifted, or mismatched evidence
  for one order blocks the whole envelope, restores
  `execution_gateway_runtime_not_verified`, changes the envelope fingerprint,
  and invalidates the previous artifact-bound approval. The exact caller map is
  fingerprinted and retained in rejection identity rather than silently
  trimming keys. Assumptions: all per-order verifications are recorded before
  the capital evaluation that references them; up to 50 order proofs may share
  one separately reviewed gateway/account relationship but never one
  fingerprint; adapter dry-run truthfulness still requires broker sandbox/vendor
  validation; this remains limit-order-only; sequential append-only reuse does
  not replace a later concurrent database uniqueness review. Validation: 24
  controlled-session service/route tests passed; the broader gateway/per-order/
  session/acceptance group passed 123 tests; the new
  `controlled_session_gateway_verification_binding` audit reports 7/7 complete;
  all 25 registered acceptance audits remain complete; and `uv run pytest -q`
  passed 1,071 tests. Risk impact: GitNexus reports LOW for
  `ControlledSessionEnvelopeService` (2 direct dependants) and both request
  models; the shared binding is a new unindexed symbol and its Stage 2.5
  refactor remains covered by per-order regression tests. A fully clear set
  removes only the runtime-verification blocker. Session authority, Stage 1/2
  promotion, session-start Account Truth, per-symbol limits, atomic budget
  reservation, runtime rate limiting, automatic pause, live gateway, broker
  submission, OMS/ledger mutation, resume, and scale-up remain disabled. The
  HIGH OMS and CRITICAL existing broker-gateway services are unchanged.
- 2026-07-11: Stage 2.5 binds the short-lived Stage 2.4 runtime gateway
  verification into the exact per-order confirmation dossier. The recorded
  `manual_each_order` capital evaluation and the request must carry the same
  typed `execution_gateway_verification:<fingerprint>` reference. Every preview
  and confirmation re-resolves the current append-only record, then allowlists
  and matches gateway id, read-only evidence connector, account alias, OMS order
  id, canonical order fingerprint, sanitized dry-run symbol/side/asset class/
  quantity/type/limit price, and the disabled-authority/submission boundary.
  Expiry, source drift, missing/failed providers, or any mismatch re-blocks
  review, restores `execution_gateway_runtime_not_verified`, changes the dossier
  fingerprint, and invalidates the previous artifact-bound operator approval.
  The application route injects the same runtime registry into the resolver;
  production still registers no execution gateway by default. Assumptions: the
  capital evaluation is recorded only after the exact gateway verification it
  references; the reviewed adapter and its zero-side-effect dry-run remain a
  trusted runtime boundary that needs real broker sandbox/vendor validation;
  this slice remains limit-order-only; append-only event reuse is deterministic
  sequentially, while concurrent database uniqueness remains a later
  persistence review. Validation: 42 gateway/per-order service and route tests
  passed; 60 acceptance tests passed; the new
  `per_order_gateway_verification_binding` manifest reports 7/7 complete; the
  all-audit export remains complete; and `uv run pytest -q` passed 1,060 tests.
  Python Black/isort and `git diff --check` are part of the final workspace
  verification. The frontend is unchanged from the preceding green checkpoint
  of 40 files / 405 tests, Prettier check, and production build. Risk impact:
  GitNexus reports LOW for `PerOrderConfirmationService` (3 direct dependants)
  and LOW for the acceptance export (3 direct consumers, including Operations);
  new Stage 2.4/2.5 symbols are not yet indexed. A clear verification removes
  only the runtime-verification blocker. Runtime authority, live gateway,
  broker submission, strategy-direct execution, OMS/ledger mutation, budget
  reservation, resume, and capital scale-up remain disabled. The HIGH OMS and
  CRITICAL existing broker-gateway services are unchanged.
- 2026-07-11: Stage 2.4 adds an isolated, non-submitting runtime execution-
  gateway verifier. It resolves a distinct gateway from the optional runtime
  registry, verifies its evidence-connector/account binding, requires complete
  submit/cancel/order-query/fill-query/dry-run/idempotent-client-order-id
  capabilities, and binds a healthy source-fingerprinted snapshot no more than
  60 seconds old. Verification derives a deterministic client order id and
  accepts only an exact limit-order dry-run that returns the same order/client
  ids, a valid payload fingerprint, `submitted=false`, no broker order id, and
  zero reported side effects. Preview is side-effect free with respect to
  Karkinos state; accepted and rejected records are append-only and sequentially
  reusable; resolution reruns all source checks and expires after five minutes.
  Production registers no execution gateway by default. Assumptions: the
  gateway implementation is trusted to honor and truthfully report its dry-run
  contract—Karkinos cannot cryptographically prove that a vendor adapter had no
  external side effect; real broker sandbox/vendor validation remains required;
  only limit orders are eligible in this slice; concurrent duplicate database
  uniqueness remains a future persistence review. Validation: the focused
  verifier/route/server/bootstrap/acceptance group passed 287 tests; the new
  acceptance manifest reports 8/8 complete; the all-audit export remains
  complete; and `.venv/bin/pytest -q` passed 1,048 tests. The frontend was
  unchanged from the preceding green checkpoint of 40 files / 405 tests,
  Prettier check, and production build. Risk impact: all verifier and route
  symbols are new and absent from the current GitNexus index; registering the
  route touches HIGH-risk `create_app` (16 upstream, 15 direct dependants) but
  changes no lifespan behavior. A clear record is readiness evidence only: it
  does not issue/consume authority, reserve budget, mutate OMS/ledger, call
  submit/cancel, resume execution, or scale capital. The CRITICAL existing
  `BrokerGatewayService` and HIGH OMS service remain unchanged.
- 2026-07-11: Capital-authorization v2 removes a structural gate conflict by
  separating the read-only evidence connector from the future controlled
  execution gateway. Policy scope now carries non-overlapping
  `evidence_connector_ids` and `execution_gateway_ids`; context names one of
  each, supplies independent health/capability facts, and requires a verified
  same-account binding. Identical role ids, overlapping policy sets, an
  unhealthy connector/gateway, submit capability on the read-only connector,
  missing submit capability on the execution gateway, or an unverified account
  relationship fails closed. Legacy `connector_id(s)`, health, and submit fields
  remain serialized for compatibility but are no longer authority-bearing.
  Per-order dossiers and session envelopes now read soak only from the evidence
  connector and bind the distinct execution gateway through a shared sanitized
  contract. Even a declared healthy submit-capable gateway remains
  `runtime_unverified`; the binding always retains a hard blocker and cannot
  contact a broker, submit, or issue authority. Assumptions: the v2 same-account
  status and gateway facts are still evaluation inputs, not runtime-verified
  broker facts; old v1 evaluation records lack the new identities and therefore
  fail closed until explicitly re-evaluated; an independent runtime gateway
  verifier is a later reviewed slice. Validation: the focused capital/per-order/
  session/route/acceptance group passed 113 tests; the Stage 0 acceptance
  manifest reports 8/8 complete; the all-audit export remains complete; and
  `.venv/bin/pytest -q` passed 1,035 tests. The frontend was unchanged from the
  preceding green checkpoint of 40 files / 405 tests, Prettier check, and
  production build. Risk impact: GitNexus reports HIGH for
  `CapitalAuthorizationContext` (64 upstream, 11 direct),
  `CapitalAuthorizationPolicy` (58 upstream, 12 direct), the evaluator (21
  upstream, 10 direct), and `ControlledSessionEnvelopeService` (46 upstream, 6
  direct); `PerOrderConfirmationService` remains MEDIUM (42 upstream, 9 direct).
  The change makes an impossible dual-role connector gate structurally valid
  without enabling execution. Runtime authority, live gateway verification,
  broker submission, OMS/ledger mutation, budget reservation, resume, and
  automatic scale-up remain disabled; the CRITICAL broker gateway and HIGH OMS
  services are unchanged.
- 2026-07-11: Stage 2 now resolves the current signed Stage 1.1 broker-soak
  promotion evidence for the exact connector named by the recorded capital
  evaluation. The per-order dossier binds the promotion dossier fingerprint,
  operational source fingerprint, Account Truth source fingerprint, and
  verified owner-acceptance id. The binding independently validates connector
  identity, exactly 20 selected trading days, clear operational and Account
  Truth states, verified owner identity, required readiness/linkage flags, and
  zero-authority boundaries instead of trusting `promotion_ready` alone.
  Missing, malformed, mismatched, or failed providers fail closed with sanitized
  blockers; source drift changes the per-order dossier fingerprint and makes the
  previous artifact-bound operator approval unusable. Assumptions: application
  routes resolve promotion evidence from the same startup state/config and
  database as the per-order service; a valid promotion may clear only the Stage
  1 Account Truth-linkage, owner-acceptance, and promotion sub-blockers; the
  legacy operational-soak check remains independent; Stage 3 session binding is
  deferred because its service is a separate HIGH-impact slice. Validation:
  per-order service/route tests passed 21 tests, the focused confirmation/
  acceptance group passed 77 tests, the per-order acceptance manifest reports
  9/9 complete, the all-audit export remains complete, and
  `.venv/bin/pytest -q` passed 1,027 tests. The frontend was unchanged from the
  preceding green checkpoint of 40 files / 405 tests, Prettier check, and
  production build. Risk impact: `PerOrderConfirmationService` is MEDIUM risk
  (42 upstream, 9 direct dependants, one read-only status process), while its
  soak-summary and status methods are LOW risk. This slice still cannot mutate
  OMS/ledger, contact a broker, reserve budget, issue runtime/capital authority,
  submit/cancel, resume, or scale capital. Connector submit capability, runtime
  authority, live gateway, and broker submission remain hard blockers; the
  HIGH-impact `ControlledSessionEnvelopeService`, HIGH OMS service, and CRITICAL
  gateway service are unchanged.
- 2026-07-11: Stage 1.1 adds a separate, signed broker-soak promotion-evidence
  review without changing the existing Stage 1 status or Stage 2 execution
  blocker. A deterministic dossier binds exactly the first 20 unique healthy
  read-only trading days with clear zero-open-item reconciliation, stable
  sanitized account alias/hash, daily startup/intraday/end-of-day evidence, all
  five persisted recovery drills, the latest healthy observation, and a
  source-sensitive current Account Truth fact. Account Truth is rebuilt from
  the latest persisted import, current ledger projection, reconciliation items,
  manual reviews, and score; it must be pass, no more than 24 hours old, and
  have zero unresolved items. Owner acceptance requires a short-lived Ed25519
  approval for the exact dossier and signed assertions that the import belongs
  to the same reviewed account and that full process/broker-terminal restart
  recovery was performed outside the service. Accepted and rejected attempts
  are append-only; exact reruns reuse evidence and source drift invalidates the
  prior acceptance. Assumptions: selection remains the first 20 qualifying days
  for deterministic stability; drill coverage is repository-wide in the
  current single-owner deployment; the account-alias relationship and full
  external restart are owner assertions because no credentialed broker identity
  or process supervisor is available to this service. Validation: the focused
  Account Truth/promotion/signature/route/acceptance group passed 83 tests;
  `broker_connector_soak_promotion` reports 8/8 complete; the all-audit export
  remains complete; and `.venv/bin/pytest -q` passed 1,023 tests. The frontend
  was unchanged from the preceding green checkpoint of 40 files / 405 tests,
  Prettier check, and production build. Risk impact: this is an isolated
  evidence-readiness service and API. It does not mutate OMS or the production
  ledger, reserve budget, contact a gateway or broker, submit/cancel orders,
  issue runtime/capital authority, or automatically promote into Stage 2. The
  HIGH-impact existing `BrokerConnectorSoakService`, HIGH OMS service, and
  CRITICAL gateway service remain unchanged; GitNexus classified the edited
  existing Account Truth helper area as LOW risk, while the new promotion
  symbols were not yet present in the index.
- 2026-07-10: Stage 2.2/3.2 adds signed operator approval evidence without
  execution authority. Trusted identity config accepts only enabled Ed25519
  public keys and rejects malformed, duplicate, unsupported, private-key, or
  secret-bearing entries. A short-lived canonical challenge binds server nonce,
  operator/key, action, artifact type, exact artifact fingerprint, issued time,
  and expiry; verification uses the maintained `cryptography` library and
  appends verified or rejected evidence. Expired, invalid, disabled/rotated-key,
  and cross-artifact approvals fail closed. Per-order confirmations and
  controlled-session attestations now require the matching verified approval id
  and operator label, but the record still cannot mutate OMS/ledger, reserve
  budget, issue/resume authority, contact a gateway, or submit/cancel an order.
  Assumptions: operator private keys and signing UX remain outside Karkinos;
  trusted public keys are provisioned locally; the challenge TTL is 30–300
  seconds; signed evidence authenticates an attestation only and is never a
  capital or runtime authorization. Validation: the combined operator/config/
  per-order/session/route/acceptance group passed 137 focused tests; the signed
  approval manifest reports 8/8 complete and the full acceptance export is
  complete; `uv run pytest -q` passed 1,013 tests. The unchanged frontend passed
  40 files / 405 tests, Prettier check, and production build. A pre-existing
  Stage 4 evidence-window fixture was also made wall-clock independent after an
  Asia/Shanghai midnight rollover exposed its nondeterministic OMS creation
  time; its 9 tests and the full suite are green. Risk impact: removes the
  unauthenticated-label blocker from recorded Stage 2/3 evidence only. Stage 1
  promotion, Account Truth/owner acceptance, submit capability, runtime
  authority, atomic budget, automatic pause, live gateway, and broker
  submission remain disabled. GitNexus reports HIGH impact for
  `ControlledSessionEnvelopeService`, MEDIUM for
  `PerOrderConfirmationService`/`ServerConfig`, and LOW for acceptance wiring;
  the CRITICAL gateway and HIGH OMS services are unchanged.
- 2026-07-10: Stage 2.1/3.1 adds exact prior-batch reconciliation evidence.
  A manifest binds at most 100 unique non-paper terminal OMS orders to one
  explicit reconciliation run. Every order requires exactly one `no_action`
  item whose stored OMS status still matches; filled orders additionally
  require exact real-fill quantity and provider, broker-order, Account Truth
  import, and same-run reconciliation linkage. Order, transition, fill, item,
  and run facts participate in a deterministic fingerprint; source drift
  invalidates a recorded gate. Per-order dossiers and session envelopes now
  require the request and recorded capital evaluation to reference the same
  resolved clear batch fingerprint instead of reading the latest run. Exact
  clear/blocked records are append-only and stale record attempts are audited.
  Assumptions at that slice: only `no_action` items are clear; manual mismatch
  acceptance and authenticated identity remained unimplemented; a
  reconciliation run may cover unrelated orders, while only the selected exact
  batch is evaluated.
  Validation: focused batch, reconciliation-route, per-order, session, and
  acceptance tests passed 91 tests; the dedicated acceptance manifest is 8/8
  complete; and `uv run pytest -q` passed 994 tests. The unchanged frontend
  remains green at 40 files / 405 tests, Prettier check, and production build.
  Risk impact: this removes one ambiguous evidence shortcut and tightens both
  proposal paths. It does not mutate OMS/ledger, reserve budget, contact a
  broker, submit/cancel an order, or issue/expand runtime authority. GitNexus
  reports HIGH impact for `ExecutionBatchReconciliationService` (60 upstream,
  17 direct, one read-only status process) and
  `ControlledSessionEnvelopeService` (46 upstream, 6 direct, no execution
  flow), MEDIUM for `PerOrderConfirmationService` (42 upstream, 9 direct), and
  LOW for the acceptance registry. The CRITICAL gateway service and HIGH OMS
  service remain unchanged.
- 2026-07-10: Stage 4.3 adds a computed `operating_sample` fact to the
  append-only scaling evidence window. Reviewed trading days come from healthy
  read-only connector-soak observations. Non-paper OMS orders retain distinct
  filled, rejected, partially filled, cancelled, expired, and nonterminal
  outcomes; a filled count requires linked real fill quantity. The latest
  reconciliation run must cover every sampled order, and p95 latency runs from
  the latest persisted order/fill/transition fact to the first `no_action`
  reconciliation item. Paper/shadow divergence comes from persisted comparison
  orders, and maximum drawdown uses cash-flow-unitized portfolio equity. The
  resolver now requires `operating_sample:<window_id>` and compares nine review
  metrics exactly. Assumptions: naive legacy timestamps are Asia/Shanghai;
  reviewed days mean healthy soak days; broker rejection is only the effective
  terminal OMS `rejected` state; cancelled/expired remain separate; and current
  reconciliation is order-covered rather than runtime-session/broker-batch
  bound. Cash flows between portfolio snapshots are unitized at the next
  persisted equity point because no valuation exists at the exact flow time.
  Validation: `uv run pytest tests/test_capital_scaling_evidence_window.py tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py -q`
  (26 passed); the Stage 4, route, and acceptance group passed 84 tests;
  `uv run python scripts/export_acceptance_audit.py --audit capital_scaling_operating_sample`
  reports 9/9 complete; the all-audit export reports
  `overall_is_complete=true`; and `uv run pytest -q` passed 985 tests. The
  unchanged frontend also passed 40 files / 405 tests, Prettier check, and the
  production build. Risk impact: this is read-only, fail-closed evidence
  aggregation. It does not mutate Account Truth, OMS, runtime limits,
  production ledger, gateway, or broker state; it cannot issue or expand
  authority, and it cannot submit/cancel an order. GitNexus reports MEDIUM
  impact for `CapitalScalingEvidenceWindowService` (3 direct upstream callers,
  no execution flow), LOW for the resolver, and LOW for the acceptance
  registry; `BrokerGatewayService` and `OmsService` remain unchanged.
- 2026-07-10: Stage 4.2 adds read-only computed scaling evidence windows and
  makes Account Truth an explicit required scaling source. A sanitized Account
  Truth point snapshot is clear only for pass/fresh/zero-unresolved evidence
  captured within 15 minutes of its broker import; a review window requires two
  distinct clear boundary snapshots. After-cost return is computed with
  Modified Dietz from persisted total-equity snapshots and external cash flows.
  Incident metrics scan critical alerts, rejected live submit/cancel attempts,
  and connector disconnect observations. Capacity, liquidity, and slippage use
  only non-simulated fills carrying broker/provider/order, Account Truth,
  execution-reconciliation, capacity-model, and market-data references. Window
  input accepts only timestamps and boundary tolerance; missing coverage creates
  blocked evidence. The resolver verifies schema, window, per-fact fingerprint,
  status, metric equality, and fill coverage before preserving scale-up
  eligibility. Any source scan reaching its 5,000-row cap is treated as
  truncated and blocked. Assumptions: naive legacy database timestamps are interpreted as
  Asia/Shanghai; boundary tolerance defaults to 72 hours for market closures;
  total equity is after recorded costs; Modified Dietz is account-level rather
  than strategy attribution; monetary slippage is divided by fill notional; and
  maximum utilization is retained instead of averaging stress away. Validation:
  `uv run pytest tests/test_capital_scaling_evidence_window.py tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py tests/server/test_capital_scaling_review_routes.py -q`
  plus acceptance tests (79 passed),
  `uv run python scripts/export_acceptance_audit.py --audit capital_scaling_evidence_window`
  (9/9 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), and `uv run pytest -q` (980 passed). Frontend
  verification remains 40 files / 405 tests with format and production build
  passing; Black, isort, and `git diff --check` also pass. Risk impact: this adds sanitized append-only evidence only. It
  does not mutate Account Truth, OMS, runtime limits, production ledger, gateway,
  or broker state; even a fully resolved result records only a separate new-
  authorization request. GitNexus reports LOW impact for the scaling evaluator
  (2 direct callers), resolver (6 upstream, 2 direct), and audit service (29
  upstream, 2 direct); the capital-scaling route symbols were not index-
  addressable after two qualified impact attempts, so their direct app/test
  scope was reviewed manually. BrokerGatewayService and OmsService are unchanged.
- 2026-07-10: Stage 4.1 adds fail-closed persisted evidence-reference
  resolution ahead of any scale-up decision. Broker-soak observations,
  execution-reconciliation runs, paper/shadow runs, and risk decisions are
  looked up by typed identifiers, checked for review-window membership and
  clear state, and reduced to sanitized source fingerprints. The review-input
  fingerprint and resolution fingerprint now form a separate evaluation
  identity, so a changed source cannot reuse a prior append-only evaluation or
  human decision. Missing, invalid, out-of-window, or non-clear sources add
  typed blockers; a mathematically eligible scale-up result becomes hold, while
  protective scale-down/disable analysis remains visible. Assumptions: the four
  supported source types prove reference existence and clear-state provenance,
  but do not yet independently recompute every caller-declared aggregate metric;
  after-cost, incident-window, and capacity/liquidity authoritative aggregate
  producers do not exist and therefore remain explicit unsupported blockers;
  operator identity remains unauthenticated. Validation:
  `uv run pytest tests/test_capital_scaling_evidence_resolution.py tests/test_capital_scaling_review.py tests/server/test_capital_scaling_review_routes.py -q`
  plus the acceptance-audit tests (66 passed), and
  `uv run python scripts/export_acceptance_audit.py --audit capital_scaling_evidence_resolution`
  (6/6 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), and `uv run pytest -q` (967 passed), with Black,
  isort, and `git diff --check` on the changed files. The frontend was unchanged
  after its current 40-file / 405-test, format, and production-build pass. Risk
  impact: this tightens scale-up eligibility only. It performs no Account Truth,
  OMS, production-ledger, runtime-limit, gateway, or broker mutation; it issues
  no authorization and keeps automatic scale-up and broker submission disabled.
  GitNexus reports LOW impact for `CapitalScalingReviewAuditService` (29 upstream,
  2 direct route dependencies, no affected execution flow) and LOW for
  `AUDIT_REGISTRY`.
- 2026-07-10: Stage 4 started with a pure evidence-based capital-scaling review
  and append-only evaluation/human-decision workflow. Versioned current/proposed
  tiers are compared with reviewed trading days, orders/fills/rejects,
  reconciliation gaps/latency, slippage, after-cost result, drawdown,
  capacity/liquidity, paper/shadow divergence, disconnects, violations, and
  incidents. At least 20 reviewed trading days, 50 orders, required typed refs,
  and all quality thresholds are needed for a scale-up candidate; invalid or
  insufficient evidence holds, degraded quality recommends scale-down, and
  critical incidents, violations, unresolved reconciliation, or exhausted
  drawdown recommends disable. Human decisions bind the persisted evaluation
  fingerprint and may choose a safer action, but cannot exceed the evidence
  recommendation. Assumptions: thresholds are versioned engineering defaults,
  not investment advice or a profit guarantee; positive after-cost evidence is
  only one gate; current metric values remain declared local review inputs while
  Stage 4.1 resolves four source types and blocks the three aggregate types that
  lack authoritative producers; operator labels remain unauthenticated; and sequential duplicate events
  reuse evidence while concurrent database uniqueness remains a residual
  limitation. Even an eligible decision records only a request for a separate
  new authorization review. Validation:
  `uv run pytest tests/test_capital_scaling_review.py tests/server/test_capital_scaling_review_routes.py tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py -q`
  (60 passed) and
  `uv run python scripts/export_acceptance_audit.py --audit capital_scaling_review_foundation`
  (8/8 complete), plus Black and isort checks for the changed Python files.
  Risk impact: automatic scale-up, new authorization issuance, active-tier or
  runtime-limit mutation, execution resume, OMS/ledger mutation, and broker
  submit/cancel remain unavailable. Protective outcomes are recommendations in
  this slice, not silent runtime mutations. GitNexus impact remains MEDIUM for
  `create_app` registration and LOW for `AUDIT_REGISTRY`; gateway, OMS, capital
  evaluator, and connector runtime behavior are unchanged.
- 2026-07-10: Stage 3 started with a proposal-only controlled-session envelope
  service. It consumes one recorded `session_bounded` capital evaluation, an
  explicit OMS order set, and a timezone-aware window of at most 30 minutes;
  canonical order/gateway evidence and conservative gross order value are bound
  to cash, capital, turnover, per-order, position-change, liquidity, and
  projected rate budgets. Missing/duplicate/unpriced/out-of-scope orders,
  unsupported OMS state, stale soak, missing/open reconciliation, kill switch,
  invalid time, or budget excess fails closed. Exact fresh-envelope attestations
  reuse append-only evidence; stale fingerprints and blocked envelopes record
  deterministic rejections. Assumptions: only priced limit orders can be
  projected; buy and sell values are not netted; the recorded capital context
  supplies review-time cash/exposure/turnover facts but is not runtime authority;
  a 60-second start-time grace allows a human to attest an immediate preview;
  the continuously changing age counter is excluded from the fingerprint while
  source time, max age, and freshness state remain bound; per-symbol runtime
  limits and prior-batch reconciliation are not yet bound. Stage 1/2 promotion,
  session-start Account Truth, authenticated identity, connector submit
  capability, atomic budget reservation, runtime rate limiting, automatic pause,
  runtime session issue/resume/revoke, live gateway, and broker submission remain
  hard blockers. Validation:
  `uv run pytest tests/test_controlled_session_envelope.py tests/server/test_controlled_session_envelope_routes.py tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py -q`
  (56 passed) and
  `uv run python scripts/export_acceptance_audit.py --audit controlled_session_envelope_foundation`
  (8/8 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), and `uv run pytest -q` (943 passed), plus Black,
  isort, and `git diff --check` for the changed files. The frontend was not
  changed after its latest 40-file / 405-test, format, and production-build pass.
  Risk impact: this slice performs deterministic local projection and append-only
  attestation audit only. It does not reserve/consume budget, issue/enable/pause/
  resume/revoke a runtime session, mutate OMS/ledger, contact a broker,
  submit/cancel an order, auto-renew/expand, or scale capital. GitNexus reports
  MEDIUM impact for the `create_app` route registration (10 affected, 9 direct)
  and LOW for `AUDIT_REGISTRY`; the CRITICAL gateway and HIGH-risk OMS remain
  unchanged.
- 2026-07-10: Stage 2 started with an isolated, non-submitting per-order dossier
  and attestation service. It fingerprints canonical OMS order terms and binds
  the recorded capital-evaluation decision, Account Truth/research/risk/
  paper-shadow gateway evidence, latest connector-soak state, latest execution
  reconciliation, and kill-switch snapshot. Missing, stale, mismatched, blocked,
  unhealthy, or unavailable review evidence fails closed. An exact dossier can
  be attested only after review gates pass; repeated identical attempts reuse an
  append-only event, while stale fingerprints and blocked dossiers produce
  deterministic rejection evidence. Assumptions: a capital evaluation is policy
  calculation evidence rather than runtime authority; the current operator
  label is unauthenticated local input; the latest clear reconciliation is
  review evidence but is not yet bound to a specific prior account/strategy/
  batch; and a local attestation may be recorded while immutable submission
  blockers remain because it cannot authorize execution. Stage 1 promotion,
  Account Truth linkage, owner acceptance, batch-bound reconciliation,
  authenticated identity, actual connector submit capability, runtime
  authority, live gateway implementation, and broker submission remain explicit
  hard blockers. Validation:
  `uv run pytest tests/test_per_order_confirmation.py tests/server/test_per_order_confirmation_routes.py tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py -q`
  (55 passed) and
  `uv run python scripts/export_acceptance_audit.py --audit per_order_confirmation_foundation`
  (7/7 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), `uv run pytest -q` (926 passed),
  `npm --prefix web test -- --run` (40 files / 405 tests),
  `npm --prefix web run format:check`, `npm --prefix web run build`, plus Black,
  isort, and `git diff --check` for the changed files.
  Risk impact: the new path reads local persisted facts and connector capability
  metadata only. It never calls `BrokerGatewayService`, reads a broker snapshot,
  changes OMS, mutates the production ledger, submits/cancels an order, resumes
  automation, or grants/scales capital authority. GitNexus reports MEDIUM impact
  for `create_app` (10 affected, 9 direct); the CRITICAL
  `BrokerGatewayService` (90 affected, 41 direct) and HIGH-risk `OmsService`
  (57 affected, 19 direct) were explicitly not modified.
- 2026-07-10: Stage 1 added a broker-neutral operating runbook service and
  append-only `startup`, `intraday`, and `end_of_day` evidence. Missing or
  unhealthy connector observations block every phase; end-of-day additionally
  requires the same-day execution reconciliation to be `clear` with zero open
  items. Disconnect, unsupported-schema, stale-data, duplicate-evidence, and
  service-instance restart-recovery drills now persist deterministic pass/fail
  evidence, reuse identical sequential inputs, and send failed/blocked results
  to the shared Operations alert queue. Run/drill APIs reject undeclared fields
  and credentials, and the operator procedure is documented in
  `docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md`. Assumptions: the operator prepares
  disposable local-export failure conditions without changing broker settings;
  end-of-day reconciliation evidence already exists for the snapshot trading
  day; service-instance reconstruction proves persistence-independent replay
  but does not prove a full operating-system or broker-terminal restart; and
  concurrent event uniqueness remains a residual persistence limitation.
  Validation:
  `uv run pytest tests/test_broker_connector_soak.py tests/test_broker_connector_soak_runbook.py tests/server/test_broker_connector_soak_routes.py tests/server/test_broker_connector_soak_runbook_routes.py tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py -q`
  (62 passed) and
  `uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_foundation`
  (11/11 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), and `uv run pytest -q` (909 passed), plus Black,
  isort, and `git diff --check` for the changed files.
  Risk impact: this adds only broker-read evidence, run/drill audit events, and
  sanitized alerts. It cannot contact write capabilities, submit/cancel an
  order, mutate OMS or the production ledger, or grant capital authority. A
  successful drill or 20-day operational metric cannot promote Stage 2 without
  real broker-specific evidence, Account Truth linkage, authenticated owner
  acceptance, and separate controlled-bridge review.
- 2026-07-10: Stage 1 started with a broker-neutral, read-only soak service and
  status/capture/list APIs. Configured `qmt_readonly_export`,
  `ptrade_readonly_export`, generic local exports, or injected read-only
  connectors produce sanitized snapshot evidence with deterministic snapshot
  and observation fingerprints, source/observed times, freshness, capability
  scope, cash/position/order/fill counts and facts, execution-reconciliation
  references when present, and provider market-calendar evidence. Raw account
  ids are replaced by a local opaque hash and never returned in snapshot facts;
  any submit capability blocks the observation. Missing calendar evidence,
  closed dates, stale/future/invalid timestamps, incomplete read capabilities,
  missing cash, degraded source health, or connector exceptions do not count as
  healthy soak days and create sanitized shared Operations alerts. Assumptions:
  QMT/PTrade integration remains a user-managed local JSON export, not direct
  SDK access; provider calendar snapshots identify trading days; account-id
  hashes are local correlation evidence, not public identifiers; sequential
  duplicate capture reuses an observation while concurrent uniqueness remains
  a residual persistence limitation. Validation:
  `uv run pytest tests/test_broker_connector_soak.py tests/server/test_broker_connector_soak_routes.py tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py -q`
  (49 passed),
  `uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_foundation`
  (6/6 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), `uv run pytest -q` (896 passed),
  `npm --prefix web test -- --run` (40 files / 405 tests),
  `npm --prefix web run format:check`, `npm --prefix web run build`, plus Black,
  isort, and `git diff --check`. Risk impact:
  starts measurable 20-trading-day read-only operations without contacting a
  broker write API, exposing raw account ids, submitting/cancelling orders,
  mutating OMS or the production ledger, or enabling capital authority. Twenty
  healthy days mark operational soak only; promotion remains blocked until
  Account Truth reconciliation and explicit owner acceptance are linked.
- 2026-07-10: Stage 0 now persists capital-authorization **evaluation
  evidence**, not execution authority, through the existing append-only event
  log. A dedicated audit service provides side-effect-free preview, sequential
  input-fingerprint reuse, evidence listing, and a status contract that remains
  `runtime_authority_status=disabled` even when the pure evaluator returns
  `allowed=true`. New status/preview/record/list routes reject undeclared
  payload fields (including attempted credential fields) and expose no issue,
  revoke, enable, resume, submit, cancel, OMS, or ledger action. Static
  `config.json` is intentionally not an authorization source; the existing
  controlled-bridge config remains whitelist preview only. Assumptions: event
  records contain local aliases, limits, fingerprints, and evidence refs but no
  broker credentials or real account identifiers; `authorized_by` is explicitly
  marked as unverified input until a future authenticated operator workflow;
  append-only event-log reuse
  is deterministic for sequential identical requests; concurrent duplicates
  remain a residual limitation until a dedicated unique persistence contract is
  reviewed. Validation:
  `uv run pytest tests/test_capital_authorization.py tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q`
  (22 passed),
  `uv run pytest tests/test_acceptance_audit.py tests/test_acceptance_audit_cli.py tests/test_capital_authorization.py tests/test_capital_authorization_audit.py tests/server/test_capital_authorization_routes.py -q`
  (58 passed),
  `uv run python scripts/export_acceptance_audit.py --audit capital_authorization_policy`
  (6/6 complete), `uv run python scripts/export_acceptance_audit.py --audit all`
  (`overall_is_complete=true`), `uv run pytest -q` (883 passed), plus Black and
  isort checks for the changed Python files.
  Risk impact: makes proposed authority limits and gate outcomes durable and
  reviewable without activating them. GitNexus reports LOW impact for
  `create_app` (2 upstream dependents) and `AUDIT_REGISTRY` (0); the MEDIUM-risk
  `ControlledBridgePolicyConfig` and HIGH-risk `BrokerGatewayService` were not
  modified. This slice cannot contact a broker, submit or cancel orders, resume
  automation, mutate OMS or the production ledger, or expand capital authority.
- 2026-07-10: Stage 0 started with an isolated, versioned
  `karkinos.capital_authorization.v1` policy contract and pure fail-closed
  evaluator. It distinguishes account capital from authorized total exposure
  and per-order purchasing/liquidity capacity; supports `disabled`,
  `manual_each_order`, and future `session_bounded` policy modes; checks
  explicit operator identity, policy version, connector/account/strategy/symbol
  scope, timezone-aware validity and expiry, matching per-order confirmation,
  market/account/risk/paper-shadow/reconciliation/connector/kill-switch gates,
  capital/order/position/turnover/loss/drawdown/order-rate/error limits; and
  returns deterministic fingerprints, block reasons, effective limits,
  remaining budgets, evidence refs, and explicit no-submit/no-cancel/no-OMS/
  no-ledger/no-self-expansion safety flags. Assumptions: the caller supplies
  already sourced current facts; daily loss is a non-negative loss magnitude;
  current authorized exposure represents existing exposure inside this
  authorization domain; Decimal amounts retain the caller's currency; and
  connector submit capability is evaluated as evidence only. This slice does
  not fetch, persist, authorize, or execute anything. Validation:
  `uv run pytest tests/test_capital_authorization.py -q` (15 passed),
  `uv run pytest tests/test_capital_authorization.py tests/test_automation_control.py tests/test_broker_gateway_service.py -q`
  (45 passed),
  `uv run black --check server/services/capital_authorization.py tests/test_capital_authorization.py`,
  and
  `uv run isort --check-only server/services/capital_authorization.py tests/test_capital_authorization.py`.
  Risk impact: establishes the non-submitting authority contract without
  changing configuration, routes, gateway, OMS, database, ledger, or strategy
  promotion behavior. GitNexus reported MEDIUM impact for the existing
  `ControlledBridgePolicyConfig` (28 upstream dependents) and HIGH impact for
  `BrokerGatewayService` (38 dependents across gateway status, Automation
  Cockpit, and alerts); neither existing symbol was modified or integrated in
  this slice. Broker submission, cancellation, automatic resume, automatic
  scale-up, and strategy-direct broker access remain unavailable.

## v1.7 Progress

- 2026-07-10: v1.6/v1.6.1 and the v1.7 non-submitting bridge foundation were
  closed against their acceptance evidence. Execution reconciliation now
  compares a recorded manual execution with already matching staged broker
  facts across quantity, price, gross amount, fee, tax, transfer fee, and net
  amount. A difference becomes a structured `broker_evidence_mismatch` review
  item with `karkinos.manual_broker_comparison.v1` evidence; a match still
  requires operator review before any ledger action. Trading manual-ticket
  export now links directly to Account Truth broker-statement import and the
  read-only reconciliation review surface. The controlled-bridge acceptance
  audit adds an end-to-end criterion covering manual confirmation -> ticket ->
  manual execution evidence -> staged broker evidence -> reconciliation.
  Decision renders the compared manual and broker values plus non-mutation
  safety flags without sync, apply-fill, cancel, or submit controls.
  Assumption: this comparison runs only after the existing broker matcher has
  identified same-side, same-symbol, same-quantity evidence; aggregation of
  multiple broker partial fills remains an explicit future limitation because
  its matcher has a HIGH GitNexus blast radius and was not changed here.
  Validation: `uv run pytest -q` (859 passed), `npm --prefix web test` (405
  passed), `npm --prefix web run build`, `npm --prefix web run format:check`,
  and `uv run python scripts/export_acceptance_audit.py --audit all`
  (`operations_runbook` 19/19 and `controlled_broker_bridge_foundation` 15/15,
  both complete). Risk impact: closes a false-clear reconciliation gap and
  improves the operator import/review handoff while keeping manual
  confirmation, gateway evidence, kill switch, Account Truth, research, risk,
  paper/shadow, connector health, and reconciliation gates intact. It does not
  aggregate partial fills, contact a broker, store credentials, submit or
  cancel broker orders, change OMS during comparison, create live fills, write
  production ledger entries, alter cash or positions, enable v1.8, or enable
  automatic trading.
- 2026-07-10: Production trade ledger entries can now receive an explicit,
  idempotent broker-settlement confirmation through
  `POST /api/ledger/trades/{entry_id}/settlement`. The confirmation preserves
  the first estimated commission, fee breakdown, net cash impact, and fee-rule
  metadata; promotes broker-confirmed values to the effective trade fields;
  and appends a `portfolio.trade_settlement.confirmed` audit event with the
  cash adjustment. Assumption: the operator supplies per-trade settlement
  evidence from a broker trade detail or contract note, not a rounded account
  summary. Validation covers persistence, idempotency, API consistency checks,
  projection cash, and Account Truth reconciliation of per-component rounding.
  Risk impact: confirmed broker values can remove deterministic rounding
  mismatches without broad tolerances or silent history loss; imported broker
  evidence remains read-only until this explicit endpoint is called, and the
  flow does not contact brokers, submit orders, enable automatic trading, or
  bypass manual confirmation.
- 2026-07-10: Account Truth position and broker cost-basis reconciliation now
  scopes explicit `position_snapshot` evidence to the asset classes covered by
  that snapshot. A stock-only broker snapshot therefore reconciles stock
  positions without treating fund positions from another platform as missing;
  uncovered asset classes remain a localized warning that requires separate
  evidence. Legacy callers that do not provide a Karkinos position asset class
  retain the prior full-portfolio comparison behavior. Assumption: a non-empty
  broker snapshot `asset_class` defines the evidence coverage boundary, while
  an empty asset class remains unscoped for backward compatibility. Validation:
  `uv run pytest tests/account_truth/test_reconciliation.py tests/server/test_account_truth_gate.py tests/server/test_account_truth_routes.py tests/account_truth/test_account_truth_score.py -q`
  and `npm --prefix web test -- public-labels.test.ts`. Risk impact: prevents
  cross-platform false position mismatches while keeping uncovered holdings
  degraded for review; it does not accept missing evidence, mutate the
  production ledger, change cash or positions, contact brokers, submit orders,
  enable automatic trading, or bypass manual confirmation.
- 2026-07-08: Execution reconciliation staged-broker trade cost summaries now
  explicitly carry a ledger-review contract:
  `requires_reconciliation_before_ledger_update=true`,
  `ledger_update_status=review_required`,
  `suggested_ledger_action=review_staged_broker_evidence`, and
  `does_not_recommend_automatic_ledger_update=true`. Matching and mismatched
  staged broker trade evidence therefore remain review inputs before any
  ledger action is suggested. Assumption: imported broker trade evidence is
  staged reconciliation evidence only; it is not a live fill command, broker
  response, or production ledger mutation by itself. Validation:
  `uv run python -m pytest tests/test_execution_reconciliation_service.py::test_reconciliation_marks_manual_ticket_with_matching_broker_evidence_available tests/test_execution_reconciliation_service.py::test_reconciliation_flags_broker_evidence_quantity_mismatch -q`.
  Risk impact: improves v1.7 reconciliation-before-ledger-update auditability
  without contacting brokers, storing credentials, changing OMS status,
  submitting or cancelling broker orders, creating live fills, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-08: Manual-ticket creation now returns the same
  `validation.required_gate_summary` as the preview/export/dry-run contract and
  writes that gate summary into the `manual_ticket_created` broker-gateway
  audit event after the OMS status changes to `manual_ticket_created`. The
  summary preserves account-truth, research-evidence, risk, paper/shadow,
  manual-confirmation, kill-switch, connector-health, and execution-
  reconciliation evidence while keeping `submitted_to_broker=false` and
  `does_not_authorize_execution=true`. Assumption: this is creation-time audit
  continuity for human-entered broker tickets, not live broker authority.
  Validation:
  `uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_gateway_creates_ticket_without_broker_submission tests/server/test_broker_gateway_routes.py::test_manual_ticket_route_returns_copyable_ticket -q`.
  Risk impact: improves v1.7 manual-ticket auditability without contacting
  brokers, storing credentials, creating fills, writing production ledger
  facts, submitting or cancelling broker orders, enabling automatic trading, or
  bypassing manual confirmation.
- 2026-07-08: Manual-ticket preview, export, and dry-run responses now include
  a controlled-bridge gate summary before any operator copies a broker ticket.
  The summary records account-truth, research-evidence, risk, paper/shadow,
  manual-confirmation, kill-switch, connector-health, and execution-
  reconciliation gates, their evidence refs, and the explicit
  `does_not_authorize_execution` safety boundary. Trading approvals renders
  the same gate summary immediately after manual-ticket export, before the
  later manual-execution preview, so the operator can review live-like
  prerequisites before broker-side manual entry. Assumption: manual-ticket
  gate summaries are read-only audit evidence for human broker entry; they do
  not authorize live broker submission, auto-pilot execution, or production
  ledger writes. Validation:
  `uv run python -m pytest tests/test_broker_gateway_service.py::test_manual_ticket_preview_is_dry_run_and_does_not_mutate_oms tests/test_broker_gateway_service.py::test_manual_ticket_export_is_read_only_and_copy_safe tests/test_broker_gateway_service.py::test_manual_ticket_dry_run_records_accepted_event_without_oms_mutation -q`,
  `uv run python -m pytest tests/server/test_broker_gateway_routes.py::test_manual_ticket_preview_route_is_read_only -q`,
  and
  `npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"`.
  Risk impact: advances the v1.7 controlled bridge evidence gate without
  enabling broker submission, adding broker credentials, contacting brokers,
  changing OMS status during preview/export/dry-run, creating live fills,
  writing production ledger facts, enabling automatic trading, or bypassing
  manual confirmation.

## v1.6.1 Progress

- 2026-07-08: Filled and non-failed paper/shadow order and fill fact payloads
  now carry local audit refs. Order-level `evidence_refs` include the source
  action, strategy/risk/signal refs, `paper_order` ref, and OMS transition
  refs. Fill metadata now carries `order_intent_ref` plus `evidence_refs`
  linking the same source action, strategy/risk/signal refs, `paper_order` ref,
  and `paper_fill` ref. This makes normal simulated order and fill facts
  auditable with the same local evidence chain already preserved for failed
  runs and run-level payloads. Assumption: these refs are local simulation
  audit evidence for operator review; they are not broker responses, live
  fills, or ledger mutation inputs. Validation:
  `uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_creates_simulated_order_and_fill_without_ledger_mutation -q`.
  Risk impact: improves v1.6.1 simulated order/fill audit continuity without
  changing fill simulation, contacting brokers, storing credentials, submitting
  orders, creating live fills, mutating production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-08: Operations Today fallback review queues for legacy or partial
  paper/shadow run payloads now preserve OMS status paths, transition refs,
  normalized transition evidence, terminal reasons, and order-level evidence
  refs when the persisted order payload already contains `oms_transitions` but
  lacks a full `review_queue`. Assumption: this is read-only runbook recovery
  evidence for local paper/shadow records; it does not replay OMS transitions,
  contact brokers, create fills, or authorize manual confirmation by itself.
  Validation:
  `uv run python -m pytest tests/test_operations_today.py::test_operations_today_synthesizes_oms_evidence_for_legacy_review_queue -q`.
  Risk impact: improves operator review continuity for older paper/shadow run
  records without changing simulation behavior, mutating OMS/order state,
  submitting broker orders, creating live fills, writing production ledger
  facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-08: Failed paper/shadow simulation runs now preserve the OMS
  `staged -> submitted -> rejected` transition path in the returned run
  payload, persisted run payload, and failed order fact payload. Failed
  review-queue items expose the same `oms_transition_refs` and status path, and
  run/order `evidence_refs` include the rejected transition ref so
  Operations/Decision/Trading can review the failed simulation using the same
  OMS evidence as successful, partial, cancelled, and expired outcomes.
  Assumption: these transition refs are local paper/shadow audit evidence for
  diagnosing a failed simulation before manual confirmation; they are not
  broker responses, live fills, or ledger inputs.
  Validation:
  `uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_records_failed_run_when_simulation_errors -q`.
  Risk impact: improves v1.6.1 failed-run audit continuity without changing
  paper/shadow execution semantics, contacting brokers, storing credentials,
  submitting orders, creating live fills, mutating production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-08: Failed paper/shadow automation alerts now preserve scheduler
  rerun evidence from the automation run payload and render it in the Decision
  Automation Cockpit as public operator text. The alert payload carries
  input fingerprint, idempotency/rerun key, and normalized input snapshot
  evidence; the UI shows order-intent count, source decision, fingerprint
  prefix, rerun key, retry attempt summary, manual-review requirement, and
  no-broker/no-ledger-mutation safety labels while hiding raw field names such
  as `input_snapshot` and `idempotency_key`. The operations-runbook acceptance
  audit now ties failed automation alerts to this rerun-evidence contract.
  Assumption: failed automation-run snapshots are local deterministic rerun
  evidence for paper/shadow operations only; they are not broker truth,
  execution approval, or production ledger inputs. Validation:
  `uv run python -m pytest tests/test_automation_alerts.py::test_alert_scan_records_failed_paper_shadow_automation_run -q`
  and
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "failed paper shadow automation recovery"`.
  Risk impact: improves v1.6 operator alert auditability without changing
  scheduler execution, contacting brokers, storing credentials, submitting
  orders, creating live fills, mutating OMS/order state, writing production
  ledger facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-08: Overview Today runbook scheduler-failure evidence now renders
  scheduler `input_snapshot` and idempotency evidence as public operator
  text. The failed scheduler recovery item shows normalized order-intent
  count, source decision, fingerprint prefix, rerun key, retry state, error,
  and no-broker-submission safety evidence while hiding raw field names such
  as `input_snapshot` and `idempotency_key`. The operations-runbook acceptance
  audit now ties scheduler run persistence to this Overview evidence command.
  Assumption: scheduler input snapshots and rerun keys are deterministic
  runbook review evidence for local paper/shadow automation only; they are not
  broker truth, execution approval, or production ledger inputs. Validation:
  `npm --prefix web test -- overview-page.test.tsx -t "failed scheduler run recovery"`
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook -q`.
  Risk impact: improves v1.6 scheduler rerun auditability without changing
  scheduler execution, contacting brokers, storing credentials, submitting
  orders, creating live fills, mutating OMS/order state, writing production
  ledger facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-08: Trading execution audit now renders the latest paper/shadow
  `input_snapshot` as public operator evidence alongside run status, review
  queue, terminal outcome, evidence refs, and no-broker/no-ledger-mutation
  safety flags. The Trading surface shows the normalized order-intent count,
  source decision, fingerprint prefix, and snapshot safety boundary while
  hiding the raw snapshot schema key. The operations-runbook acceptance audit
  now includes the Trading input-snapshot test command as evidence for the
  frontend paper/shadow next-action contract. Assumption: the Trading input
  snapshot is deterministic rerun/review evidence for simulated paper/shadow
  runs only; it is not broker truth, execution approval, or a production
  ledger input. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"`
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook -q`.
  Risk impact: completes the Decision/Overview/Trading operator-facing input
  snapshot loop without adding broker-submit controls, contacting brokers,
  storing credentials, mutating OMS/order state, creating live fills, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-08: Decision and Overview now render paper/shadow
  `input_snapshot` as public operator evidence. The surfaces show the
  normalized order-intent count, source decision, fingerprint prefix, and
  no-broker/no-production-ledger-mutation snapshot safety flags while hiding
  the raw snapshot schema key. The operations-runbook acceptance audit now
  records this frontend input-snapshot contract alongside paper/shadow next
  actions and review-queue evidence. Assumption: the input snapshot is a
  deterministic rerun/review aid for simulated paper/shadow runs only; it is
  not broker truth, execution approval, or a production ledger input.
  Validation:
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "paper shadow review queue"`,
  `npm --prefix web test -- overview-page.test.tsx -t "divergence evidence summary"`,
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook -q`.
  Risk impact: improves v1.6.1 operator-facing reproducibility evidence
  without adding broker-submit controls, contacting brokers, storing
  credentials, mutating OMS/order state, creating live fills, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-08: Paper/shadow run payloads now include a deterministic
  `input_snapshot` with run fingerprint, input refs, normalized order-intent
  summaries, account-truth state, account constraint summary, outcome
  overrides, and explicit no-broker / no-production-ledger-mutation safety
  flags. Operations Today also surfaces the persisted snapshot through
  `paper_shadow.input_snapshot`, giving Decision/Overview/Operations consumers
  enough evidence to verify what inputs a run used without replaying the
  trading plan. Assumption: this snapshot is audit evidence for deterministic
  paper/shadow rerun review only; it is not broker truth, execution authority,
  or a production ledger source. Validation:
  `uv run python -m pytest tests/test_paper_shadow_run_service.py::test_paper_shadow_run_creates_simulated_order_and_fill_without_ledger_mutation -q`
  and
  `uv run python -m pytest tests/test_operations_today.py::test_operations_today_prefers_persisted_paper_shadow_run -q`.
  Risk impact: improves v1.6/v1.6.1 runbook reproducibility and operator
  auditability without changing order-state transitions, contacting brokers,
  storing credentials, submitting broker orders, mutating OMS state beyond the
  existing paper/shadow simulation path, creating live fills, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-08: Trading execution audit now renders terminal paper/shadow review
  reasons alongside the latest run evidence, matching the Decision and
  Overview terminal outcome summaries. Expired or cancelled simulated
  outcomes show localized terminal status, terminal reason, formatted OMS
  transition evidence, and the existing no-broker / no-ledger-mutation safety
  boundary without exposing raw reason codes. The operations-runbook
  acceptance audit now records the Trading targeted test for this frontend
  contract. Assumption: Trading terminal outcome evidence is an operator
  review cue for simulated paper/shadow runs only; it is not a live broker
  response, broker cancellation/expiry action, execution authorization, or
  manual-confirmation approval. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "terminal paper shadow review reasons"`
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`.
  Risk impact: closes the v1.6.1 terminal-review evidence loop across
  Operations/Decision/Overview/Trading surfaces without contacting brokers,
  storing credentials, submitting or cancelling broker orders, mutating OMS
  state, creating live fills, writing production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-08: Decision and Overview paper/shadow review queues now render
  terminal simulation outcomes as public operator evidence. Cancelled and
  expired paper/shadow items show a localized terminal outcome summary with
  status, terminal reason, and formatted OMS transition evidence while hiding
  raw reason codes such as `operator_cancelled` and `paper_session_closed`.
  The operations-runbook acceptance audit now records this frontend terminal
  reason contract. Assumption: terminal outcome text is review evidence for
  simulated paper/shadow orders only; it is not a broker cancellation,
  live-order expiry, execution authorization, or manual-confirmation approval
  by itself. Validation:
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "terminal paper shadow review reasons"`,
  `npm --prefix web test -- overview-page.test.tsx -t "terminal paper shadow review reasons"`,
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`.
  Risk impact: improves v1.6.1 operator-facing Decision/Overview review
  evidence for terminal paper/shadow outcomes without contacting brokers,
  storing credentials, submitting or cancelling broker orders, mutating OMS
  state, creating live fills, writing production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-08: Paper/shadow review queue items for cancelled and expired
  simulated outcomes now expose `terminal_status`, `terminal_reason`, and
  `terminal_oms_transition_ref` directly, so Operations/Decision/Overview
  consumers can show why a terminal paper/shadow outcome needs review without
  parsing raw OMS transitions. Assumption: terminal reason evidence is
  operator-facing simulation review context only; it is not a cancellation
  request, broker response, or execution authorization. Validation:
  `uv run python -m pytest tests/test_paper_shadow_run_service.py -k cancelled_and_expired`
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`.
  Risk impact: improves v1.6.1 structured review evidence for cancel/expire
  simulations without contacting brokers, storing credentials, submitting or
  cancelling broker orders, changing OMS transition rules, creating live
  fills, writing production ledger facts, enabling automatic trading, or
  bypassing manual confirmation.
- 2026-07-07: The `operations_runbook` acceptance audit now has an explicit
  `paper_shadow_manual_handoff_gate` criterion tying the Operations Today
  `paper_shadow.manual_handoff` payload and the Decision/Overview surfaces to
  deterministic evidence and validation commands. Assumption: the handoff gate
  is operator-facing readiness evidence for manual confirmation after
  paper/shadow review; it is not execution authority and does not submit
  orders. Validation:
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`,
  `uv run python -m pytest tests/test_acceptance_audit_cli.py -k operations_runbook`,
  `uv run python -m pytest tests/test_operations_today.py -k "manual_handoff or accepted_shadow_divergence"`,
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual handoff gate"`,
  and
  `npm --prefix web test -- overview-page.test.tsx -t "accepted paper shadow review"`.
  Risk impact: improves v1.6.1 acceptance traceability only; it does not
  change runtime paper/shadow behavior, contact brokers, store credentials,
  create broker orders, mutate OMS, write production ledger facts, enable
  automatic trading, or bypass manual confirmation.
- 2026-07-07: Overview Today's to-dos now renders
  `paper_shadow.manual_handoff` as user-facing manual-confirmation handoff
  evidence, including ready/blocked status, review queue count, and explicit
  no-broker / no-ledger-mutation safety flags. Assumption: Overview handoff
  text is runbook evidence for the operator's daily queue and is not execution
  authority by itself. Validation:
  `npm --prefix web test -- overview-page.test.tsx -t "accepted paper shadow review"`.
  Risk impact: improves v1.6.1 Overview visibility for the
  paper/shadow-to-manual-confirmation gate without contacting brokers, storing
  credentials, creating broker orders, mutating OMS, writing production ledger
  facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Operations Today now exposes a structured
  `paper_shadow.manual_handoff` gate with readiness, status, blockers, required
  actions, review queue count, review metadata, and explicit no-broker /
  no-ledger-mutation safety flags. Decision Cockpit renders the gate as
  user-facing operator evidence so unresolved paper/shadow divergence blocks
  manual confirmation until accepted review, while accepted divergence or clean
  simulation hands off to manual confirmation review. Assumption: manual
  handoff readiness is runbook evidence derived from persisted paper/shadow
  status and review state; it is not execution authority by itself.
  Validation:
  `uv run python -m pytest tests/test_operations_today.py -k "manual_handoff or accepted_shadow_divergence_ready_for_handoff"`
  and
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "manual handoff gate"`.
  Risk impact: makes the paper/shadow-to-manual-confirmation gate explicit for
  v1.6.1 Operations/Decision review without contacting brokers, storing
  credentials, creating broker orders, mutating OMS, writing production ledger
  facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: CI repository hygiene now blocks tracked `reports/` artifacts in
  the same private-artifact guard that already rejects runtime databases,
  logs, exports, screenshots, local secrets, Codex/agent state, and generated
  skill locks. Assumption: generated reports are local run evidence and should
  remain outside source control even when useful for operator review.
  Validation:
  `uv run python -m pytest tests/test_ci_workflow.py -k repository_hygiene`,
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`,
  and
  `uv run python -m pytest tests/test_acceptance_audit_cli.py -k operations_runbook`.
  Risk impact: strengthens the v1.6 Operations source-control boundary only;
  it does not change runtime paper/shadow behavior, contact brokers, create
  broker orders, mutate OMS, write production ledger facts, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-07: `/api/operations/today` now feeds the `operations_runbook`
  acceptance audit export into the Operations runbook, so the
  `acceptance_audit` subsystem reports real audit completion evidence such as
  `operations_runbook:<completed>/<required>`, the generated timestamp, next
  action, and audit limitations instead of only using ledger-review count as a
  placeholder.
  Assumption: acceptance audit status is operator-facing readiness evidence
  for v1.6 runbook review, not a trading gate by itself. Validation:
  `uv run python -m pytest tests/test_operations_today.py -k acceptance_audit_subsystem`
  and
  `uv run python -m pytest tests/server/test_operations_routes.py -k today_operations_route_returns_read_only_runbook`.
  Risk impact: improves Operations Center audit observability without changing
  paper/shadow execution, contacting brokers, creating broker orders, mutating
  OMS, writing production ledger facts, enabling automatic trading, or
  bypassing manual confirmation.
- 2026-07-07: The `operations_runbook` acceptance audit now has an explicit
  `paper_shadow_fallback_review_queue` criterion tying the recent Operations
  Today legacy/partial-run fallback review queues to deterministic evidence and
  validation commands. Assumption: fallback review queues are a first-class
  v1.6.1 operator runbook capability because they prevent stale persisted
  paper/shadow payloads from hiding diverged, failed, or missing-simulation
  review work. Validation:
  `uv run python -m pytest tests/test_acceptance_audit.py -k operations_runbook`,
  `uv run python -m pytest tests/test_acceptance_audit_cli.py -k operations_runbook`,
  and
  `uv run python -m pytest tests/test_operations_today.py -k "legacy_diverged_run or missing_simulation"`.
  Risk impact: improves acceptance traceability only; it does not change
  runtime paper/shadow behavior, contact brokers, create broker orders, mutate
  OMS, write production ledger facts, enable automatic trading, or bypass
  manual confirmation.
- 2026-07-07: Operations Today fallback paper/shadow review queues now also
  cover persisted `review_required` runs whose divergence summary reports
  missing simulated order-intent refs but whose payload lacks stored orders or
  `review_queue` items. The synthesized item preserves run id, order-intent
  ref, `missing_simulation` status, review action, and no-broker-submission /
  no-production-ledger-mutation safety flags. Assumption: a missing simulation
  is still actionable operator review work and should not disappear from
  Operations/Overview/Decision simply because an older persisted payload had
  only divergence-summary evidence. Validation:
  `uv run python -m pytest tests/test_operations_today.py -k missing_simulation`.
  Risk impact: improves v1.6.1 paper/shadow runbook continuity for
  review-required runs without rerunning simulations, contacting brokers,
  creating broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Operations Today now synthesizes a minimal read-only
  paper/shadow review queue for legacy or partial persisted runs that have
  diverged/failed order evidence but no stored `review_queue` payload. The
  fallback queue preserves run id, order intent ref, order id, symbol, status,
  divergence status, required action, filled/remaining quantity, and explicit
  no-broker-submission / no-production-ledger-mutation safety flags.
  Assumption: Operations should not hide review work just because an older
  persisted run predates the richer review-queue schema; fallback items are
  runbook evidence only and do not rerun paper/shadow, contact brokers, mutate
  OMS, or sync ledger entries. Validation:
  `uv run python -m pytest tests/test_operations_today.py -k legacy_diverged_run`.
  Risk impact: improves v1.6.1 operator-facing divergence review continuity
  for Operations/Overview/Decision consumers without storing credentials,
  creating broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Operations Today scheduler summaries now carry explicit recovery
  evidence for failed market-session / paper-shadow automation runs:
  `suggested_action`, `requires_manual_review`, `retry_recommended`, and
  `does_not_mutate_production_ledger` join the existing run id, retry state,
  error, limitation, and no-broker-submission fields. Assumption: the
  operations API should be the source of truth for operator recovery cues, but
  these fields are read-only runbook evidence and do not start retries,
  contact brokers, mutate OMS, or sync ledger entries. Validation:
  `uv run python -m pytest tests/test_operations_today.py tests/server/test_operations_routes.py`.
  Risk impact: improves v1.6 scheduler/paper-shadow failure recovery
  auditability across Operations/Overview/Decision consumers without storing
  credentials, creating broker orders, mutating OMS, writing production ledger
  facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Overview Today's to-dos now expands failed scheduler / market
  session recovery text with the recorded automation run id, retry attempt,
  prior retry count, error summary, and explicit no-broker-submission safety
  boundary. Assumption: scheduler failure evidence should be visible in the
  operator's first daily queue, but it remains a read-only runbook cue and does
  not add retry, broker-submit, cancel, OMS mutation, or ledger-sync controls.
  Validation:
  `npm --prefix web test -- overview-page.test.tsx -t "failed scheduler run recovery"`.
  Risk impact: improves v1.6 scheduler/paper-shadow recovery visibility in
  Overview without contacting brokers, storing credentials, creating broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Decision Automation Cockpit now renders failed automation-run
  recovery evidence from open alert payloads: the primary `suggested_action`
  can drive the panel's next action, and alert chips show manual-review
  requirement, retry recommendation, no-broker-submission, and
  `does_not_mutate_production_ledger` safety flags. Assumption: the cockpit
  should surface the operator recovery action already recorded by the backend
  alert, but it must remain a read-only runbook cue with no retry,
  broker-submit, cancel, or ledger-sync control. Validation:
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "failed paper shadow automation recovery action"`.
  Risk impact: improves v1.6.1 paper/shadow failure recovery visibility in the
  operator UI without contacting brokers, storing credentials, creating broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Failed paper/shadow automation-run alerts now expose explicit
  operator recovery evidence: `requires_manual_review=true`, a
  `suggested_action` such as `inspect_failed_paper_shadow_run`, and
  `retry_recommended` derived from the persisted retry state. Existing alert
  keys, statuses, retry payloads, limitations, and no-submission safety flags
  remain unchanged. Assumption: a failed automation run should tell the
  operator what to inspect next, but this field is runbook evidence only and
  does not schedule retries or grant execution authority. Validation:
  `uv run python -m pytest tests/test_automation_alerts.py -k failed_paper_shadow_automation_run`.
  Risk impact: improves v1.6 scheduler/paper-shadow failure recovery
  visibility without contacting brokers, storing credentials, creating broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Paper/shadow run reviews now reject
  `accepted_for_manual_confirmation` when the raw run status is `failed`; failed
  simulations must remain blocked with `inspect_failed_run` until the operator
  inspects or reruns the paper/shadow workflow. Operations Today also
  defensively treats any stale `failed` + accepted review data as failed, so a
  corrupted or legacy row cannot become a manual-confirmation handoff. The
  review API returns HTTP 400 for this invalid transition and does not mutate
  the run review fields. Assumption: accepting divergence is only valid for
  simulated outcomes that produced reviewable evidence; failed simulations are
  missing or invalid evidence and require inspection/rerun. Validation:
  `uv run python -m pytest tests/test_paper_shadow_runs.py tests/test_operations_today.py tests/server/test_operations_routes.py -k "failed_run_manual_handoff or failed_shadow_run_blocked"`.
  Risk impact: strengthens the v1.6.1 paper/shadow gate before manual
  confirmation without creating broker orders, fills, OMS live transitions,
  production ledger entries, automatic trading, or bypassing risk/account-truth
  review.

## v1.7 Progress

- 2026-07-07: Strategy promotion lifecycle now supports audit-only operator
  pause and retire transitions, exposes lifecycle metadata to Automation
  Cockpit / Decision Cockpit, and rejects `controlled_bridge_pilot` lifecycle
  requests by default while recording a rejection event. Decision Cockpit
  renders paused/retired lifecycle state, audit-only evidence,
  does-not-authorize-execution, controlled-bridge-pilot disabled, and
  live-like disabled labels without live promotion controls. Assumption:
  pause/retire lifecycle transitions are operator audit evidence for strategy
  governance, not execution authority or broker bridge enablement. Validation:
  `uv run python -m pytest tests/test_strategy_promotion_pipeline.py -k "lifecycle or controlled_bridge"`,
  `uv run python -m pytest tests/server/test_strategy_promotion_routes.py -k "lifecycle or pause"`,
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "strategy promotion lifecycle audit"`,
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k controlled_broker_bridge_foundation`.
  Risk impact: improves v1.7 lifecycle visibility and auditability without
  contacting brokers, storing credentials, submitting or cancelling broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, authorizing controlled bridge pilot, or bypassing manual
  confirmation.
- 2026-07-07: Operations Today now exposes a read-only
  `execution_reconciliation` summary from open reconciliation items, including
  manual-execution review count, first open item, preview fingerprint evidence,
  next review step, and no-broker/no-OMS/no-ledger-mutation safety flags.
  Overview Today's to-dos renders the same manual execution reconciliation
  cue so an operator can import broker statements or explicitly review before
  any ledger update. Assumption: open reconciliation items are runbook evidence
  and do not authorize broker submission, cancellation, OMS mutation, or
  production ledger writes. Validation:
  `uv run python -m pytest tests/test_operations_today.py -k manual_execution_reconciliation_review`,
  `uv run python -m pytest tests/server/test_operations_routes.py -k execution_reconciliation_open_items`,
  `npm --prefix web test -- overview-page.test.tsx -t "manual execution reconciliation review"`,
  and
  `uv run python -m pytest tests/test_acceptance_audit.py -k controlled_broker_bridge_foundation`.
  Risk impact: improves v1.7 reconciliation/runbook visibility without
  contacting brokers, storing credentials, submitting or cancelling broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Trading manual-execution preview now renders the gateway
  `safety` flags for `broker_submission_enabled=false`,
  `requires_human_broker_entry=true`, `requires_operator_save=true`,
  `does_not_mutate_oms=true`, and
  `does_not_mutate_production_ledger=true` in the preview safety card before
  any manual execution evidence can be recorded. Assumption: these flags are
  operator-facing review evidence returned by the controlled bridge preview;
  they do not add save-ledger, apply-fill, submit, cancel, or broker connector
  controls. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "previews manual execution draft"`.
  Risk impact: improves v1.7 manual-execution handoff transparency without
  contacting brokers, storing credentials, submitting or cancelling broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Trading manual-execution preview and recorded manual-execution
  evidence now render gateway `limitations` directly in the approval panel,
  including the no-broker-submit, no-gateway-event/fill, no-OMS-mutation, and
  no-ledger-write boundaries returned by the backend. Assumption: limitations
  are operator review text and audit context, not controls; execution authority
  still comes only from the existing manual-confirmation, risk, paper/shadow,
  account-truth, kill-switch, and reconciliation gates. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "manual execution"`.
  Risk impact: improves v1.7 controlled-bridge transparency before and after
  manual execution evidence recording without contacting brokers, storing
  credentials, submitting or cancelling broker orders, mutating OMS, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-07: Trading manual-execution preview now shows the current
  position/cost-basis baseline alongside the post-execution projection,
  including current quantity, current average cost, and current market value
  when the gateway preview provides them. Assumption: the baseline helps the
  operator compare before/after manual fill effects before recording evidence,
  but it remains read-only preview data and does not save a ledger entry, apply
  a fill, submit to a broker, or authorize execution. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "previews manual execution draft"`.
  Risk impact: improves v1.7 manual execution review clarity before evidence
  recording without contacting brokers, storing credentials, submitting or
  cancelling broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading manual-execution preview now renders the
  `position_cost_preview` from the gateway response before an operator can
  record manual execution evidence, including execution-after quantity,
  average cost, cost-basis method, and preview source. Assumption: this
  position/cost-basis block is read-only review evidence for an
  operator-entered manual fill; it does not save a ledger entry, apply a fill,
  submit to a broker, or authorize execution. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "previews manual execution draft"`.
  Risk impact: improves v1.7 manual execution review clarity before evidence
  recording without contacting brokers, storing credentials, submitting or
  cancelling broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading manual-execution evidence records now render the
  record-level `requires_operator_ledger_save=true` safety flag next to the
  existing no-broker-submission, no-OMS-mutation, and no-production-ledger
  mutation flags. Assumption: a recorded manual execution is audit continuity
  after the operator typed a broker ticket, but any ledger update still requires
  a separate operator save/reconciliation decision. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "records manual execution evidence"`.
  Risk impact: improves v1.7 Trading review clarity for manual execution
  evidence without contacting brokers, storing credentials, submitting or
  cancelling broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading manual-ticket export review now surfaces the generated
  export file name, MIME type, export schema, export format, and gateway
  limitations beside the broker copy text and JSON payload. Assumption:
  operator-facing export metadata reduces manual-entry ambiguity, but it is
  still review evidence only and does not create a local download, broker
  order, fill, OMS transition, or production ledger entry. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "exports confirmed manual ticket"`.
  Risk impact: improves v1.7 manual-ticket export ergonomics and auditability
  without contacting brokers, storing credentials, submitting or cancelling
  broker orders, mutating OMS, writing production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-07: Local JSON read-only broker connector exports now require the
  explicit `karkinos.readonly_broker_snapshot_export.v1` schema before any
  account id, cash, position, order, or fill field is accepted. Unsupported or
  missing schemas degrade into an `incomplete` runtime snapshot, and the
  `qmt_readonly_export` / `ptrade_readonly_export` example config entries now
  document the same ignored local JSON snapshot contract. Assumption: QMT and
  PTrade local exports enter Karkinos through a user-managed sanitized snapshot
  file, not direct broker client control; wrong files are data-quality
  evidence, not account truth. Validation:
  `uv run python -m pytest tests/account_truth/test_broker_connector.py tests/server/test_broker_gateway_routes.py -k "unsupported_schema"`
  and
  `uv run python -m pytest tests/test_bootstrap.py -k example_broker_connector_config_contains_no_credentials`.
  Risk impact: improves v1.7 local read-only adapter integrity without
  contacting brokers, storing credentials, exposing private account ids,
  creating fills, mutating OMS, saving production ledger entries, submitting or
  cancelling broker orders, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-07: Local JSON read-only broker connector exports now degrade invalid
  local snapshot files into an `incomplete` runtime snapshot instead of
  propagating JSON, file, or decimal parsing exceptions through broker gateway
  routes. Invalid snapshots omit private account ids and account facts, keep
  connector health as `runtime_degraded` / `snapshot_degraded`, and preserve
  explicit no-broker-contact / no-submission limitations for Operations and
  alert review. Assumption: the JSON file is a user-managed ignored local
  export and malformed numeric fields should be treated as data-quality
  evidence, not a broker runtime action. Validation:
  `uv run python -m pytest tests/account_truth/test_broker_connector.py tests/server/test_broker_gateway_routes.py -k "invalid_export or invalid_snapshot_degrades"`
  and
  `uv run python -m pytest tests/account_truth/test_broker_connector.py tests/server/test_broker_gateway_routes.py tests/test_broker_gateway_service.py tests/test_automation_alerts.py -k "local_json or local_export or runtime_readonly_connector or connector_health"`.
  Risk impact: improves v1.7 local read-only adapter resilience without
  contacting brokers, storing credentials, exposing private account ids,
  creating fills, mutating OMS, saving production ledger entries, submitting or
  cancelling broker orders, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-07: Execution reconciliation now preserves the broker-gateway
  `validation.required_gate_summary` from `manual_execution_recorded` gateway
  events inside `manual_execution_evidence_summary`, and automation alerts
  continue to carry that same controlled-bridge gate summary in the
  acknowledgeable runbook payload. Assumption: the gate summary is read-only
  audit evidence for later broker-statement import, reconciliation review, or
  explicit ledger-save review; it does not authorize broker submission or
  ledger mutation. Validation:
  `uv run pytest tests/test_execution_reconciliation_service.py -k manual_execution_record`
  and
  `uv run pytest tests/test_automation_alerts.py -k manual_execution_reconciliation_evidence`.
  Risk impact: improves v1.7 full audit trail continuity without contacting
  brokers, storing credentials, creating fills, changing OMS status, saving
  production ledger entries, submitting or cancelling broker orders, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading approvals now render the broker-gateway
  `required_gate_summary` from manual execution preview/record responses,
  showing the controlled-bridge gate names, statuses, evidence refs, and the
  `does_not_authorize_execution=true` safety boundary beside the manual
  execution economics and preview fingerprint. Assumption: this is an
  operator-facing audit aid for reviewing account-truth, research, risk,
  paper/shadow, manual-confirmation, kill-switch, connector-health, and
  reconciliation evidence before later ledger or reconciliation work; it is not
  a live bridge action. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "manual execution"`.
  Risk impact: improves v1.7 gate visibility at the manual execution handoff
  without contacting brokers, storing credentials, creating fills, mutating
  OMS, saving production ledger entries, submitting or cancelling broker
  orders, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Manual execution preview and recorded manual-execution evidence
  now carry a `required_gate_summary` inside the broker-gateway validation
  payload. The summary lists the v1.7 controlled-bridge gates
  (`account_truth`, `research_evidence`, `risk`, `paper_shadow`,
  `manual_confirmation`, `kill_switch_clear`, `connector_health`, and
  `execution_reconciliation`), preserves OMS gateway evidence refs, marks the
  manual-ticket and kill-switch state, and explicitly states that the payload
  does not authorize execution or submit to a broker. The same validation
  snapshot is written to the `manual_execution_recorded` gateway audit event.
  Assumption: manual execution evidence is post-ticket audit continuity; it
  helps the operator prove which gates were reviewed before a ledger-save or
  reconciliation decision, but it does not become broker authority. Validation:
  `uv run pytest tests/test_broker_gateway_service.py`. Risk impact: improves
  v1.7 controlled-bridge auditability without contacting brokers, storing
  credentials, creating fills, mutating OMS, saving production ledger entries,
  submitting or cancelling broker orders, enabling automatic trading, or
  bypassing manual confirmation.
- 2026-07-07: Decision Cockpit automation status now renders manual execution
  reconciliation alert detail plus the read-only evidence summary from the
  automation cockpit open-alert payload: preview fingerprint, event count,
  reviewed economics, net cash impact, ledger draft amount, and explicit
  review/no-broker-submission/no-OMS-mutation/no-production-ledger-mutation
  safety labels. Assumption: the open alert payload is runbook evidence for the
  operator; broker statement import or an explicit ledger-save review is still
  required before production ledger facts change. Validation:
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "surfaces manual execution alert evidence"`
  and
  `npm --prefix web test -- overview-page.test.tsx decision-cockpit-page.test.tsx trading-page.test.tsx public-labels.test.ts ledger-format.test.ts`.
  Risk impact: improves v1.7 Operations/Decision runbook visibility without
  contacting brokers, storing credentials, creating fills, saving production
  ledger entries, mutating OMS, submitting or cancelling broker orders,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Automation alert scanning now preserves
  `manual_execution_recorded` execution-reconciliation evidence in the
  acknowledgeable runbook alert payload. The alert carries the read-only manual
  execution summary, preview fingerprint, gateway event ids, reviewed economics,
  and explicit no-broker-submission / no-OMS-mutation /
  no-production-ledger-mutation safety flags. Assumption: this alert helps the
  operator find manual execution records that still need broker statement import
  or explicit ledger-save review; it is not a ledger-sync, fill-apply, broker
  submit, or cancel workflow. Validation:
  `uv run pytest tests/test_automation_alerts.py -k manual_execution_reconciliation_evidence`.
  Risk impact: improves v1.7 Operations runbook continuity for manual execution
  reconciliation without contacting brokers, storing credentials, creating
  fills, saving production ledger entries, mutating OMS, submitting or
  cancelling broker orders, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-07: Execution reconciliation now recognizes
  `manual_execution_recorded` gateway events for manual-ticket OMS orders and
  exposes a read-only `manual_execution_evidence_summary`: event ids, preview
  fingerprint, fill price, quantity, gross amount, fee/tax, transfer fee, net
  cash impact, ledger-entry draft amount, and explicit review/no-mutation
  safety flags. Decision Cockpit renders the same summary as operator evidence
  with no ledger-sync, fill-apply, broker-submit, or cancel controls.
  Assumption: a manual execution record proves which human-entered execution
  preview was reviewed; broker statements still need to be imported or the
  ledger save must be explicitly reviewed later. Validation:
  `uv run pytest tests/test_execution_reconciliation_service.py -k manual_execution_record`
  and
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "surfaces manual execution evidence"`.
  Risk impact: improves v1.7 execution-reconciliation audit continuity without
  contacting brokers, storing credentials, creating fills, saving production
  ledger entries, mutating OMS, submitting or cancelling broker orders,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading approvals now records matching-fingerprint manual
  execution evidence after the operator previews a confirmed manual-ticket
  export. The UI posts the reviewed fill price, quantity, fee, tax, transfer
  fee, and `preview_fingerprint` to the broker gateway record endpoint, then
  shows the gateway audit event id plus explicit no-broker-submission /
  no-OMS-mutation / no-production-ledger-mutation safety flags. Assumption:
  this is controlled bridge audit continuity after a human-entered execution
  preview; it is not a broker fill, ledger save, OMS transition, broker
  submission, or cancellation. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "records manual execution evidence"`.
  Risk impact: improves v1.7 non-submitting manual execution traceability
  without contacting brokers, storing credentials, creating fills, saving
  production ledger entries, mutating OMS, submitting or cancelling broker
  orders, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Added a deterministic strategy broker-boundary scanner that
  checks the current `strategy/` tree for forbidden broker/gateway adapter
  imports and direct broker-style calls such as `submit_order()`. The
  controlled broker bridge foundation acceptance audit now records this guard
  as evidence for the "no strategy-direct broker access" requirement.
  Assumption: the guard covers strategy files present under the local
  `strategy/` tree, including ignored private extension files if they are
  stored there; private strategies outside the repo must be passed to the
  scanner explicitly. Risk impact: reduces the chance of future QMT/PTrade or
  other broker adapters leaking into strategy code while preserving the
  policy -> risk -> OMS -> gateway -> reconciliation authority path; it does
  not contact a broker, store credentials, create gateway events, mutate OMS,
  write production ledger facts, submit or cancel broker orders, enable
  automatic trading, or bypass manual confirmation.

## v1.6 Progress

- 2026-07-07: Trading execution audit now shows accepted paper/shadow review
  outcome evidence after the operator records a divergence review: reviewer,
  reviewed timestamp, and explicit no-broker-submission /
  no-production-ledger-mutation safety flags. Assumption: accepted review
  metadata is a manual-confirmation handoff audit trail, not execution
  authority. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "records accepted simulation review"`.
  Risk impact: improves v1.6.1 review-outcome traceability without contacting
  brokers, storing credentials, creating broker orders, submitting or
  cancelling broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading execution audit now surfaces the first structured
  paper/shadow `review_queue` item alongside the latest run summary: public next
  action, review reason, OMS status path, latest OMS transition ref, and
  explicit no-broker-submission / no-production-ledger-mutation safety flags.
  Assumption: Trading is the manual-confirmation review surface, so it should
  display the same read-only divergence evidence already carried by Operations;
  this summary does not authorize execution. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"`.
  Risk impact: improves v1.6.1 operator-facing divergence review before manual
  confirmation without contacting brokers, storing credentials, creating broker
  orders, submitting or cancelling broker orders, mutating OMS, writing
  production ledger facts, enabling automatic trading, or bypassing manual
  confirmation.
- 2026-07-07: Trading execution audit now prioritizes compact paper/shadow run
  evidence as simulated order, simulated fill, and latest OMS transition instead
  of blindly showing the first three refs. This keeps long run-level
  `evidence_refs` readable while preserving the newest state-machine transition
  such as `OMS transition · SHADOW-1 #4 Partially Filled`. Assumption: this is
  a display-only runbook summary; the full persisted run payload remains the
  audit source of truth. Validation:
  `npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"`.
  Risk impact: improves v1.6.1 Trading runbook clarity without contacting
  brokers, storing credentials, creating broker orders, submitting or
  cancelling broker orders, mutating OMS, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Trading execution audit and the shared public evidence formatter
  now render run-level `oms_transition:{order_id}:{sequence}:{status}` refs as
  user-facing OMS transition labels, for example
  `OMS transition · SHADOW-1 #4 Partially Filled`, without exposing raw refs or
  snake-case status codes. Assumption: transition refs are read-only audit links
  for paper/shadow review and future reconciliation/manual-ticket inspection,
  not execution authority. Validation:
  `npm --prefix web test -- public-labels.test.ts -t "formats internal evidence references"`
  and
  `npm --prefix web test -- trading-page.test.tsx -t "surfaces latest paper shadow run evidence"`.
  Risk impact: improves v1.6.1 paper/shadow-to-Trading audit readability
  without contacting brokers, storing credentials, creating broker orders,
  submitting or cancelling broker orders, writing production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Paper/shadow run-level `evidence_refs` now include
  deterministic `oms_transition:{order_id}:{sequence}:{status}` references
  derived from simulated OMS transitions, so the persisted run payload can
  point at the same state-machine evidence shown in the structured review
  queue. Assumption: transition refs are audit links for paper/shadow and
  future reconciliation/manual-ticket review, not execution authority.
  Validation:
  `uv run pytest tests/test_paper_shadow_run_service.py -k creates_simulated_order`.
  Risk impact: improves v1.6.1 run-level OMS auditability without contacting
  brokers, storing credentials, creating broker orders, submitting or
  cancelling broker orders, writing production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-07: Paper/shadow review queue items now expose compact OMS
  transition audit evidence for simulated orders, and Decision Cockpit plus
  Overview Today's to-dos render the public status path and latest transition
  summary without raw state codes: deterministic `oms_transition:` refs,
  per-step from/to status, reason, source, filled quantity, and explicit
  non-submission/non-ledger-mutation flags remain in the payload for audit.
  Assumption: these transition details are operator review evidence for
  paper/shadow state-machine audit and do not create execution authority.
  Validation:
  `uv run pytest tests/test_paper_shadow_run_service.py -k structured_review_evidence`
  and
  `uv run pytest tests/test_paper_shadow_run_service.py tests/test_oms_service.py tests/test_operations_today.py -k "paper_shadow or oms"`
  plus
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "renders paper shadow review queue as public operator review items"`
  and
  `npm --prefix web test -- overview-page.test.tsx -t "surfaces paper shadow divergence evidence summary in today todos"`.
  Risk impact: improves v1.6.1 paper/shadow OMS auditability without
  contacting brokers, storing credentials, creating broker orders, submitting
  or cancelling broker orders, writing production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-07: Overview Today's to-dos now includes a compact structured
  paper/shadow review-queue summary for the first operator review item:
  public risk/manual status, Account Truth and cash state, constraint counts,
  projected fee, simulated fee/tax, queue slippage, market price context, and
  public evidence refs. Assumption: Overview remains a scan-first runbook
  surface, so it summarizes the first queue item and sends deeper review to
  Decision/Trading rather than adding execution controls. Validation:
  `npm --prefix web test -- overview-page.test.tsx -t "surfaces paper shadow divergence evidence summary in today todos"`.
  Risk impact: improves v1.6.1 Overview paper/shadow review visibility without
  contacting brokers, storing credentials, submitting or cancelling broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Decision Cockpit now renders structured paper/shadow review
  queue evidence for each operator review item, including public risk/manual
  confirmation status, Account Truth and cash status, constraint counts,
  projected and simulated cost evidence, market price context, and strategy /
  risk / signal / simulated-order / simulated-fill evidence refs. The shared
  public evidence formatter now recognizes `strategy:`, `paper_order:`, and
  `paper_fill:` refs so runbook surfaces do not degrade them into generic
  review labels. Assumption: the added fields are read-only review evidence
  for the operator and do not create execution authority. Validation:
  `npm --prefix web test -- decision-cockpit-page.test.tsx -t "renders paper shadow review queue as public operator review items"`
  and `npm --prefix web test -- public-labels.test.ts -t "formats internal evidence references"`.
  Risk impact: improves v1.6.1 Decision paper/shadow review visibility without
  contacting brokers, storing credentials, submitting or cancelling broker
  orders, mutating OMS, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-07: Paper/shadow review queue items now carry structured review
  evidence for operator-facing divergence review: strategy/risk/signal refs,
  deduplicated evidence refs, account-truth gate state, risk/manual/submission
  statuses, cash and constraint status counts, fee/slippage evidence, and
  market price context. Assumption: these fields are read-only runbook
  evidence used to explain why a simulated order needs review; they do not
  authorize broker submission or ledger mutation. Validation:
  `uv run pytest tests/test_paper_shadow_run_service.py -k structured_review_evidence`.
  Risk impact: improves v1.6.1 paper/shadow divergence review clarity without
  contacting brokers, storing credentials, creating broker orders, mutating
  OMS beyond existing paper/shadow simulation transitions, writing production
  ledger facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-07: Operations Today now translates retryable market-session
  scheduler retry state into a human-readable scheduler subsystem limitation,
  for example `Scheduler retry attempt 2 of 2; previous attempts: 1.` The raw
  `retry_state` remains available in the scheduler payload for audit, while
  the runbook surface exposes the retry count without leaking implementation
  field names. Assumption: retry-attempt text is operator review evidence only
  and does not trigger automatic retries by itself. Validation:
  `uv run pytest tests/test_operations_today.py -k scheduler_retry_attempt`.
  Risk impact: improves scheduler failure review in Operations/Overview
  without contacting brokers, storing credentials, creating broker orders,
  mutating OMS, writing production ledger facts, enabling automatic trading,
  or bypassing manual confirmation.
- 2026-07-07: Market-session automation retry state now increments
  `retry_state.attempt` for repeated retryable failures on the same
  fingerprint-idempotent run and records `previous_attempts` once a prior
  failed attempt exists. Assumption: retry attempt count is runbook evidence
  for the operator and automation alerts; it does not automatically keep
  retrying beyond the scheduler invocation. Validation:
  `uv run pytest tests/test_market_session_automation.py`. Risk impact:
  improves failed scheduler-run review and retry auditability without
  contacting brokers, storing credentials, creating broker orders, mutating
  OMS, writing production ledger facts, enabling automatic trading, or
  bypassing manual confirmation.
- 2026-07-07: Market-session automation run records now use the deterministic
  trading-plan fingerprint idempotency key as the persisted `run_id`, so
  repeated scheduler invocations for the same plan/date update one audit run
  instead of creating time-sliced duplicates; changed trading-plan inputs still
  create a new run. Assumption: a market-session run is identified by
  run date plus normalized trading-plan inputs, not by wall-clock poll time.
  Validation: `uv run pytest tests/test_market_session_automation.py`. Risk
  impact: improves scheduler/runbook audit determinism and retry review
  without contacting brokers, storing credentials, creating broker orders,
  mutating OMS, writing production ledger facts, enabling automatic trading,
  or bypassing manual confirmation.
- 2026-07-06: Added a `local_export_readonly` connector adapter that reads an
  ignored local JSON broker snapshot into the existing read-only connector
  contract. Broker Gateway routes and automation routes now turn that local
  config into a runtime `read_account_snapshot()` connector for health and
  snapshot queries, while preserving the legacy QMT/PTrade configuration-only
  health contract for other connector types. Assumption: the JSON file is a
  user-managed local export, not source-controlled broker evidence or a broker
  login credential. Risk impact: moves connector polling from deterministic
  fake-only fixtures toward real local read-only account evidence without
  contacting a broker client, storing credentials, creating gateway events,
  submitting or cancelling broker orders, mutating OMS, writing production
  ledger facts, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-06: Automation Cockpit and Decision Cockpit now surface runtime
  read-only connector snapshot summaries from `read_account_snapshot()`
  connectors. The panel shows connector id, alias, snapshot status, cash,
  position/order/fill counts, and explicit no-submission/no-ledger-mutation
  safety text without exposing account ids or rendering broker submit, cancel,
  fill-apply, or ledger-sync controls. Assumption: the cockpit summary is
  operator-review evidence for the controlled bridge runbook, not execution
  authority. Risk impact: makes v1.7 query-only connector evidence visible in
  the daily review surface while preserving manual confirmation and non-live
  broker defaults.
- 2026-07-06: Broker Gateway now exposes a read-only runtime connector
  snapshot query for connector objects that implement `read_account_snapshot()`.
  The query returns connector health, cash, positions, orders, and fills with
  explicit non-submitting capability blockers while excluding account ids. It
  does not create gateway events, mutate OMS, write ledger entries, store
  credentials, submit orders, or cancel orders. Assumption: runtime connector
  snapshots are account-truth evidence for operator review and future
  reconciliation, not execution authority. Risk impact: advances v1.7 query-only
  broker gateway contracts without enabling live broker automation or bypassing
  manual confirmation.
- 2026-07-06: Broker Gateway connector health now recognizes read-only
  connector objects that implement `read_account_snapshot()`. It polls the
  snapshot health into a runtime health payload with connector id, alias,
  heartbeat, runtime status, capability scope, non-submitting capability
  blockers, and limitations while excluding account ids. Automation alert
  scanning can consume the same connector object and create a
  `broker_connector_health` alert for degraded snapshots. Assumption: runtime
  connector polling is read-only account-fact evidence and the deterministic
  fake connector represents the future QMT/PTrade read-only adapter contract.
  Risk impact: advances Operations runbook wiring for real read-only connector
  polling without storing credentials, submitting orders, cancelling orders,
  creating gateway events, mutating OMS state, writing ledger entries, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-06: Automation connector-health alerts now preserve the read-only
  connector `capability_scope`, read/query capability flags, and explicit
  preview/export/dry-run/cancel/submit blockers in the alert payload for both
  configuration-incomplete and runtime-degraded connector health snapshots.
  Assumption: connector-health alerts are runbook evidence for operator review,
  not live broker probes or execution permissions. Risk impact: improves
  Operations alert audit continuity for future controlled-bridge readiness
  without contacting broker clients, storing credentials, submitting orders,
  cancelling orders, creating gateway events, mutating OMS state, writing
  ledger entries, enabling automatic trading, or bypassing manual confirmation.
- 2026-07-06: Read-only broker connector health now exposes a fuller
  capability contract with `capability_scope`, read/query capability flags, and
  explicit non-submitting `can_preview_orders=false`,
  `can_export_tickets=false`, `can_dry_run_orders=false`,
  `can_submit_orders=false`, and `can_cancel_orders=false` flags. Decision
  Cockpit renders the same connector preview/export/dry-run/submit/cancel
  boundaries as blocked capability labels. Assumption: connector health is a
  local configuration contract, not a live broker-client probe. Risk impact:
  makes future controlled-bridge capability review more explicit without
  contacting broker clients, storing credentials, submitting orders, cancelling
  orders, creating gateway events, mutating OMS state, writing ledger entries,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-06: Broker gateway now exposes
  `POST /api/broker-gateway/orders/{order_id}/manual-execution` to record
  reviewed manual execution evidence after manual-ticket creation. The endpoint
  recomputes the manual execution preview, requires the supplied
  `preview_fingerprint` to match, and then writes a
  `manual_execution_recorded` gateway audit event with the execution preview,
  ledger-entry draft, position/cost preview, controlled bridge policy, and
  operator note. Assumption: this event proves which preview draft the
  operator reviewed; it is not a broker fill, ledger entry, or OMS state
  transition. Risk impact: improves manual execution audit continuity without
  creating fills, changing OMS status, writing production ledger entries,
  contacting a broker, submitting or cancelling orders, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-06: Manual execution preview responses now include a deterministic
  `preview_fingerprint` and explicit fingerprint scope covering order id,
  execution preview, ledger-entry draft, position/cost preview, and controlled
  bridge policy. Trading approvals renders the fingerprint after preview so an
  operator can correlate later reconciliation or manual-save review with the
  exact economics draft they inspected. Assumption: the fingerprint identifies
  the preview economics and policy snapshot, not the operator identity and not
  a broker-side execution. Risk impact: improves auditability of manual
  execution review only; it does not write ledger entries, create fills, change
  OMS state, contact a broker, submit or cancel orders, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-06: Trading approvals now exposes the broker gateway manual
  execution preview after a confirmed manual-ticket export. The UI sends the
  operator-entered fill price, quantity, fee, tax, and transfer fee to
  `POST /api/broker-gateway/orders/{order_id}/manual-execution/preview`, then
  renders gross amount, fee/tax, transfer fee, net cash impact, ledger draft
  amount, `requires_operator_save=true`, and
  `does_not_mutate_production_ledger=true` as read-only review evidence.
  Assumption: the preview values come from a human's broker-client entry or
  statement review after manual-ticket creation; they are not an instruction
  to apply a fill or save a ledger record. Risk impact: improves operator
  visibility before ledger review without adding save-ledger, apply-fill,
  broker-submit, broker-cancel, OMS mutation, live broker contact, automatic
  trading, or a bypass of manual confirmation.
- 2026-07-06: Broker gateway now exposes a non-mutating manual execution
  preview at
  `POST /api/broker-gateway/orders/{order_id}/manual-execution/preview`.
  The endpoint requires an OMS order that has already reached
  `manual_ticket_created`, accepts operator-entered fill price, quantity, fee,
  tax, and transfer fee, and returns gross amount, total cost, net cash impact,
  a production-ledger draft, position/cost preview, and explicit
  operator-save / no-ledger-mutation safety flags. Assumption: this preview is
  a review draft after the operator manually enters a broker ticket; it is not
  a fill import, ledger-sync, or broker submission path. Risk impact: improves
  manual execution review before any saved ledger record without creating
  gateway events, changing OMS status, mutating production ledger facts,
  contacting a broker, submitting or cancelling orders, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-06: Decision Cockpit now surfaces broker trade cost evidence from
  execution reconciliation items. The automation panel renders the staged
  broker event count, gross amount, fee/tax, transfer fee, net amount, and
  explicit review-before-ledger-update / no-ledger-mutation flags as read-only
  operator evidence. Assumption: these values are reconciliation evidence for
  human review before any production ledger action; they are not ledger-sync
  instructions. Risk impact: improves fee/tax/net-amount visibility in the
  operator workflow without adding ledger-sync, fill-apply, OMS mutation,
  broker submit, broker cancel, live broker contact, automatic trading, or a
  bypass of manual confirmation.
- 2026-07-06: Execution reconciliation now includes a read-only
  `broker_trade_cost_summary` payload for matched or mismatched staged broker
  trade evidence. The summary carries staged broker event ids, currency, gross
  amount, fee, tax, transfer fee, net amount, and explicit
  review-before-ledger-update / no-ledger-mutation flags. Assumption: broker
  cost fields are evidence for operator reconciliation only, not an automatic
  ledger-sync instruction. Risk impact: improves fee/tax/net-amount review
  before any ledger update without contacting a broker, submitting or
  cancelling orders, mutating OMS or production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-06: Decision Cockpit now renders strategy promotion state from the
  Automation Cockpit summary as read-only evidence. The panel shows the
  strategy id, lifecycle stage, paper/shadow gate status, missing readiness
  requirements, backtest evidence id when present, and an explicit
  `Live-like disabled` boundary. Assumption: strategy promotion state helps an
  operator understand readiness and paper/shadow enablement; it does not
  authorize execution by itself. Risk impact: improves lifecycle visibility
  without adding live-promotion controls, broker submit, broker cancel,
  ledger-sync, OMS mutation, live broker contact, or automatic trading
  behavior.
- 2026-07-06: Decision Cockpit now renders gateway query/read capability
  labels and connector read-cash/read-position capability labels alongside
  preview/export/dry-run/submit/cancel status. Assumption: these labels are a
  read-only operator contract for what local connectors and gateways can
  observe; they are not query buttons or broker actions. Risk impact: improves
  capability visibility before any controlled bridge work without adding
  broker submit, broker cancel, credential exposure, ledger-sync, OMS mutation,
  live broker contact, or automatic trading behavior.
- 2026-07-06: Decision Cockpit now queries the existing read-only broker
  gateway order endpoint for the first open execution reconciliation item and
  renders OMS status, gateway audit count, staged broker fill count, and the
  non-submission safety boundary in the automation panel. Assumption: this
  order query is a local audit/evidence view for operator reconciliation, not
  a broker polling or action surface. Risk impact: improves visibility into
  OMS/gateway/staged-evidence agreement without adding broker submit, broker
  cancel, ledger-sync, fill-apply, OMS mutation, live broker contact, or
  automatic trading behavior.
- 2026-07-06: Decision Cockpit now links read-only staged fill evidence to
  execution reconciliation review. When staged fills exist and the latest
  execution reconciliation run has open items, the automation panel shows a
  review hint that the staged fills can be compared before any ledger update.
  Assumption: this is an operator handoff between staged broker evidence and
  reconciliation, not an approval workflow. Risk impact: improves review
  clarity without adding broker submit, broker cancel, ledger-sync, fill-apply,
  OMS mutation, live broker contact, or automatic trading behavior.
- 2026-07-06: Decision Cockpit now consumes the read-only staged fill query and
  renders a staged fill-polling summary in the automation panel. The panel
  shows fill counts, staged broker-evidence event counts, sample symbols, and
  the non-submission safety boundary without adding broker submit, broker
  cancel, or ledger-sync controls. Assumption: this UI is an operator review
  surface for already imported broker evidence and future execution
  reconciliation. Risk impact: improves visibility into query-only fill
  evidence only; it does not contact a broker, store credentials, submit or
  cancel broker orders, mutate OMS or production ledger facts, enable
  automatic trading, or bypass manual confirmation.
- 2026-07-06: Broker gateway now exposes a read-only staged fill query through
  `GET /api/broker-gateway/fills/query`. The service reads already imported
  broker trade evidence, can filter by symbol, returns fill counts and import
  references, and keeps `submitted_to_broker=false` and
  `can_submit_orders=false`. The query does not create gateway events, mutate
  OMS state, update ledger facts, contact broker clients, store credentials,
  or cancel/submit orders. Assumption: staged broker fills are evidence for
  operator review and execution reconciliation, not live broker truth by
  themselves. Risk impact: improves v1.7 query-only/fill-polling readiness
  without enabling broker submission, automatic trading, ledger mutation, or a
  bypass of manual confirmation.
- 2026-07-06: Manual-ticket export now includes an operator form snapshot with
  user-readable field labels, a controlled-policy account alias, fee/tax
  assumptions, net cash impact, remaining-position/cost-basis preview,
  regular-session constraints, and explicit non-submission safety flags. The
  Trading page renders those fields before the JSON audit payload so an
  operator can manually enter the ticket without inferring broker submission.
  Assumption: fee/tax, cash-impact, and position/cost values in this form are
  review assumptions from OMS/order-intent context when available, while the
  broker client remains authoritative before manual entry. Risk impact:
  improves manual-entry ergonomics and audit clarity only; it does not contact
  a broker, store credentials, submit or cancel broker orders, save manual
  execution records, mutate production ledger facts, enable automatic trading,
  or bypass manual confirmation.
- 2026-07-06: Manual-ticket preview, export, dry-run, and create now preserve
  the current `controlled_bridge_policy` snapshot in validation payloads,
  export JSON, and broker gateway audit events. This lets each non-submitting
  ticket record show the policy id, whitelist, required gates, blockers, and
  disabled live-submission state that were in force when the ticket was
  prepared or recorded. Assumption: the policy snapshot is immutable audit
  context for local review only and does not authorize broker API submission.
  Risk impact: improves manual-ticket audit traceability only; it does not
  contact a broker, store credentials, submit or cancel broker orders, mutate
  OMS beyond the existing manual-ticket-created transition, mutate production
  ledger facts, enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Decision Cockpit now renders the broker gateway
  `controlled_bridge_policy` snapshot as read-only bridge evidence. The panel
  shows the policy id, non-submitting status, connector/account/strategy/symbol
  whitelist, required gates, and blockers without adding submit, cancel, or
  ledger-sync controls. Assumption: this UI surface helps review future bridge
  readiness only and does not make the bridge actionable. Risk impact: improves
  operator visibility into controlled-bridge policy evidence only; it does not
  contact a broker, store credentials, submit or cancel broker orders, mutate
  OMS or production ledger facts, enable automatic trading, or bypass manual
  confirmation.
- 2026-07-06: Local server config now has a typed
  `controlled_bridge_policy` parser for the future controlled broker bridge
  whitelist model. The parser is server-only, keeps the default policy
  disabled, accepts connector/account/strategy/symbol review whitelists,
  rejects password/secret/token/credential fields, rejects
  `automation_allowed=true`, and requires per-order confirmation to remain
  enabled. `config.example.json` and the config docs show only a disabled
  non-submitting example. Assumption: this local config is review metadata for
  the gateway status policy skeleton, not a live adapter enablement path.
  Risk impact: improves bridge-policy auditability only; it does not contact a
  broker, store credentials, submit or cancel broker orders, mutate OMS or
  production ledger facts, enable automatic trading, or bypass manual
  confirmation.
- 2026-07-06: Broker gateway status now exposes a
  `controlled_bridge_policy` snapshot for the future controlled bridge
  whitelist model. The default policy is disabled, has empty connector,
  account, strategy, and symbol whitelists, lists the required account-truth,
  research, risk, paper/shadow, manual-confirmation, kill-switch, connector
  health, and execution-reconciliation gates, and reports
  `live_submission_available=false`. If a local review policy is injected, it
  can surface the configured whitelist as `configured_non_submitting`, but
  broker submission, cancellation, and automation remain disabled. Assumption:
  this is an API-visible policy skeleton for future review only, not a live
  broker adapter or enablement path. Risk impact: improves bridge policy
  auditability only; it does not contact a broker, store credentials, submit
  or cancel broker orders, mutate OMS or production ledger facts, enable
  automatic trading, or bypass manual confirmation.
- 2026-07-06: Acceptance audit export now includes a
  `controlled_broker_bridge_foundation` manifest for completed non-submitting
  broker bridge foundation capabilities. The manifest records evidence and
  validation commands for disabled-by-default broker submission, manual-ticket
  preview/export/dry-run/create, gateway capability and connector health
  contracts, account-truth/research/risk/paper-shadow/manual-confirmation
  gates, kill-switch enforcement, read-only staged account facts and local
  order queries, default-rejected broker cancellation, execution
  reconciliation, and the Decision Cockpit's read-only bridge panel.
  Assumption: this audit marks only the listed foundation capabilities as
  evidenced and does not enable or complete a live broker submission path.
  Risk impact: improves release-review evidence only; it does not contact a
  broker, store credentials, submit or cancel broker orders, mutate production
  ledger facts, enable automatic trading, or bypass manual confirmation.

## v1.6 Progress

- 2026-07-06: Decision and Overview now consume the paper/shadow
  `review_queue` as operator-facing runbook evidence. Overview Today's to-dos
  adds a compact queue count and public next-action label, while the Decision
  daily trading-plan panel renders the first review items with symbol, public
  action text, and explicit no-broker-submission/no-production-ledger-mutation
  boundaries. Assumption: UI queue items are review guidance only and do not
  expose raw OMS state codes or backend reason text. Risk impact: improves the
  v1.6.1 manual review handoff without adding execution controls, submitting or
  cancelling broker orders, creating fills, mutating production ledger facts,
  enabling automatic trading, or bypassing manual confirmation.
- 2026-07-06: Paper/shadow runs now emit a structured `review_queue` for
  simulated divergence and failed simulations. Each item carries the run/order
  references, status, divergence status, severity, required operator action,
  human-readable reason, filled/remaining quantity when available, and explicit
  no-broker-submission/no-production-ledger-mutation evidence. Operations Today
  surfaces the persisted queue directly so runbook clients do not need to infer
  the next review items from raw OMS statuses. Assumption: the queue is
  operator-review guidance for simulated evidence only. Risk impact: improves
  v1.6.1 paper/shadow runbook clarity without contacting a broker, submitting
  or cancelling orders, creating live fills, mutating OMS beyond existing
  paper/shadow transitions, writing production ledger facts, enabling automatic
  trading, or bypassing manual confirmation.
- 2026-07-06: Operations Today now exposes a paper/shadow `effective_status`
  for runbook display. Accepted divergence reviews keep the raw
  `status=diverged` and `divergence_status=diverged` for audit, while
  `effective_status=accepted_for_manual_confirmation` lets Decision show a
  clear manual-confirmation handoff instead of a stale diverged badge.
  Assumption: `effective_status` is display/runbook guidance only; raw
  divergence evidence remains authoritative for review. Risk impact: improves
  paper/shadow handoff clarity without contacting a broker, submitting or
  cancelling orders, mutating OMS or production ledger facts, enabling
  automatic trading, or bypassing manual confirmation.
- 2026-07-06: Trading execution audit now renders the latest paper/shadow
  run's evidence references with public labels in the read-only latest-run
  card. The frontend operations contract now includes `paper_shadow.evidence_refs`
  so the run id, counts, divergence refs, and immutable evidence refs can be
  reviewed together. Assumption: evidence refs identify stored simulation
  artifacts for human audit only. Risk impact: improves traceability only; it
  does not contact a broker, submit or cancel broker orders, create live fills,
  mutate OMS or production ledger facts, enable automatic trading, or bypass
  manual confirmation.
- 2026-07-06: Overview Today's to-dos now treats accepted paper/shadow
  divergence reviews and within-expectations paper/shadow runs as handoffs to
  manual order confirmation, even when the daily trading plan subsystem is
  also manual-action-required. The operations card shows the public "Review
  manual order confirmation" step and keeps the `/trading` route without
  exposing raw review or OMS status codes. Assumption: accepted or
  within-expectations paper/shadow evidence means the operator may continue
  reviewing the manual-confirmation queue, not that execution is authorized
  automatically. Risk impact: improves runbook handoff clarity only; it does
  not contact a broker, submit or cancel broker orders, create live fills,
  mutate OMS or production ledger facts, enable automatic trading, or bypass
  manual confirmation.
- 2026-07-06: Trading execution audit now shows the latest paper/shadow run as
  read-only evidence, including run id, public status, order-intent/simulated
  order/fill counts, public next action, mapped divergence references,
  simulated slippage cost, and explicit no-broker-submission/no-ledger-mutation
  safety boundaries. The rich divergence-report acceptance audit now validates
  Trading together with Overview and Decision. Assumption: Trading uses this
  latest-run summary to support human review before manual confirmation; it
  does not authorize execution. Risk impact: improves execution-review
  visibility only; it does not contact a broker, submit or cancel broker
  orders, create live fills, mutate OMS or production ledger facts, enable
  automatic trading, or bypass manual confirmation.
- 2026-07-06: Overview Today's to-dos now appends a compact paper/shadow
  divergence evidence summary when the runbook is waiting on divergence
  review or resolution. The summary shows order-intent/simulated order/fill
  counts, mapped divergence references, simulated slippage cost, and the
  no-broker-submission boundary without exposing raw OMS state codes. The
  operations-runbook acceptance audit now validates this Overview surface
  alongside the Decision panel. Assumption: Overview remains a triage surface
  that points the operator to review evidence; it does not decide whether to
  trade. Risk impact: improves daily review routing only; it does not contact
  a broker, submit or cancel broker orders, create live fills, mutate OMS or
  production ledger facts, enable automatic trading, or bypass manual
  confirmation.
- 2026-07-06: Decision Cockpit now renders rich paper/shadow divergence
  evidence in the daily trading plan panel: expected strategy behavior,
  simulated execution comparison, realized market context, cost evidence, and
  explicit non-submission/non-ledger-mutation safety boundaries. The
  operations-runbook acceptance audit now records the Decision frontend test
  and build as validation for this report surface. Assumption: this panel is a
  human review surface for existing simulation evidence only. Risk impact:
  improves operator review clarity only; it does not contact a broker, submit
  or cancel broker orders, create live fills, mutate OMS/production ledger
  facts, enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Paper/shadow divergence summaries now include richer comparison
  evidence for expected strategy behavior, simulated execution, current
  account-truth state, realized market context, cost evidence, and explicit
  non-submission/non-ledger-mutation safety flags. Assumption: the report is
  derived from the existing daily trading plan, simulated paper orders, and
  simulated paper fills; it does not fetch live market data, contact a broker,
  submit or cancel broker orders, or mutate ledger, cash, positions, broker
  evidence, or manual orders. Risk impact: improves operator review quality
  for paper/shadow divergence only; it does not enable automatic trading,
  live broker submission, or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now accepts runtime read-only broker
  connector health snapshots and records degraded, stale, unavailable,
  disconnected, failed, or heartbeat-stale states as acknowledgeable operations
  alerts. The alert preserves connector id/type, capability flags, heartbeat
  timestamp, last error, limitations, manual-review requirement, and explicit
  `does_not_submit_broker_order=true` evidence. Assumption: the scan consumes
  an existing connector health snapshot and does not poll a broker client,
  store credentials, submit or cancel broker orders, or mutate OMS, broker
  evidence, ledger, cash, or positions. Risk impact: improves operator
  visibility into connector runtime degradation only; it does not enable live
  broker submission, automatic trading, or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now accepts a paper/shadow run
  snapshot and records diverged, failed, or review-required simulation states
  as acknowledgeable operations alerts. The alert preserves run id, plan date,
  order/fill counts, missing simulation count, diverged order count, next
  manual review step, evidence references, limitations, and explicit
  `does_not_submit_broker_order=true` /
  `does_not_mutate_production_ledger=true` evidence. Assumption: the scan
  consumes an existing paper/shadow run snapshot and does not rerun simulation
  or mutate OMS, ledger, cash, positions, broker evidence, or manual orders.
  Risk impact: improves operator visibility into paper/shadow divergence only;
  it does not contact a broker, submit or cancel broker orders, create new OMS
  orders, mutate production ledger facts, enable automatic trading, or bypass
  manual confirmation.
- 2026-07-06: Automation alert scanning now accepts an Account Truth score
  snapshot and records degraded, blocked, or unresolved-mismatch states as
  acknowledgeable operations alerts. The alert preserves gate status, score,
  component statuses, data freshness, unresolved mismatch count, required
  review actions, blocking reasons, manual-review requirement, and explicit
  `does_not_submit_broker_order=true` /
  `does_not_mutate_production_ledger=true` evidence. Assumption: the scan
  consumes an existing Account Truth snapshot and does not recompute
  reconciliation or modify ledger state. Risk impact: improves operator
  visibility into account-truth mismatches only; it does not contact a broker,
  submit or cancel broker orders, create OMS orders, mutate production ledger
  facts, enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now accepts a market-data health
  snapshot and records stale/cache/missing/estimated market-data states as
  acknowledgeable operations alerts. The alert preserves source health,
  provider status, persistent-cache status, stale-symbol counts and samples,
  next action, manual-review requirement, and
  `does_not_submit_broker_order=true` evidence. Assumption: the scan consumes
  an existing `/api/market/data-health`-style snapshot and does not refresh
  market data or make trading decisions. Risk impact: improves operator
  visibility into stale market evidence only; it does not contact a broker,
  submit or cancel broker orders, create OMS orders, mutate production ledger
  facts, enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now accepts a daily trading-plan
  snapshot and records risk-blocked plans as acknowledgeable operations alerts.
  The alert preserves the plan date, blocked count, risk blocker count,
  specific risk reasons, manual-review requirement, and
  `does_not_submit_broker_order=true` evidence. Assumption: the scan consumes
  the already-built trading-plan preview and does not change risk decisions or
  promote blocked orders. Risk impact: improves operator visibility into risk
  blockers only; it does not contact a broker, submit or cancel broker orders,
  create OMS orders, mutate production ledger facts, enable automatic trading,
  or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now records incomplete read-only
  broker connector health as acknowledgeable operations alerts. The alert uses
  the existing Broker Gateway connector-health contract, preserves connector
  capabilities, credential-storage status, and `submitted_to_broker=false`
  evidence, and `/api/automation/alerts/scan` now reads connector config from
  local app state. Assumption: connector health is a local configuration
  review signal only; Karkinos does not open the broker client, verify a live
  session, or store credentials. Risk impact: improves operator visibility
  into degraded bridge readiness only; it does not contact a broker, submit or
  cancel broker orders, mutate OMS state, mutate production ledger facts,
  enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Automation alert scanning now records failed paper/shadow
  automation runs as acknowledgeable operations alerts. The alert preserves
  the run id, execution mode, retry state, limitations, and explicit
  `does_not_submit_broker_order` / `does_not_mutate_production_ledger`
  evidence, and Automation Cockpit can surface it through the existing
  read-only open-alert summary. Assumption: a failed paper/shadow automation
  run is local runbook evidence requiring operator review, not broker
  execution authority. Risk impact: improves scheduler failure visibility and
  alert review only; it does not contact a broker, submit or cancel broker
  orders, mutate OMS state, mutate production ledger facts, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-06: Acceptance audit export now includes an
  `operations_runbook` manifest for the completed Operations Center and
  paper/shadow runbook capabilities. The manifest records evidence and
  validation commands for the daily runbook, scheduler run persistence,
  paper/shadow run storage, paper/shadow OMS lifecycle, simulation outcomes,
  run-level review outcomes, frontend next-action surfaces, automation run
  failure alerts, connector-health alerts, daily-plan risk-blocker alerts, and
  safety documentation.
  Assumption: this audit marks only the listed completed
  capabilities as evidenced and does not mark the entire v1.6 roadmap as
  complete. Risk impact: improves release-review evidence only; it does not
  submit broker orders, mutate OMS order state, mutate production ledger
  facts, enable automatic trading, or bypass manual confirmation.
- 2026-07-06: Trading approvals now surfaces the latest Operations
  paper/shadow run review state in the execution audit panel. When the latest
  run needs simulation-review attention, the panel can record an accepted
  run-level review through `/api/operations/paper-shadow/runs/{run_id}/review`
  and then shows a user-readable prompt to continue with manual confirmation.
  The panel hides raw review/state-machine codes and removes the action once
  the review is accepted. Assumption: this UI action records local operator
  review evidence only. Risk impact: improves the paper/shadow runbook review
  loop; it does not submit broker orders, mutate OMS order state, mutate
  production ledger facts, enable automatic trading, or bypass manual
  confirmation.
- 2026-07-06: Paper/shadow runs now have a run-level operator review outcome.
  `paper_shadow_runs` records can store review status, timestamp, notes, and
  reviewer, and `/api/operations/paper-shadow/runs/{run_id}/review` records an
  immutable audit event for the review. An accepted run review preserves the
  original run `status` and `divergence_status` as audit evidence, but lets
  `/api/operations/today` treat the paper-shadow gate as reviewed so the daily
  runbook can return to manual-confirmation review. Assumption: this review is
  local operator evidence only and does not convert a diverged simulation into
  broker-safe execution authority. Risk impact: closes the paper/shadow
  runbook review loop only; it does not submit broker orders, mutate OMS order
  state, mutate production ledger facts, enable automatic trading, or bypass
  manual confirmation.
- 2026-07-06: `/api/operations/today` now treats a running persisted
  paper/shadow run as an in-progress wait state. If the run has no explicit
  next step, the paper-shadow subsystem emits `wait_for_paper_shadow_run`,
  the daily runbook conclusion prioritizes that degraded waiting state ahead
  of otherwise manual-ready order intents, and the Decision/Overview UI renders
  localized "simulation is running; wait for completion" copy instead of a raw
  internal code. Assumption: a running paper/shadow row is local simulation
  evidence in progress and must complete before manual confirmation is
  actionable. Risk impact: improves operator guidance only; it does not submit
  broker orders, mutate OMS or production ledger facts, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-06: Paper/shadow simulated orders now also create deterministic OMS
  order records keyed by the paper/shadow order id and run id. The OMS service
  supports a separate paper/shadow lifecycle (`staged`, `submitted`,
  `accepted`, `partially_filled`, `filled`, `rejected`, `cancelled`,
  `expired`, `reconciled`) while preserving the existing manual-confirmation
  lifecycle and continuing to reject disabled broker submission for manual
  orders. Execution reconciliation classifies `paper_shadow` OMS records as
  simulation evidence with no broker-action requirement, so paper/shadow runs
  do not create false live-execution exceptions. Assumption: paper/shadow OMS
  records remain local simulation evidence and are not used as broker
  submission authority. Risk impact: improves lifecycle auditability and
  reconciliation separation only; it does not submit broker orders, mutate
  production ledger facts, or bypass manual confirmation.
- 2026-07-06: `/api/operations/today` now surfaces the latest
  `market_session` automation run as a scheduler summary with run id,
  status, execution mode, last-run timestamp, input fingerprint, idempotency
  key, compact input snapshot, retry state, error payload, and limitations.
  The scheduler subsystem maps failed runs to a blocked runbook state and an
  `inspect_scheduler_failure` next action, while skipped non-trading sessions
  remain skipped and completed runs remain pass. Assumption: only same-day
  market-session runs are shown in the daily runbook to avoid stale scheduler
  evidence. Risk impact: improves operator visibility into scheduler failures
  and rerun evidence only; it does not submit broker orders, mutate production
  ledger facts, or bypass manual confirmation.
- 2026-07-06: Market-session automation run records now persist a compact
  scheduler input snapshot, SHA-256 input fingerprint, idempotency key, and
  retry state for each run. Paper/shadow failures are captured as
  `paper_shadow_failed` automation runs with error type/message while leaving
  paper/shadow result rows absent and broker submission disabled. Assumption:
  this scheduler uses local weekday/intraday A-share session checks until an
  official holiday calendar is wired in. Risk impact: improves auditability
  and replay/debug evidence only; it does not submit broker orders, mutate
  production ledger facts, or bypass manual confirmation.
- 2026-07-01: Daily trading plan blockers now include a stable
  `blocker_summary` grouped by account truth, market/NAV data, portfolio
  constraints, risk gate, evidence-not-ready, and other blockers. Overview
  "Today's to-dos" uses that summary instead of showing a raw blocked total,
  so large candidate pools are presented as upstream evidence or gate work
  rather than dozens of manual trading actions. This is display and
  observability only; it does not bypass account truth, market data, risk, or
  manual-confirmation gates.
- 2026-07-01: Added the initial read-only operations runbook surface via
  `/api/operations/today`. The API aggregates the current daily decision,
  daily trading plan, operations summary, order facts, and fill facts into
  subsystem health, next action, limitations, daily-plan counts, and
  paper/shadow simulation-review status. Overview "Today's to-dos" now
  surfaces the runbook status and next manual step, while the Decision daily
  trading plan panel shows paper/shadow order-intent, simulated-order,
  simulated-fill, divergence-review, and next-review-step summary. This is
  observability and review guidance only; it does not create orders/fills,
  mutate ledger entries, submit broker orders, or bypass manual confirmation.

## v1.5 Planning

- 2026-07-01: Daily trading plan implementation now exposes a read-only
  `/api/decision/trading-plan` surface and a Decision cockpit panel for
  manual-confirmation order-intent previews. The plan separates candidate pool
  count, manual-ready count, and blockers; estimates quantity, gross amount,
  fees, net cash impact, remaining position, and cost-basis effect; and marks
  buy intents with insufficient cash as portfolio blockers instead of manual
  confirmation candidates. Broker bridge status remains disabled, the API does
  not create orders/fills/ledger entries, and the UI states that previews do
  not submit broker orders.
- 2026-07-01: The Overview "Today's to-dos" queue now reads the daily trading
  plan when summarizing the decision-review item. Large candidate pools remain
  visible as research context, while only `manual_ready_count` is presented as
  work that can move toward manual confirmation; cash shortfalls and other
  blockers are prioritized ahead of ordinary watch items. This is still
  read-only review and navigation, not broker execution.
- 2026-07-01: Daily trading plan order intents now carry explicit pre-trade
  constraint checks for trading unit, fee/tax preview, cash buffer,
  concentration, T+1 sellable quantity, limit up/down state, suspension,
  special-treatment risk, drawdown, and fund NAV latency. Blocking constraint
  checks remove the intent from manual-ready counts and create targeted
  portfolio, risk, or market blockers. The Decision cockpit renders these
  constraints as localized read-only evidence and keeps broker submission
  disabled.
- 2026-07-01: Roadmap documentation was realigned around Daily Trading Plan &
  Portfolio Construction as the active v1.5 milestone. The intended product
  progression is daily evidence-linked trading plans, then scheduled
  paper/shadow operations, then a controlled broker bridge or order-ticket
  export. Manual confirmation remains the default boundary, broker submission
  remains disabled, and unattended real-money automation remains deferred. This
  is documentation planning only and does not change runtime behavior.

## v1.4 Progress

- 2026-06-27: Portfolio holding strategy-attribution cards now show a concrete
  next review step even when holding-level attribution readiness evidence is
  unavailable. The card points the user back to the single-instrument Strategy
  Lab flow for the current holding and explains that signal, risk, simulation,
  and attribution evidence should be reviewed together before strategy P/L can
  be assigned. This is read-only guidance and navigation only; it does not
  create orders, mutate production ledger entries, submit broker orders,
  enable automatic trading, or bypass manual confirmation.
- 2026-06-27: Backtest signal preview now groups the selected symbol's
  research data basis into a user-readable evidence block. It shows the
  formatted dataset snapshot reference, the underlying snapshot id for audit
  traceability, and the signal-preview data quality status together before
  risk preview or paper/shadow simulation. This improves the
  data-trusted single-instrument loop without changing backtest execution,
  strategy signal generation, risk gates, paper/shadow simulation, production
  ledger entries, broker submission, automatic trading defaults, or manual
  confirmation behavior.
- 2026-06-27: Decision signal journal entries now show structured source
  evidence references through the shared public evidence formatter and link
  each logged signal back to the single-instrument Backtest evidence view and
  symbol-scoped holding attribution review. Unstructured raw source references
  are not displayed as user-facing evidence labels. This is read-only
  navigation and presentation only; it does not create orders, mutate
  production ledger entries, submit broker orders, claim strategy P/L
  attribution, enable automatic trading, or bypass manual confirmation.
- 2026-06-27: Decision signal action queue cards now link each persisted
  signal action back to its single-instrument Backtest evidence view and
  symbol-scoped holding attribution review. The links preserve symbol, asset
  class, and strategy parameters where available, so users can move from a
  daily signal task to the same read-only research and attribution evidence
  chain before preparing any manual order. This is navigation-only and does not
  create orders, mutate production ledger entries, submit broker orders, enable
  automatic trading, or bypass manual confirmation.
- 2026-06-27: Decision candidate cards now expose risk-gate reasons as
  localized read-only evidence when a candidate is blocked or degraded. Known
  risk reason codes render through shared public labels and unknown backend
  reason codes fall back to review-note wording instead of raw identifiers.
  This strengthens the single-instrument signal-to-risk-gate explanation
  without changing signal generation, risk decisions, paper/shadow isolation,
  production ledger entries, broker submission, automatic trading defaults, or
  manual-confirmation behavior.
- 2026-06-27: Decision workflow cards now format required actions and blocking
  reasons through separate public-label paths. Required actions remain
  user-facing next steps, while blocking reasons render as localized review
  notes, so future backend reason codes do not leak into the Decision cockpit
  as raw internal identifiers or misleading action chips. The single-instrument
  strategy-loop acceptance audit now includes Decision cockpit source and tests
  in the user-readable surface contract. This is presentation and audit
  coverage only; it does not change signal generation, risk gates,
  paper/shadow isolation, production ledger entries, broker submission,
  automatic trading defaults, or manual-confirmation behavior.
- 2026-06-26: Shared Web public labels now use one Chinese term,
  "simulation review" / `模拟复核`, for paper/shadow review evidence across
  Backtest, Decision, and Trading surfaces. The shared formatter maps backend
  `paper_shadow_*` codes and known paper/shadow notes to localized public copy,
  and Backtest copy tests prevent the older mixed terms from reappearing. This
  is UI wording only and keeps API paths, schema versions, ledger isolation,
  broker submission, and manual-confirm defaults unchanged.
- 2026-06-26: Web Trading Chinese execution-audit copy now uses the same
  simulation-review wording as Backtest for the post-risk paper/shadow review
  stage. The Trading page keeps the existing daily shadow-run API and ledger
  isolation but no longer presents the Chinese UI as a separate "simulation
  replay" concept. Deterministic Trading tests assert the localized title,
  action button, result banner, and absence of `shadow` jargon in rendered
  Chinese text.
- 2026-06-26: Web Backtest Chinese copy now presents the paper/shadow preview
  step as localized simulation-review language in the single-instrument
  strategy loop. The UI describes the post-risk simulated review, simulated
  order/fill evidence, and no-ledger-mutation boundary without exposing the
  `paper/shadow` jargon to Chinese users. This is a copy-only presentation
  change and does not alter API paths, strategy runtime behavior, risk gates,
  paper/shadow isolation, ledger mutation rules, broker submission, or
  automatic real-money trading defaults.
- 2026-06-26: Web Backtest run configuration now includes a localized
  pre-run single-instrument readiness summary before submission. It shows the
  selected strategy, strategy source, instrument, asset class, configured
  parameter count, and the boundary that the dataset snapshot is frozen when
  the backtest runs. This is a research-input review surface only and does not
  run strategies, create orders or fills, mutate the ledger, submit broker
  orders, or enable automatic real-money trading.
- 2026-06-26: Web Backtest strategy catalog now labels each registry entry as
  a built-in strategy or local extension using localized user-facing copy. This
  makes custom strategy discovery clearer in the single-instrument research
  loop while keeping strategy source fields as audit metadata only; it does not
  execute extension code from the browser, submit broker orders, mutate the
  ledger, or enable automatic real-money trading.
- 2026-06-26: Web Backtest attribution preview now renders a localized,
  user-readable evidence-chain card for strategy signal, dataset snapshot,
  risk-gate preview, paper-shadow order, and paper-shadow fill evidence. The
  card derives readiness from evidence refs and counts but hides raw internal
  refs such as `signal_preview:*`, `dataset_snapshot:*`, and
  `risk_preview:*` from the workflow UI. This is display-only and does not
  create orders, fills, ledger entries, broker submissions, or automatic
  real-money trading.
- 2026-06-26: Backtest attribution preview evidence refs now include the
  read-only risk-gate preview reference alongside signal, dataset,
  paper-shadow order, and paper-shadow fill refs. This tightens the
  single-instrument audit chain from signal through risk and paper/shadow
  evidence before any manual attribution review, without creating orders,
  fills, ledger entries, broker submissions, or automatic real-money trading.
- 2026-06-26: Web Backtest attribution preview now reads the same structured
  holding-level attribution prerequisites used by Portfolio holding detail.
  After paper/shadow preview evidence is available, the Backtest page surfaces
  the holding attribution readiness, first missing prerequisite, and localized
  next manual review step before users leave the single-instrument loop. This
  is a read-only evidence handoff and does not create orders, fills, ledger
  entries, broker submissions, or automatic real-money trading.
- 2026-06-26: Portfolio holding attribution readiness now surfaces the next
  manual review action for the first missing prerequisite, routing users back
  to the single-instrument strategy loop, Decision review, or execution review
  as appropriate. The action is navigation-only and localized; it does not
  create orders, fills, ledger entries, broker submissions, or automatic
  real-money trading.
- 2026-06-26: Holding-level strategy attribution reports now include
  structured review prerequisites for strategy signal, candidate action, risk
  gate, manual review, order evidence, and fill evidence. Portfolio holding
  detail consumes those typed prerequisites instead of inferring readiness from
  audit-reference string prefixes, keeping the review boundary deterministic
  and localized. This is read-only evidence surfacing; it does not mutate
  attribution records, ledger facts, broker state, risk gates, or trading
  behavior.
- 2026-06-26: Decision candidate cards now include a localized, symbol-scoped
  handoff to the holding attribution review section. This lets a daily
  candidate continue into the same holding-level attribution boundary used by
  Backtest paper/shadow evidence. It is navigation-only and does not create
  orders, fills, ledger entries, broker submissions, or automatic real-money
  trading.
- 2026-06-26: Web Backtest attribution preview now links directly to the
  matching holding's strategy-attribution review section after paper/shadow
  evidence is generated. The link is localized, symbol-scoped, and anchored to
  the holding attribution boundary so users can continue the single-instrument
  loop without hunting through pages. This is navigation-only: it does not
  create orders, fills, ledger entries, broker submissions, or automatic
  real-money trading.
- 2026-06-26: The `single_instrument_strategy_loop` acceptance audit now
  includes holding-level attribution review readiness. The manifest points to
  the read-only holding attribution API, localized evidence-chain display, and
  deterministic backend/frontend tests that prove symbol-filtered evidence is
  visible before any strategy P/L claim. This does not mutate ledger records,
  submit broker orders, or enable automatic real-money trading.
- 2026-06-25: Web strategy-contribution surfaces now include a stable
  localized explanation that only linked signal, review, order, and fill
  evidence is counted while manual trades and cash flows remain separate.
  Decision summaries also keep contribution status user-readable in English
  and Chinese. Internal strategy identifiers remain secondary audit labels.
  This is display-only and does not change contribution math, attribution
  gates, ledger records, broker submission, or automatic trading behavior.
- 2026-06-25: Added a read-only acceptance audit API surface for
  `single_instrument_strategy_loop` and moved the audit registry / JSON export
  builder into shared analytics code. The Backtest readiness card now fetches
  live audit manifest metadata instead of hardcoding the 8/8 coverage count.
  The API is review-only: it writes no report artifact, does not mutate the
  ledger, does not submit broker orders, and does not enable automatic
  real-money trading.
- 2026-06-25: Web Backtest now surfaces the
  `single_instrument_strategy_loop` acceptance audit coverage directly inside
  the single-instrument readiness card. Users can see the verified
  product-readiness criteria without reading CLI JSON, with explicit wording
  that the audit does not enable broker execution and is not investment advice.
- 2026-06-25: The Data-Trusted Single-Instrument Strategy Loop acceptance
  audit now includes an explicit Web boundary criterion for the post-risk
  paper/shadow next step and the rule that strategy P/L attribution stays
  blocked when production fills are not linked. The capability-based
  `single_instrument_strategy_loop` CLI export covers this evidence without
  introducing broker submission, ledger mutation, or automatic real-money
  trading.
- 2026-06-25: Web Backtest now makes the post-risk paper/shadow step and
  attribution boundary more explicit in the single-instrument research loop.
  Once a risk preview passes, the UI tells users to run paper/shadow simulation
  before any manual step, and attribution preview highlights that strategy P/L
  stays unavailable when no production fill facts are linked. This is
  explanatory UI only; it does not create broker orders, mutate the production
  ledger, or enable automatic real-money trading.
- 2026-06-25: Web Backtest single-instrument loop readiness now includes a
  localized next-review-step guide. After a run produces signal evidence, the
  card tells the user whether to inspect after-cost evidence, wait for signal
  preview, run risk preview, run paper/shadow simulation, or review the
  attribution boundary, without exposing internal reason codes or triggering
  broker execution.
- 2026-06-25: Web Backtest now shows a localized Decision handoff context
  panel when opened from a candidate action with `symbol`, `assetClass`, or
  `strategy` query parameters. The panel summarizes the carried instrument,
  asset class, and strategy and explicitly marks the flow as research-only so
  users can continue from daily candidate review into reproducible after-cost
  research without mistaking it for broker execution.
- 2026-06-25: Decision candidate Backtest evidence links now carry
  single-instrument context through `symbol`, `assetClass`, and `strategy`
  query parameters, and the Web Backtest page reads those values as initial
  form defaults. This lets a daily candidate hand off to a reproducible
  after-cost research run for the same instrument and strategy without manual
  re-entry. It is UI/default-state plumbing only; it does not create signals,
  orders, fills, ledger entries, broker submissions, or change
  automatic-trading defaults.
- 2026-06-25: Decision candidate cards now provide localized handoff links
  from each candidate to Backtest evidence, the single-instrument holding
  detail page, and Trading approvals when manual confirmation is ready. This
  makes the single-instrument strategy loop easier to follow from a daily
  candidate back to research evidence and position context. It is navigation
  only; it does not create signals, orders, fills, ledger entries, broker
  submissions, or change automatic-trading defaults.
- 2026-06-25: Decision workflow task cards now include localized handoff
  links to existing review surfaces for market data, risk review, Strategy
  Lab/backtest evidence, paper/shadow review, and trading approvals. This
  helps the single-instrument strategy loop move from daily decision review
  back to the relevant evidence surface without exposing internal workflow
  codes. It is navigation only; it does not create signals, orders, fills,
  ledger entries, broker submissions, or change automatic-trading defaults.
- 2026-06-25: Web Backtest now renders a localized single-instrument loop
  readiness card for the current result. The card summarizes dataset snapshot,
  strategy registry, after-cost backtest, signal preview, risk gate,
  paper/shadow simulation, and attribution-boundary evidence as user-readable
  review states without exposing internal reason codes. It is display and
  review guidance only; it does not mutate ledger entries, create orders or
  fills, submit broker orders, claim strategy P/L, or change automatic-trading
  defaults.
- 2026-06-25: Added a capability-based acceptance audit manifest and CLI
  registry entry for the data-trusted single-instrument strategy loop. The
  audit covers dataset snapshot and strategy registry evidence, one-symbol
  after-cost backtest, signal preview, risk preview, paper/shadow preview,
  attribution-preview boundary, and localized Web Backtest surfaces. This is
  deterministic audit coverage for the read-only preview chain; it does not
  claim production strategy P/L, mutate ledger entries, submit broker orders,
  or change automatic-trading defaults.
- 2026-06-25: Backtest now exposes a read-only attribution evidence preview
  after the single-symbol signal, risk, and paper/shadow preview chain. The
  backend reports preview evidence counts, production order/fill fact counts,
  evidence refs, next review action, and keeps `can_attribute_pnl=false` until
  real signal, review, order, and fill facts are linked. Web Backtest renders
  the preview boundary after paper/shadow simulation with localized copy. This
  does not write order facts, fill facts, ledger entries, broker submissions,
  or claim strategy P/L.
- 2026-06-25: Backtest now exposes a read-only paper/shadow preview after a
  passed single-symbol risk preview. The backend route builds paper order/fill
  simulation evidence with structured fee breakdown and a shadow-review
  summary without passing a database handle to the paper broker. Web Backtest
  renders the simulated fill, estimated fee, and no-ledger-mutation boundary
  after the user sizes a candidate and runs risk preview. This does not write
  order facts, fill facts, ledger entries, broker submissions, or change
  automatic-trading defaults.
- 2026-06-25: Backtest now exposes a read-only pre-trade risk preview for
  sized single-symbol strategy candidates. The backend route reuses
  `PreTradeRiskManager` rule inputs through a pure preview function and the
  Web Backtest page lets users enter a quantity, run the preview, and see
  localized pass/blocked reasons such as kill-switch status. The response
  explicitly requires manual confirmation and does not create orders, persist
  risk decisions, create fills, mutate ledger entries, submit broker orders,
  or change automatic-trading defaults.
- 2026-06-25: Strategy signal-preview audit records now include a structured
  review-gate chain for data readiness, account truth, pre-trade risk,
  paper/shadow preview, and manual review. Web Backtest renders those gates as
  localized user-facing review states after a single-symbol run, without
  exposing internal reason codes. This is audit and review guidance only; it
  does not run a sized pre-trade order intent, create paper or live orders,
  persist signals, mutate ledger entries, submit broker orders, or change
  automatic-trading defaults.
- 2026-06-25: Added a research-only Backtest signal-preview path that runs a
  registered strategy over explicit single-symbol bars or server-side
  single-symbol date ranges, validates the same parameter schema as backtests,
  and returns strategy-runtime audit records with dataset snapshot and
  data-quality context. Web Backtest now shows the preview after a
  single-symbol research run. Candidate records require downstream risk,
  account-truth, paper/shadow, and manual-review gates and explicitly do not
  enable execution. This preview does not persist signals, create action tasks,
  create paper or live orders, create fills, mutate ledger entries, submit
  broker orders, or change automatic-trading defaults.
- 2026-06-25: Web Backtest equity/drawdown charts now consume saved fill
  records, overlay buy/sell markers, and show a compact marker summary with
  localized side labels, symbol, price, time, and quantity. The markers are
  report display evidence only and do not change strategy math, fills,
  attribution, broker behavior, order submission, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
- 2026-06-24: Backtest validation evidence now shows localized strategy names
  as the primary OOS strategy value and keeps raw strategy ids in a separate
  audit-id field. Backtest strategy snapshot cards follow the same convention:
  primary strategy text is localized and the raw id remains audit metadata.
  Web surfaces no longer consume the combined strategy audit-label helper
  directly, so internal ids stay secondary in Backtest and Decision review
  text. This is display formatting only; it does not change research evidence,
  OOS calculations, strategy ids, broker behavior, order submission, risk
  gates, automatic trading defaults, or manual-confirmation requirements.
- 2026-06-24: Decision candidate cards, candidate evidence chains, and signal
  journal rows now keep localized strategy names as the primary user-facing
  text and show raw strategy ids only as secondary audit ids. This removes
  combined labels such as "strategy name · strategy id" from the main
  decision workflow while preserving traceability. This is display formatting
  only; it does not change decision evidence, signal records, strategy ids,
  broker behavior, order submission, risk gates, automatic trading defaults,
  or manual-confirmation requirements.
- 2026-06-24: Decision strategy-attribution gate summaries now show the
  localized strategy name in the primary status value and move the raw
  strategy id into the detail line as an audit id. This keeps decision
  summaries readable while preserving the review key. This is display
  formatting only; it does not change decision evidence, attribution math,
  strategy ids, broker behavior, order submission, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
- 2026-06-24: Strategy contribution cards now show localized strategy names as
  the primary label and move the raw strategy id into a smaller audit-id line.
  This keeps contribution evidence user-readable while preserving the
  underlying strategy key for review. This is display formatting only; it does
  not change strategy attribution math, evidence gating, strategy ids, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-24: Activity manual-trade preview now keeps generated fee-rule
  notes out of the visible panel once gross amount, commission, stamp tax,
  transfer fee, total fee, net cash impact, fee-rule label, and cost-basis
  method are already shown as structured fields. This is display formatting
  only; it does not change fee calculation, ledger persistence, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-24: Backtest account-strategy and strategy-review tables now use
  localized strategy names as the primary display even when registry metadata
  is incomplete, while strategy ids remain visible only as secondary audit
  keys where needed. This is display formatting only; it does not change
  strategy assignment, strategy ids, attribution math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-24: Public ledger notes now localize raw internal note-code
  segments through the shared ledger formatter instead of rendering backend
  reason-code text in Activity, Overview dashboard, explainability, and
  holding ledger traces. User-authored free-text notes remain unchanged. This
  is display formatting only; it does not change ledger persistence, fee
  calculation, cost-basis math, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
- 2026-06-24: Portfolio positions and holding-detail cost-basis method labels
  now use the shared ledger formatter. Unknown future broker cost-basis method
  ids fall back to localized review copy instead of leaking raw backend codes
  in portfolio cost views, while existing broker displayed cost, projected
  ledger cost, local moving-average cost, difference, and status display stay
  unchanged. This is display formatting only; it does not change cost-basis
  math, ledger projection, broker evidence, fee calculation, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
- 2026-06-24: Shared Web ledger formatting now owns public labels for manual
  fee-rule ids and cost-basis method ids. The Activity manual-trade preview
  consumes those shared labels instead of carrying its own local mapping, so
  configured account fee rules, manual fee overrides, moving-average cost,
  broker displayed remaining cost, and unknown future ids use the same
  localized public fallback path as other ledger evidence. This is display
  formatting only; it does not change fee calculation, cost-basis math,
  ledger persistence, broker behavior, risk gates, automatic trading defaults,
  or manual-confirmation requirements.
- 2026-06-24: Activity manual-trade entry now previews the same configured
  fee contract used by ledger persistence before the user saves a trade. The
  preview shows gross amount, commission, stamp tax, transfer fee, total fee,
  net cash impact, fee-rule label, and cost-basis method while the backend
  preview route deliberately avoids writing trades, ledger entries, or broker
  orders. This is pre-save evidence surfacing only; it does not change ledger
  persistence, broker behavior, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-24: Backtest run-configuration and strategy snapshot copy now
  describes the backend boundary as a user-facing interface boundary and
  labels strategy ids as audit metadata instead of internal implementation
  identifiers. Chinese strategy metadata uses the same audit-id framing. This
  is copy-only and does not change backtest payloads, strategy ids, report
  persistence, strategy math, broker behavior, risk gates, automatic-trading
  defaults, or manual-confirmation requirements.
- 2026-06-24: Shared public-note formatting now localizes Account Truth
  evidence limitation phrases about staged broker evidence and unresolved
  reconciliation review in both English and Chinese. Decision, Backtest,
  Risk, and Account Truth surfaces that consume `formatPublicNote` can reuse
  the same user-readable text instead of leaking backend limitation wording.
  This is display formatting only; it does not change account-truth scoring,
  reconciliation math, broker evidence persistence, API paths, trading
  behavior, risk gates, automatic-trading defaults, or manual-confirmation
  requirements.
- 2026-06-24: Backtest asset-class controls now display localized asset labels
  such as Stock/Fund or 股票/基金 while preserving the backend enum payload for
  API compatibility. Adjacent Backtest asset-entry helper copy was also updated
  to avoid exposing raw `asset_class` field names in user-facing guidance. This
  is display/input guidance only; it does not change strategy math, backtest
  API paths, broker behavior, order submission, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
- 2026-06-24: Saved Backtest dataset-snapshot tables now reuse the shared
  asset-class formatter so report rows display localized labels instead of raw
  backend enum values. The underlying dataset snapshot schema, API payloads,
  report persistence, strategy math, broker behavior, risk gates, and
  manual-confirmation defaults are unchanged.
- 2026-06-24: Backtest Chinese run-configuration copy now describes the
  backend contract as a user-readable interface boundary instead of leaking the
  English implementation term `contract`. This is copy-only and does not change
  request payloads, API paths, strategy math, broker behavior, risk gates,
  automatic-trading defaults, or manual-confirmation requirements.
- 2026-06-24: Shared Web submit-error copy now avoids developer-facing
  payload/server-log wording in both English and Chinese. The router fallback
  uses the same user-readable form/service-status language. This is copy-only
  and does not change form validation, request payloads, API paths, broker
  behavior, risk gates, automatic-trading defaults, or manual-confirmation
  requirements.
- 2026-06-24: Account strategy contribution cards and the Backtest account
  strategy panel now format missing-valuation warnings with readable
  instrument labels from current holdings when available, keeping the symbol
  as secondary audit context and falling back to the raw symbol only when no
  local name is known. This is display-only evidence surfacing; it does not
  change strategy contribution math, valuation data, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-24: Backtest strategy evidence gates now merge promotion-review
  rows with validation-matrix rows, so readiness-only strategies remain
  visible with display names first and internal strategy ids as secondary
  audit labels. This is display-only evidence surfacing; it does not change
  strategy promotion rules, attribution math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-24: Account strategy contribution cards now surface backend
  limitation notes through the shared public-note formatter, so strategy
  contribution estimates explain linked-fill, quote, manual-trade, and
  cash-flow boundaries in user-facing language instead of raw backend
  wording. This is display formatting only; it does not change attribution
  math, strategy assignment, broker behavior, order submission, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
- 2026-06-24: Trading execution audit fill facts now parse structured
  fill metadata and reuse the shared public ledger execution-detail formatter
  for gross amount, net cash impact, quantity, price, commission, stamp tax,
  transfer fee, and other fee display. Internal fee-rule identifiers remain
  hidden from user-facing fill cards. This is display formatting only; it does
  not change fill persistence, order submission, broker behavior, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
- 2026-06-24: Shared dashboard ledger presentation now uses signed structured
  net cash impact as the primary amount when fee evidence is available, while
  preserving gross amount, quantity, price, commission, stamp tax, and
  transfer fee as detail fields. This prevents buy-side ledger cards from
  presenting pre-fee gross amount as the cash movement. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-24: Shared public ledger notes now suppress generated account
  commission configuration remarks when structured fee breakdown or fee-rule
  evidence is already present. This keeps generated fee assumptions out of
  free-text user notes while preserving structured commission, stamp tax,
  transfer fee, other fee, and cash-impact details. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-24: Portfolio position tables now show broker-displayed unit cost
  beside the local moving-average cost when broker cost-basis evidence exists,
  with localized method/status context on both desktop rows and mobile
  metrics. This is a read-only presentation slice; it does not change ledger
  math, cost-basis computation, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
- 2026-06-23: Manual trade fee calculation was extracted into a shared backend
  fee-contract service used by both Portfolio trade creation and direct Ledger
  trade creation. Stock/ETF omitted-fee entries now share the same configured
  commission, stamp-tax, transfer-fee, other-fee, total-fee, fee-rule, and
  note formatting behavior, while explicit user-entered fees are marked with
  the `manual_fee_input` audit rule. This keeps manual trade accounting
  metadata consistent without changing broker behavior, risk gates, automatic
  trading defaults, or manual-confirmation requirements.
- 2026-06-23: Manual ledger trade creation now uses the same structured
  configured fee contract as the Portfolio manual trade path when the caller
  omits an explicit fee. The route preserves commission, stamp tax, transfer
  fee, other fees, total fee, fee-rule id, and net cash impact for stock/ETF
  manual ledger entries, while explicit user-supplied fees continue to use the
  `manual_fee_input` audit marker. This is accounting metadata only; it does
  not submit broker orders, change risk gates, enable automatic trading, or
  bypass manual confirmation.
- 2026-06-23: Shared public ledger notes now suppress generated trade-note
  segments that start with a buy/sell/subscription/redemption action and only
  repeat structured quantity, price, amount, commission, or fee facts. Activity,
  Portfolio holding traces, Overview, and Risk explainability tests cover the
  formatter path so public notes stay reserved for user-authored context while
  core accounting facts remain structured fields. This is display formatting
  only; it does not change ledger storage, accounting math, broker behavior,
  order submission, risk gates, or manual-confirmation defaults.
- 2026-06-23: Shared public ledger explainability titles now treat generated
  Chinese trade titles such as local buy/sell labels followed by a symbol the
  same way as generated English `Bought/Sold` titles. Risk explainability
  events rebuild those titles through the shared ledger formatter, so
  user-facing cards show localized action + instrument name + symbol instead
  of symbol-only generated titles. This is display formatting only; it does
  not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, or manual-confirmation defaults.
- 2026-06-23: Decision strategy-attribution summary tiles now surface
  component-level strategy contribution evidence when the backend provides it:
  net contribution, realized P/L, unrealized P/L, commission, slippage, tax,
  manual movement, cash-flow movement, and excluded movement. Frontend
  coverage pins the user-facing component labels in the decision summary.
  This is display formatting only; it does not change attribution math,
  decision generation, broker behavior, order handling, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Aligned the standalone Account Strategy contribution card with
  the Backtest contribution report by showing realized P/L, unrealized P/L,
  commission, slippage, tax, manual movement, cash-flow movement,
  unattributed movement, and net contribution as localized component fields.
  Frontend coverage verifies the contribution card does not collapse
  strategy performance into a single net value when linked-fill evidence is
  available. This is display formatting only; it does not change attribution
  math, strategy assignment, broker behavior, order handling, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Expanded the Backtest account-strategy contribution report to
  show component-level realized P/L, unrealized P/L, commission, slippage, tax,
  manual movement, cash-flow movement, unattributed movement, and net
  contribution instead of only a compressed net summary. Frontend coverage
  verifies the user-facing contribution breakdown. This is display formatting
  only; it does not change attribution math, strategy assignment, broker
  behavior, order handling, risk gates, or manual-confirmation defaults.
- 2026-06-23: Updated the Backtest strategy snapshot surface so saved reports
  show the localized strategy name before the internal strategy id, while the
  internal id remains available as a secondary audit identifier. The same
  snapshot now localizes asset-universe and frequency codes such as stock and
  daily, and validation notes now fall back to the shared public-note formatter.
  Frontend coverage verifies the Chinese strategy snapshot no longer presents
  "strategy id" as the primary user-facing field or leaks those raw metadata
  codes or raw English validation notes. This is display formatting only; it
  does not mutate persisted reports, strategy metadata, trading behavior, risk
  gates, broker behavior, or manual-confirmation defaults.
- 2026-06-23: Routed Backtest validation-evidence OOS strategy labels through
  the shared strategy audit formatter, so research evidence panels show the
  localized strategy name before the internal strategy id, and added localized
  benchmark-role copy for generic trend-following evidence. The same panel now
  renders assumption and limitation notes through the shared public-note
  formatter. Frontend coverage verifies the OOS evidence panel no longer
  renders a bare strategy id, raw benchmark role, or raw English investment
  advice limitation as the public evidence value. This is display formatting
  only; it does not mutate strategy metadata, research evidence, trading
  behavior, risk gates, broker behavior, or manual-confirmation defaults.
- 2026-06-23: Routed Decision strategy-attribution gate summaries through the
  shared strategy display-name map, so strategy names appear before internal
  ids in user-facing decision evidence. Frontend coverage verifies the gate
  shows the localized strategy label with the internal id secondary. This is
  display formatting only; it does not mutate strategy assignment, broker
  behavior, risk gates, order handling, or manual-confirmation defaults.
- 2026-06-23: Routed Account Truth latest-review notes through the shared
  public operational-note formatter and displayed the localized note under the
  latest review status. Historical backend review notes such as Account Truth
  center audit remarks no longer need to appear as raw English operational
  text in the Chinese review surface. Frontend coverage verifies the localized
  note rendering. This is display formatting only; it does not mutate manual
  review decisions, broker evidence, production ledger entries, trading
  behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Added broker-evidence instrument names to Account Truth
  reconciliation detail responses and routed the review item title through the
  shared instrument display helper, so review cards show the instrument name
  before the symbol when broker evidence provides it. Backend and frontend
  tests cover the detail payload and Account Truth review rendering. This is
  display evidence only; it does not mutate reconciliation math, broker
  evidence, production ledger entries, trading behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Tightened user-facing strategy assignment and simulation-review
  labels across shared public notes, Backtest, and Decision surfaces. Raw
  backend phrases about strategy assignment now render as localized product
  language that explains when strategy contribution can be calculated, and
  paper/shadow evidence labels are presented as simulation-review evidence for
  users. Frontend tests cover the shared formatter plus Backtest and Decision
  rendering. This is display wording only; it does not mutate strategy
  assignment, broker behavior, risk gates, order handling, or
  manual-confirmation defaults.
- 2026-06-23: Added structured trade fields to portfolio explainability
  drivers and timeline events, including quantity, price, commission, gross
  amount, net cash impact, fee rule metadata, and optional fee breakdown.
  Risk explainability now prefers the shared public ledger formatter for these
  structured fields, so generated quantity/price/fee facts are displayed as
  localized execution details instead of being carried as free-text notes.
  Backend and frontend tests cover the API fields and Risk page rendering.
  This is evidence/display formatting only; it does not mutate ledger entries,
  broker evidence, fee models, trading behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Routed Decision signal-queue action details through the shared
  public note formatter so backend research or review phrases are localized
  before being shown in the manual-order handoff surface. Frontend coverage
  verifies the `/api/signals/actions` path in Chinese and keeps the original
  English evidence phrase out of the public UI. This is display formatting
  only; it does not mutate candidate actions, manual-order payloads, broker
  evidence, trading behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Tightened the shared public ledger note formatter so generated
  trade notes that only repeat structured amount, quantity, price, commission,
  or fee facts are suppressed from public note fields while user-authored notes
  remain visible. Overview and Activity tests cover the shared behavior so
  generated ledger remarks do not duplicate structured columns. This is
  display formatting only; it does not mutate ledger entries, broker evidence,
  fee models, trading behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Routed Activity ledger instrument cells through the shared public
  ledger instrument formatter so the audit table shows one consistent
  name-plus-symbol label and keeps the asset-class chip separate, instead of
  rendering a standalone secondary symbol line. Frontend coverage verifies the
  ActivityFeed path for fund and stock rows. This is display formatting only;
  it does not mutate ledger entries, broker evidence, fee models, trading
  behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Added shared localized fallbacks for unknown public status,
  action, and note codes so future backend snake-case values render as generic
  review labels instead of leaking internal names, title-cased raw codes, or
  "unmapped" placeholders into Decision workflow cards and other public
  surfaces. Tests cover the shared formatter and the Decision workflow path in
  Chinese and English. This is display formatting only; it does not mutate
  ledger entries, broker evidence, trading behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Moved Risk/Overview explainability event title and detail
  formatting into the shared public ledger formatter. Generated event titles
  such as buy/sell/cash movement now use the same localized ledger labels,
  instrument-name resolution, and legacy-note suppression as Activity,
  Portfolio, and Account Truth review surfaces. This is display formatting
  only; it does not mutate ledger entries, broker evidence, trading behavior,
  risk gates, or manual-confirmation defaults.
- 2026-06-23: Moved broker trade evidence-reference formatting into the shared
  public ledger formatter and routed the Account Truth review surface through
  it. Broker trade evidence now uses the same localized buy/sell labels as
  ledger activity, while non-trade broker evidence still uses the public
  evidence formatter. This is display formatting only; it does not mutate
  broker evidence, production ledger entries, trading behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Extended the Account Truth review surface to format broker
  trade evidence references with the shared public ledger trade labels instead
  of page-local broker event labels. Review evidence now renders buy/sell
  trade references as the same localized ledger actions used by Activity,
  Overview, Portfolio, Risk, and holding detail, while non-trade broker
  evidence keeps the existing public evidence formatter. The shared ledger
  execution details also accept the full ledger-row shape and suppress zero
  stock-specific fee rows for open-end fund purchases. This is display
  formatting only; it does not mutate broker evidence, production ledger
  entries, trading behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Routed manual Portfolio trade ledger writes through the
  configured stock/ETF fee model when commission is omitted. Ledger entries now
  store structured commission, stamp tax, transfer fee, other fee, total fee,
  and net cash impact while the API response continues to expose the legacy
  commission component for compatibility. Tests cover buy-side transfer fees
  and sell-side tax/fee cash impact. This is ledger evidence alignment only; it
  does not submit broker orders, bypass risk gates, or alter
  manual-confirmation defaults.
- 2026-06-23: Surfaced ledger-projected remaining cost-basis evidence in the
  Web holding-detail valuation panel with separate labels from broker-confirmed
  cost evidence. Holding detail now labels projected values as local
  ledger-derived evidence, keeps broker-confirmed `available` evidence as the
  only state that can trigger a broker cost-basis review warning, and continues
  to show moving-average local cost separately. Frontend tests cover the
  `projected_from_ledger` state and assert it is not rendered as broker
  displayed cost. This is display evidence only; it does not mutate ledger
  entries, submit broker orders, change risk gates, or alter
  manual-confirmation defaults.
- 2026-06-23: Added broker-style remaining cost-basis evidence to deterministic
  portfolio ledger projections. Partial sells now reduce projected
  broker-display-style remaining cost by net proceeds after commission, stamp
  tax, transfer fees, and other structured trade fees, while realized P/L and
  cash continue to use the same net cash impact math. The projected
  cost-basis status is `projected_from_ledger`, not broker-confirmed
  `available`, so UI surfaces can keep imported broker evidence distinct from
  local ledger-derived estimates. This is projection evidence only; it does not
  mutate ledger entries, submit broker orders, change risk gates, or alter
  manual-confirmation defaults.
- 2026-06-23: Added a shared Web instrument display helper and applied it to
  the Decision page's candidate cards, signal action queue, and signal journal
  rows. When backend evidence provides a display name, Decision surfaces now
  show the instrument name before the symbol instead of relying on raw symbols
  or legacy candidate titles. Trading execution-audit order and fill facts now
  reuse the same name-plus-symbol helper and prefer display names carried by
  the execution facts before falling back to current holdings. Activity and
  holding-detail execution details also avoid duplicating net cash impact after
  it has already been shown as the primary signed amount, while keeping gross
  amount, quantity, price, and fee breakdowns structured. Frontend tests cover
  that the user-visible Decision surface renders name-plus-symbol labels and
  does not expose the old internal candidate title as the primary audit label,
  that Trading audit rows use fact-level instrument names, and that public
  execution details avoid repeating cash-impact fields. This is display
  formatting only; it does not submit broker orders, mutate account facts,
  change API paths, or change live-like manual-confirmation defaults.
- 2026-06-22: Started the shared public ledger formatter migration by moving
  ledger instrument, note, amount, and entry-type formatting into a shared Web
  module. Overview, Risk explainability conversion, Activity compatibility
  imports, and holding-detail ledger traces now use the shared formatter path,
  and holding-detail tests prove raw ledger entry types such as internal trade
  codes are not rendered in that surface. This is display formatting only; it
  does not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
- 2026-06-22: Upgraded account strategy contribution attribution so fully
  linked strategy fills remain the only source of strategy net contribution,
  while tax, fee, slippage, manual ledger movement, missing-evidence fills, and
  external cash flow are separated into distinct report fields. Deterministic
  backend coverage proves that metadata-only strategy fills and manual trades
  are excluded from net strategy contribution by default. This is attribution
  evidence only; it does not submit broker orders, mutate broker facts, or
  change live-like manual-confirmation defaults.
- 2026-06-22: Added structured trade-cost fields to persisted ledger entries.
  Buy and sell ledger rows can now preserve gross trade amount, signed net cash
  impact, JSON fee breakdown, fee-rule id, fee-rule version, and cost-basis
  method while keeping the legacy `amount` and `commission` fields compatible.
  Manual Portfolio trades and Ledger trade imports populate these fields for
  audit and reconciliation. This is accounting evidence only; it does not
  submit broker orders, mutate broker facts, or change live-like
  manual-confirmation defaults.
- 2026-06-22: Started Strategy Attribution 2.0 + Broker Fee & Cost Basis
  Fidelity with a structured local broker fee schedule and deterministic fee
  breakdown contract. Ignored `config.json` can now hold safe fee-rule
  parameters such as commission rates, minimum commissions, stamp tax,
  transfer fee, other fee rate, rule id, and known limitations while rejecting
  credential-like fields. `StockACommission` and `ETFCommission` expose
  component-level fee breakdowns while legacy total-fee `calculate()` calls
  remain compatible. This is accounting evidence only; it does not submit
  broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.

## v1.3 Progress

- 2026-06-22: Completed localized frontend coverage for Decision no-action,
  degraded, blocked, and review-required states. The Web Decision page now
  formats lane summary decisions through the shared public-label formatter, so
  Chinese and English surfaces do not expose raw internal decision codes such
  as no-action or review-required state ids. Tests assert that localized
  no-action, degraded account truth, blocked data quality, review-required
  decision state, and no-action reasons remain user-readable. This is display
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.
- 2026-06-22: Added decision certainty evidence for candidate actions so stale,
  cached, estimated, unknown, missing, or unavailable market/account evidence
  cannot appear as a certain actionable suggestion. Decision summaries now
  degrade stale/estimated data to review-required, block missing/unavailable
  evidence, hide manual approval entry points until review is complete, and
  localize certainty reasons and required actions in the Web Decision page.
  This is review evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
- 2026-06-22: Added candidate-level evidence-chain fields and Web rendering for
  strategy source, market data status, account truth, risk status, research
  evidence, paper/simulation evidence, cost impact, uncertainty, and manual
  confirmation state. The surface localizes user-facing labels and keeps
  internal action codes out of the UI. This is review evidence only; it does
  not submit broker orders, mutate account facts, or change live-like
  manual-confirmation defaults.
- 2026-06-22: Connected the decision workflow task surface to the Web Decision
  page with localized task labels, status labels, and next-action labels.
  Decision workflow rendering now places data refresh and account truth before
  strategy evidence, paper/shadow review, and manual confirmation, and tests
  assert that internal action codes are not shown to users. This is display
  and review-order evidence only; it does not submit broker orders, mutate
  account facts, or change live-like manual-confirmation defaults.
- 2026-06-22: Started Professional Decision Workflow with a stable decision
  summary workflow task surface. Daily and intraday decision summaries now
  order data refresh, account truth, risk review, strategy evidence,
  paper/shadow review, and manual confirmation so data and account-truth
  blockers are visible before strategy opportunities. This is API review
  evidence only; it does not submit broker orders, mutate account facts, or
  change live-like manual-confirmation defaults.

## v1.1 Progress

- 2026-06-22: Added shadow review comparison evidence for strategy candidates,
  paper outcomes, and real account movement. The new
  `analytics.shadow_review` report only attributes a real account movement to a
  strategy when candidate id, paper order id, and strategy id references align;
  unsupported movement remains explicitly unattributed with a review action.
  The report is audit evidence only and does not mutate account facts, ledger
  entries, broker orders, or manual-confirmation defaults.
- 2026-06-22: Added an explicit paper OMS state machine with deterministic
  transitions for staged, submitted, accepted, partially filled, filled,
  rejected, cancelled, expired, and reconciled states. Paper order payloads now
  retain full OMS transition evidence in addition to the compact status
  history, and tests cover idempotent repeated transitions plus invalid path
  rejection. The state machine is paper-only review evidence and does not
  submit broker orders, mutate production ledger entries, or change manual
  confirmation defaults.
- 2026-06-22: Added the first Paper Broker & OMS evidence slice. The new
  `execution.paper_broker` module records paper-only order and fill evidence
  into the existing order/fill fact tables with
  `karkinos.paper_broker.v1` payloads, status history, fee/slippage fields, and
  optional strategy, signal, risk decision, dataset, cost model, and
  account-truth references. Tests verify that paper evidence does not mutate
  production ledger entries. This does not introduce broker submission, broker
  credentials, default real-money automation, or any change to manual
  confirmation defaults.

## v1.0 Progress

- 2026-06-22: Completed the v1.0 documentation and backend coverage acceptance
  evidence. The bilingual strategy primer now explains built-in strategy ids,
  parameter meanings, risk assumptions, custom strategy placement under
  `strategy/extensions/` or `KARKINOS_STRATEGY_EXTENSION_DIR`, sanitized
  extension templates, and the non-investment-advice/manual-confirmation
  boundary. Added deterministic documentation coverage tests, and confirmed
  existing backend tests cover lifecycle ordering, read-only runtime context,
  output normalization, extension discovery, and blocked unsafe extension
  manifests.
- 2026-06-22: Added a shared market-calendar contract for Strategy Runtime and
  the Web return calendar. `data.market_calendar` and the Web shared
  `market-calendar` helper expose the same
  `karkinos.market_calendar.v1` schema semantics for trading days, weekends,
  configured market holidays, and configured closed days. Strategy Runtime
  context now carries the calendar as read-only review context, while the Web
  return calendar explains non-trading blank dates as weekend, holiday, or
  closed instead of rendering them as missing prices or zero-return trading
  days. This is calendar explanation evidence only; it does not fetch broker
  data, submit orders, change risk gates, or change manual-confirmation
  defaults.
- 2026-06-22: Tightened the shared Strategy Registry contract for built-in and
  extension strategies. Registry entries and `/api/backtest/strategies` now
  expose the same capability-based contract version, strategy schema version,
  source type, extension flag, parameter schema, validation metadata, and
  research-only execution boundary for both built-in and local extension
  strategies. The boundary explicitly keeps broker order submission disabled
  and requires risk, account-truth, paper/shadow, and manual confirmation gates
  before any candidate could be reviewed. Existing `params` and
  `parameter_schema` fields remain aligned for compatibility.
- 2026-06-22: Added standardized Strategy Runtime output normalization.
  Lifecycle hooks may now return observation signals, buy candidates, sell
  candidates, rebalance candidates, risk warnings, or no-action explanations.
  `StrategyRuntimeRunner` stamps each output with deterministic audit ids,
  hook/source-event references, strategy/run ids, reason text, evidence, and
  downstream gate requirements. Candidate actions explicitly require risk,
  account-truth, paper/shadow, and manual review gates and set
  `does_not_enable_execution=true`, so this contract does not submit broker
  orders or change live-like manual-confirmation defaults.
- 2026-06-22: Hardened the Strategy Runtime context boundary. Runtime context
  now carries account facts, position facts, risk limits, parameters, and
  metadata as recursively frozen read-only mappings, exposes only a false
  `broker_order_submission_enabled` safety flag, and does not provide broker,
  broker-client, or order-submission methods to strategies. Deterministic tests
  prove context immutability and the absence of broker submit capability. This
  does not change existing backtest behavior, broker submission, real-money
  trading defaults, or live-like manual-confirmation requirements.
- 2026-06-22: Added the capability-based Strategy Runtime lifecycle contract.
  `strategy.runtime` now exposes the canonical initialize, before-market, bar,
  tick, after-market, order-update, and fill-update hooks through a deterministic
  runner and audit trace. The contract is exported from the strategy package and
  covered by backend tests for hook vocabulary and invocation order. This does
  not change existing backtest behavior, broker submission, real-money trading
  defaults, or live-like manual-confirmation requirements.

## v0.9 Progress

- 2026-06-22: Added Market Data Reliability acceptance evidence for frontend
  market-data tests. The audit manifest now groups tests for shared
  data-status rendering, Overview estimated valuation labels, return-calendar
  confirmed versus unconfirmed valuation handling, 1D equity-curve missing and
  stale observation behavior, dashboard next actions, and Backtest unconfirmed
  dataset warnings. This is frontend test and audit evidence only; it does not
  change valuation inputs, broker submission, trading behavior, or manual
  confirmation defaults.
- 2026-06-22: Added Market Data Reliability acceptance evidence for backend
  deterministic tests. The audit manifest now groups the adapter normalization
  contract tests, freshness diagnostics tests, manual and scheduled refresh
  boundary tests, and frozen dataset replay determinism tests under the backend
  coverage criterion. This is test and audit evidence only; it does not change
  market-data inputs, broker submission, trading behavior, or live-like manual
  confirmation defaults.
- 2026-06-22: Added Market Data Reliability acceptance evidence for Web
  data-status surfaces. The audit manifest now ties the shared localized
  market-data status formatter to Overview quick actions, Market selected
  symbol detail, Settings valuation notices, Backtest dataset snapshot warnings,
  and the global app-shell status indicators, with tests proving user-facing
  next actions do not leak internal reason codes. This is display and audit
  evidence only; it does not change valuation inputs, broker submission,
  trading defaults, or manual-confirmation behavior.
- 2026-06-21: Tightened the Overview 1D net-value chart missing-observation
  contract. The Web chart now treats `missing` or `error` quote-status points
  as gaps for quote-dependent series (`total`, stocks, funds, and other
  assets) while preserving the cash series and localized quote status in the
  tooltip. This prevents missing intraday observations from being displayed as
  confirmed total or stock/fund values and keeps the chart from fabricating a
  continuous market-data path. This is a display-safety change only; it does
  not change valuation data, broker submission, trading behavior, or manual
  confirmation defaults.
- 2026-06-21: Tightened the backend 1D equity-series missing-observation
  contract. The portfolio equity-series API can now return `null` for
  quote-dependent buckets on missing or error quote observations while keeping
  cash, public quote status, and missing-symbol evidence intact. This prevents
  the API from materializing average-cost or stale baseline values as if they
  were intraday market observations. This is a data-contract safety change
  only; it does not change broker submission, trading behavior, risk gates, or
  manual confirmation defaults.
- 2026-06-21: Hardened return-calendar and explainability conversion for
  nullable valuation points. Equity-series points with missing quote-dependent
  values are now excluded from numeric equity-curve and component-breakdown
  conversion while their valuation status and missing-symbol evidence remain
  available to downstream diagnostics. This prevents missing valuation points
  from crashing attribution surfaces or being displayed as confirmed returns.
  This is a reporting-safety change only; it does not change valuation source
  data, broker submission, trading behavior, risk gates, or manual confirmation
  defaults.
- 2026-06-21: Documented the v0.9 market-data reliability workflow and privacy
  boundary in the user README set. The docs now explain the shared status
  vocabulary, manual and scheduled refresh boundaries, frozen replay datasets,
  local storage boundaries, and that estimated, cached, stale, missing, or
  confirmed-NAV-missing data is data-quality evidence rather than investment
  advice, return guarantee, or execution approval. The market-data acceptance
  audit manifest now includes this documentation evidence.
- 2026-06-21: Extended the shared Web market-data next-action formatter to
  Overview and Market data-status surfaces. Overview now prefers localized
  cache/stale/estimated/missing/confirmed-NAV-missing guidance before showing
  provider fallback actions, while Market exposes the same guidance in both
  the data-health panel and selected-symbol detail. Provider-specific actions
  such as continuing with local cached data remain intact. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
- 2026-06-20: Added a shared Web market-data next-action formatter for
  unconfirmed statuses and connected Settings valuation notices to it. Cache
  and stale states now guide users to refresh quotes or check the data source,
  estimated states guide users to wait for confirmation or refresh, missing
  states guide users to backfill or run first sync, and confirmed-NAV-missing
  states guide users to wait for or sync fund NAV confirmation. This is a
  user-facing explanation change only; it does not change valuation data,
  trading behavior, broker submission, or manual-confirmation defaults.
- 2026-06-20: Added the capability-based Market Data Reliability acceptance
  audit manifest and CLI registry entry. `build_market_data_reliability_acceptance_audit()`
  maps the completed v0.9 data-plane criteria to deterministic evidence paths
  and validation commands, while `scripts/export_acceptance_audit.py --audit
market_data_reliability` exports the manifest through the shared CI-friendly
  JSON surface. This is audit/reporting evidence only; it does not change
  trading behavior, broker submission, live-like defaults, or manual
  confirmation requirements.
- 2026-06-20: Connected the shared v0.9 market-data status vocabulary to Web
  public labels and the return calendar valuation guard. The Web formatter now
  localizes `confirmed`, `live`, `cache`, `estimated`, `missing`, `stale`, and
  `confirmed_nav_missing` without leaking internal codes, and the return
  calendar treats estimated, cached, stale, or confirmed-NAV-missing periods as
  valuation gaps instead of confirmed returns. The Overview 1D equity curve now
  uses the same localized status text and marks category changes as needing
  confirmation when the underlying valuation point is estimated, cached,
  missing, or otherwise unconfirmed. Historical market bars and daily closes now
  normalize to the shared public `confirmed` status while keeping their source
  evidence separate. Current valuation points preserve explicit shared
  statuses such as `estimated`, `cache`, and `confirmed_nav_missing` instead of
  collapsing them into `live`. Market data health aggregation now preserves a
  full-cache state as `cache` rather than relabeling it as stale, and the
  Overview data-status card plus global toolbar treat cache, estimated,
  missing, partial, stale, and confirmed-NAV-missing states as unconfirmed
  market data instead of healthy live quotes. This changes display semantics
  only; it does not change portfolio data, broker submission, trading
  defaults, or manual-confirmation behavior. The Overview total-assets rail
  also labels estimated, missing, or confirmed-NAV-missing valuation status
  with localized public text instead of showing those figures as confirmed.
  Market research now counts cache, estimated, missing, stale, and
  confirmed-NAV-missing quotes as data needing review through the shared
  frontend status helper, and the user-facing summary uses review-oriented
  wording instead of calling every unconfirmed quote stale. Settings data
  status now uses the same shared helper so estimated, missing, and
  confirmed-NAV-missing valuations are shown as review-required rather than
  healthy confirmed quotes. Backtest dataset snapshots now surface per-symbol
  data status in the report table and show a research-evidence warning when a
  saved report contains unconfirmed market data, so estimated rows are not
  presented as confirmed inputs for after-cost metrics. Frozen replay datasets
  now provide deterministic replay evidence for Strategy Runtime dry-runs,
  including status counts, unconfirmed statuses, required action, and safety
  flags, so estimated replay inputs cannot be treated as confirmed returns.
- 2026-06-20: Added deterministic frozen market-data replay datasets.
  `data.market_data_replay` freezes normalized `MarketDataRecord` values into
  a stable `karkinos.market_data_dataset.v1` payload, computes a deterministic
  dataset fingerprint, and replays records in canonical order for backtest,
  strategy-runtime dry-run, paper/shadow review, and audit replay consumers.
  The frozen dataset carries explicit safety evidence that it does not change
  trading behavior, enable broker order submission, or alter manual
  confirmation defaults.
- 2026-06-20: Added a capability-based market-data refresh contract for manual
  and scheduled refresh flows. `data.market_data_refresh` builds and runs
  auditable refresh tasks for intraday quotes, close-price bars, and fund NAV
  confirmation through the market-data adapter boundary. Each refresh run
  returns trigger, task, refreshed-symbol, failed-symbol, record-count, and
  safety evidence showing that trading behavior, broker order submission, and
  manual-confirmation defaults were not changed.
- 2026-06-20: Added market-data quality diagnostics to the shared v0.9
  contract. `build_market_data_quality_report()` now detects missing expected
  trading sessions, records that appear on configured non-trading days, stale
  quotes, confirmed fund NAV gaps, mixed adjustment modes, and provider price
  differences. The diagnostics return localized messages, deterministic
  pass/degraded/blocked status, and JSON-safe evidence payloads. This is a
  backend data-quality contract only; it does not change broker submission,
  trading defaults, refresh behavior, or manual-confirmation requirements.
- 2026-06-20: Started Data Plane & Market Reliability with a shared market
  data contract. `data.market_data` defines the capability-based
  `MarketDataAdapter` boundary for daily bars, intraday bars, snapshots, ticks,
  and replay records, plus the shared status vocabulary (`confirmed`, `live`,
  `cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`).
  `MarketDataRecord` and `MarketDataRecordMetadata` preserve source, source
  symbol, timestamp, trading session, adjustment mode, freshness metadata, and
  limitations. Deterministic tests cover status normalization, Chinese labels,
  event-kind serialization, and the adapter contract without changing broker
  submission, trading defaults, or manual-confirmation behavior.

## v0.8 Progress

- 2026-06-18: Added the first account strategy assignment and attribution loop.
  `/api/account-strategy` can read and update a research-only assignment while
  forcing `auto_trade_enabled=false`; attribution and contribution endpoints
  link available signal, risk, order, fill, fee, and valuation evidence without
  mutating ledger, broker, order, fill, or position state. Backtest Web now
  starts with the strategy catalog, shows the current account assignment, and
  surfaces attribution/contribution status as audit evidence rather than a
  profitability claim.
- 2026-06-18: Connected strategy attribution readiness into promotion and
  decision gates. Strategy promotion readiness blocks an assigned strategy when
  attribution evidence is pending; Decision summaries and candidate cards now
  surface the strategy-attribution gate and fall back to review-required when
  a strategy-driven candidate lacks linked contribution evidence. Backend and
  frontend deterministic tests cover the degraded decision state and visible
  gate status without changing broker submission, trading defaults, or manual
  confirmation requirements.
- 2026-06-18: Added Strategy Assignment acceptance audit coverage to the shared
  capability registry. `build_strategy_assignment_acceptance_audit()` and
  `scripts/export_acceptance_audit.py --audit strategy_assignment` map the
  completed v0.8 checklist items to deterministic backend, frontend, and
  documentation evidence while leaving unfinished roadmap items visible in
  `docs/ROADMAP.md`.
- 2026-06-18: Completed account, asset-class, and symbol scope handling for
  account strategy assignment updates. Asset-class assignments now persist the
  selected class and filter attribution evidence by matching signal asset
  class, with deterministic route tests covering the boundary.

## v0.7 Progress

- 2026-06-18: Started Account Truth Review Center with read-only review APIs.
  `/api/account-truth/import-runs` lists staged broker import metadata, while
  `/api/account-truth/reconciliation-reports` and
  `/api/account-truth/reconciliation-reports/{import_run_id}` compute report
  summaries and details against current Karkinos ledger, cash, positions,
  fees, taxes, and cost basis. Reconciliation items include item keys,
  severity, broker value, Karkinos value, difference, suggested review action,
  symbol, detail, and broker evidence references. The routes do not mutate the
  production ledger, holdings, broker state, or credentials.
- 2026-06-18: Added the first manual review action API for Account Truth
  differences. `POST
/api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`
  records `accepted`, `ignored`, `known_difference`, `ledger_candidate`, or
  `needs_investigation` decisions and returns the persisted audit state. Report
  detail responses include the latest review decision per item. Deterministic
  tests verify that recording a `ledger_candidate` does not create production
  ledger entries.
- 2026-06-18: Added the first Web Account Truth Review Center. `/account-truth`
  shows Account Truth Score component reasons, staged import runs, status
  filters for reconciliation reports, per-item broker/Karkinos differences,
  evidence references, and manual review action buttons. `GET
/api/account-truth/score` exposes the same component-level score evidence to
  the Web UI. Frontend tests cover rendering, status filtering, review action
  submission, score display, and blocked-state presentation; backend tests
  cover the score endpoint and ledger-candidate non-mutation safety.
- 2026-06-18: Surfaced Account Truth gate evidence in Decision and Strategy
  Promotion review surfaces. Decision summaries and candidates now show pass,
  degraded, blocked, or not-evaluated account-truth state with score and
  unresolved-difference context; Strategy Lab promotion readiness shows the
  same gate status and evidence availability. Frontend tests cover degraded and
  blocked decision states plus promotion-gate rendering without changing broker
  submission, production ledger mutation, or manual-confirmation defaults.
- 2026-06-18: Added Account Truth Review Center acceptance audit coverage.
  `build_account_truth_review_acceptance_audit()` maps the v0.7 review
  workflow checklist to deterministic backend, frontend, documentation, and CLI
  evidence. `scripts/export_acceptance_audit.py --audit account_truth_review`
  exports the manifest through the shared capability registry without using a
  roadmap version in function, file, or CLI names.

## v0.6 Progress

- 2026-06-17: Started Account Truth with a canonical broker statement CSV
  contract and read-only import preview parser. The parser normalizes local CSV
  rows into broker evidence preview events, validates required columns and
  event types, computes file-level and row-level SHA-256 fingerprints, reports
  deterministic duplicate rows, and records limitations that the preview does
  not mutate the production ledger or enable broker submission. README and
  Chinese docs now describe the import workflow, privacy boundary, and safe
  synthetic examples.
- 2026-06-17: Added staged broker evidence persistence for valid import
  previews. `BrokerEvidenceRepository` creates local `broker_import_runs` and
  `broker_evidence_events` tables, stores source type, file fingerprint, row
  counts, validation status, duplicate counts, timestamps, limitations, and
  typed evidence events for trades, dividends, fees, taxes, transfers,
  position snapshots, and cash snapshots. Duplicate files are recorded as
  warning import runs without duplicating evidence rows, and deterministic
  tests verify the production ledger is not mutated.
- 2026-06-17: Added the first deterministic reconciliation report core.
  `build_reconciliation_report()` compares staged broker evidence against
  Karkinos cash, positions, ledger fees, ledger taxes, and position cost basis,
  returning versioned `pass`, `warning`, `mismatch`, or `blocked` reports with
  per-category differences and suggested review actions. The report remains
  evidence only; it does not write ledger entries, change holdings, or submit
  broker orders.
- 2026-06-17: Added manual review persistence for reconciliation items.
  `ManualReviewRepository` records `accepted`, `ignored`, `known_difference`,
  `ledger_candidate`, and `needs_investigation` decisions keyed by import run
  and reconciliation item. Decisions are idempotent audit notes only;
  `ledger_candidate` does not create production ledger entries without a
  future explicit confirmation path.
- 2026-06-17: Added deterministic Account Truth Score generation.
  `build_account_truth_score()` converts reconciliation report status, manual
  review decisions, account/data freshness, and unresolved cash, position, fee,
  tax, and cost-basis differences into a versioned 0-100 score with
  `pass`, `degraded`, or `blocked` gate status, required actions, blocking
  reasons, and limitations. The score is report/gate evidence only and does
  not mutate ledger, holdings, or broker state.
- 2026-06-17: Connected Account Truth Score evidence to strategy promotion
  readiness. `build_strategy_promotion_readiness()` can now consume explicit
  account-truth score evidence; `degraded`, `blocked`, or explicitly missing
  account-truth evidence adds an `account_truth_gate_pass` missing requirement
  while legacy callers that do not pass score evidence remain unchanged.
- 2026-06-17: Connected Account Truth Score evidence to Decision Cockpit.
  `/api/decision/today` and `/api/decision/intraday` now include
  account-truth gate evidence in summaries and candidates. Missing,
  `degraded`, or `blocked` account-truth evidence changes actionable
  candidates to `review_required` and prevents live-like manual-confirm
  readiness without changing broker submission or ledger mutation behavior.
- 2026-06-17: Added Account Truth acceptance audit coverage and CLI registry
  wiring. `build_account_truth_acceptance_audit()` maps all Account Truth and
  reconciliation acceptance criteria to concrete code, docs, deterministic
  tests, and validation commands. `scripts/export_acceptance_audit.py` now
  supports `--audit account_truth` and includes it in `--audit all` without
  using roadmap-version names or writing artifacts by default.

## v0.5 Progress

- 2026-06-17: Added a research evidence acceptance audit manifest.
  `build_research_evidence_acceptance_audit()` maps all completed
  Quant Research Quality & Production Evidence Hardening checkboxes to
  concrete code, docs, deterministic tests, and validation commands without
  changing execution defaults or schema versions.
- 2026-06-17: Started v0.5 by adding target, scope, acceptance criteria, and a
  dedicated progress section for research evidence hardening. The first backend
  implementation slice is a minimal versioned `ResearchEvidenceBundle` and
  analyzer contract for existing backtest runs, without changing Web UI or
  execution behavior.
- 2026-06-17: Implemented the first v0.5 backend evidence slice. Single
  backtest runs now attach `research_evidence_bundle` to `metrics_json` and
  saved report files. The bundle is versioned, includes deterministic analyzer
  outputs for data quality, after-cost evidence, and OOS presence, records
  China-market assumption gaps, and keeps promotion status as human review
  evidence without enabling execution behavior.
- 2026-06-17: Extended the evidence bundle surface to Strategy Lab sweeps and
  comparisons. Each sweep result and comparison item now exposes the same
  `research_evidence_bundle` contract that is persisted in the saved
  `metrics_json`, so multi-run research outputs can be audited without looking
  up each saved result manually.
- 2026-06-17: Connected research evidence gates to promotion readiness.
  Strategy promotion readiness now reads each saved backtest result's
  `research_evidence_bundle.promotion_gate.status`; degraded or blocked
  evidence adds a `research_evidence_gate_pass` missing requirement even when
  after-cost/OOS, risk, paper/shadow, and divergence evidence are otherwise
  present. This keeps shadow/paper eligibility behind the v0.5 evidence gate.
- 2026-06-17: Added explicit evidence references and trade statistics to the
  research evidence bundle. Backtest evidence now records dataset snapshot
  references, strategy metadata availability, after-cost and OOS evidence
  availability, cost-summary availability, fill and trade counts, turnover,
  commission, slippage, and limitation counts so saved reports can be audited
  from one versioned artifact without enabling execution behavior.
- 2026-06-17: Added deterministic rolling OOS evidence for Strategy Lab
  experiments. Backtest requests can now ask for rolling OOS folds over a
  frozen equity curve, producing fold-level train/test evidence, aggregate
  pass rate, worst and mean out-of-sample return, and total OOS cost. The
  research evidence bundle's OOS analyzer summarizes rolling mode, fold count,
  and aggregate fields while explicitly noting that rolling evidence does not
  refit parameters per fold or enable execution behavior.
- 2026-06-17: Added parameter sweep robustness evidence. Sweep responses now
  include a versioned robustness artifact with the best parameter set, local
  neighbor stability, per-parameter sensitivity ranges, grid-grounded
  overfitting warnings, and limitations requiring after-cost, OOS, risk, and
  data-quality review before any promotion consideration.
- 2026-06-17: Exposed research evidence bundles as first-class API and report
  artifacts. Single backtest responses and saved JSON reports now surface the
  same `research_evidence_bundle` at top level while retaining the nested
  `metrics_json` copy for compatibility. README and Chinese docs now explain
  `pass`, `degraded`, and `blocked` gate states, required review evidence, and
  the boundary that evidence does not enable broker order submission.

## Earlier Progress

- 2026-06-17: Added a per-instrument daily PnL entry point. Portfolio positions
  now carry `today_change`, `today_change_pct`, daily baseline price, baseline
  timestamp, and baseline source through the same API used by the holdings
  table and holding detail page. The Web cockpit shows single-stock/fund daily
  PnL beside quote price, market value, since-buy PnL, and baseline evidence,
  so account-level daily movement can be traced back to individual holdings
  without adding broker submission or execution behavior.
- 2026-06-17: Documented portfolio return-accounting semantics. Added a
  Chinese guide for daily PnL, since-buy floating PnL, realized PnL, cash-flow
  treatment, and baseline-price priority so future cockpit and API work can
  keep cost basis, market movement, and external flows separated.
- 2026-06-16: Cleaned Risk explainability notes and top-panel layout. Risk
  recent impact cards and timeline events now route their details through the
  shared Web ledger public-note formatter, suppressing legacy internal notes
  while preserving user-authored English notes elsewhere. The Risk
  explainability top grid now aligns panels at the top and keeps the
  recent-impact list in a local scrollable region.
- 2026-06-16: Fixed Risk explainability event readability so recent impact
  events and timeline trade events use the shared instrument identity metadata
  path instead of rendering raw symbols or internal action strings.
- 2026-06-16: Fixed the Overview 1D equity-curve cash path so same-day ledger
  events are replayed at their ledger timestamp instead of being projected back
  to the market open.
- 2026-06-16: Fixed the Overview 1D equity-curve tooltip path so category
  point-in-time changes are supplied by backend `*_daily_change` fields
  instead of being inferred from the first visible chart point.
- 2026-06-16: Confirmed the v0.2/v0.3/v0.4 acceptance checkboxes had no
  remaining unchecked items, then added a data integrity slice for provider
  reconciliation through deterministic local-cache-vs-provider OHLCV reports.
- 2026-06-16: Made historical OHLCV storage explicitly SQLite-first for local
  audit and query paths while retaining Parquet as a local mirror.
- 2026-06-15: Added a v0.4 Strategy Lab acceptance audit and marked the v0.4
  acceptance criteria complete.
- 2026-06-15: Split Strategy Lab after-cost report assumptions into structured
  cost and slippage evidence.
- 2026-06-15: Reduced raw Strategy Lab parameter-key exposure in the Web
  Backtest comparison panel.
- 2026-06-15: Surfaced persisted Strategy Lab metadata in saved Web Backtest
  reports.
- 2026-06-15: Persisted Strategy Lab strategy metadata snapshots on saved
  backtest reports.
- 2026-06-15: Added Strategy Lab strategy metadata and readable parameter
  labels to the Web Backtest page.
- 2026-06-15: Added the Web Strategy Lab same-dataset comparison review
  surface.
- 2026-06-15: Added a same-dataset Strategy Lab comparison contract.
- 2026-06-15: Added Web Backtest parameter-sweep review.
- 2026-06-15: Added a Web Backtest validation-evidence report panel.
- 2026-06-15: Surfaced Backtest dataset snapshots in the Web report.
- 2026-06-15: Added dataset snapshot metadata to the single Backtest runner.
- 2026-06-15: Refined the Web Backtest strategy-parameter experience for
  Chinese users.
- 2026-06-15: Added the first backend Strategy Lab parameter-sweep API.
- 2026-06-15: Made local Strategy Lab extension scripts runnable through the
  Backtest API path.
- 2026-06-15: Localized Web Backtest strategy parameter labels and
  descriptions while preserving stable API parameter ids.
- 2026-06-15: Fixed the Web Backtest initial-cash control browser validation
  contract.
- 2026-06-15: Added the first local Strategy Lab extension area.
- 2026-06-15: Wired the Web Backtest page to the strategy registry.
- 2026-06-15: Started v0.4 Strategy Lab backend parameter contracts.
- 2026-06-15: Added the v0.4 Strategy Lab Backtesting Engine target to the
  project goal.
- 2026-06-12: Removed the Activity batch fund form's built-in fund candidates.
- 2026-06-12: Exposed latest risk-gate outcomes on signal action cards.
- 2026-06-12: Added a deterministic Profit Discipline smoke path covering
  fixture data cache metadata, feature calculation, after-cost backtest report,
  generated signal, mandatory pre-trade risk gate, action queue risk summary,
  and signal journal audit chain.
- 2026-06-12: Tagged registered strategies with v0.2 benchmark metadata.
- 2026-06-12: Added reusable out-of-sample validation evidence for completed
  backtests.
- 2026-06-12: Wired OOS validation evidence into the backtest run path.
- 2026-06-12: Added a deterministic v0.2 strategy validation matrix.
- 2026-06-12: Added fixture-backed validation backtests for all v0.2 benchmark
  strategies.
- 2026-06-12: Exposed the v0.2 strategy validation matrix through the backtest
  API.
- 2026-06-12: Added a portfolio cockpit API surface.
- 2026-06-12: Made action-card risk gate state explicit.
- 2026-06-12: Added manual-confirmation readiness to action cards.
- 2026-06-12: Added the first action-to-manual-order execution bridge.
- 2026-06-12: Linked manual order decisions back into the signal journal.
- 2026-06-12: Added a deterministic daily paper/shadow run endpoint.
- 2026-06-12: Added a signal journal review/outcome endpoint.
- 2026-06-12: Made the CI contract explicit for Profit Discipline MVP gates.
- 2026-06-12: Added a strategy promotion readiness surface.
- 2026-06-12: Added a paper/shadow divergence review write path.
- 2026-06-12: Added a v0.2 acceptance audit manifest and aligned the goal
  checklist with deterministic evidence.
- 2026-06-12: Started v0.3 shadow-trading reliability work with schema
  versioning and idempotent same-date/action order facts.
- 2026-06-12: Added the first v0.3 data-quality gate to daily shadow runs.
- 2026-06-12: Started the Daily + Intraday Decision Cockpit API surface.
- 2026-06-12: Added the first read-only intraday decision lane.
- 2026-06-12: Attached persisted strategy validation evidence to decision
  candidates.
- 2026-06-12: Added current-state aggregation to decision summaries.
- 2026-06-12: Added the first frontend Decision Cockpit surface.
- 2026-06-12: Added a deterministic v0.3 Decision Cockpit acceptance path.
- 2026-06-12: Completed the v0.3 checklist audit.
- 2026-06-12: Fixed Web cockpit responsive containment.
- 2026-06-14: Improved portfolio analysis responsiveness and audit surfaces.
- 2026-06-14: Moved the return calendar into the Overview cockpit.
- 2026-06-14: Improved the Overview return-calendar empty state.
- 2026-06-14: Consolidated the Overview performance module.
- 2026-06-14: Polished the Overview return-calendar fallback language and
  holdings display.
- 2026-06-14: Connected explainability attribution to deterministic daily
  portfolio valuation when historical price cache is available.
- 2026-06-14: Tightened the return-calendar attribution contract.
- 2026-06-14: Aligned the return calendar with China-market non-trading day
  semantics.
- 2026-06-14: Fixed return-calendar valuation-gap attribution.
- 2026-06-14: Connected return-calendar daily valuation to the authoritative
  local OHLC cache.
- 2026-06-14: Added traceable daily-change breakdowns to the return calendar.
- 2026-06-14: Clarified ledger and holding labels in the web cockpit.
- 2026-06-15: Tightened current-day return attribution and ledger naming.
- 2026-06-15: Separated current valuation from audited return-calendar
  attribution.
- 2026-06-15: Tightened live quote freshness semantics for fund estimates.
- 2026-06-15: Made TuShare fund permission fallback auditable in the cockpit.
- 2026-06-15: Added a Settings data-source operations surface.
- 2026-06-15: Tightened the Settings cockpit density around backend operations.
- 2026-06-15: Added Settings runtime-boundary and safety-register surfaces.
- 2026-06-15: Began cockpit-density cleanup on the Decision page.
- 2026-06-15: Reworked the Risk page summary into boundary and blocking
  registers.
- 2026-06-15: Standardized portfolio return percentages to two decimal places.
- 2026-06-15: Clarified the Portfolio holdings quote board summary cards.
- 2026-06-15: Deduplicated the Portfolio holdings quote board detail surface.
- 2026-06-15: Split Portfolio quote summaries from instrument detail.
- 2026-06-15: Redesigned the Portfolio positions entry affordance.
- 2026-06-15: Upgraded the holding-detail and Market price-structure surface
  from a compact sparkline into a K-line chart with selectable ranges.
- 2026-06-15: Tightened the holding-detail page header.
- 2026-06-15: Added account-level manual trade commission configuration.
- 2026-06-15: Fixed return-calendar detail labels for aggregated periods.
- 2026-06-18: Added research-only account strategy assignment and attribution
  evidence surfaces without enabling automatic trading.
- 2026-06-18: Added a strategy contribution estimate API and Backtest surface
  that separates linked-fill unrealized P/L, commission, slippage, and net
  contribution while excluding manual trades, cash flows, and missing-evidence
  movement by default.
- 2026-06-18: Added five-tier Backtest P/L attribution status copy for account
  strategy evidence: not started, partial, stale, blocked, and complete.
- 2026-06-18: Extended account strategy attribution evidence references across
  signal, action, risk, review, order, and fill records.
- 2026-06-18: Added evidence-gated strategy contribution surfaces to Overview
  and Portfolio while reusing Backtest and Decision attribution gates.
- 2026-06-22: Fixed return-calendar valuation status semantics so live,
  confirmed, and complete periods display returns normally; cache, stale,
  estimated, and confirmed-NAV-missing periods display returns with an
  unconfirmed marker; and only missing or unavailable prices render as
  valuation gaps.
- 2026-06-22: Added acceptance-audit evidence for the 1D net-value chart
  contract. Existing frontend and backend deterministic tests now prove that
  the 1D chart can show intraday market movement, cash-flow changes,
  stock/fund movement, fund confirmation state, stale status, and missing
  quote-dependent observations without fabricating values. This is audit
  wiring only; it does not change broker submission, trading behavior, risk
  gates, or manual-confirmation defaults.
- 2026-06-22: Completed the v1.1 paper broker and OMS backend coverage slice.
  Paper broker tests now cover paper-only fills, partial fills, cancellations,
  rejections, slippage, fee/tax cost modeling, and OMS idempotency without
  mutating the production ledger or introducing broker order submission.
- 2026-06-22: Started v1.2 Broker Evidence Connector with a capability-based
  read-only connector contract and deterministic fake connector fixtures for
  account, cash, position, order, fill, and health facts. The connector surface
  does not expose broker order submission.
- 2026-06-22: Added local read-only broker connector configuration parsing for
  ignored `config.json`. Connector config accepts client path and account alias
  only, rejects password/secret/token/credential fields, and keeps source
  examples synthetic.
- 2026-06-22: Added read-only broker connector evidence normalization. Synthetic
  connector snapshots now convert fills, cash snapshots, and position snapshots
  into staged broker evidence that can feed reconciliation without mutating the
  production ledger or enabling broker order submission.
- 2026-06-22: Wired staged broker evidence into shared Account Truth gate
  construction. Decision summaries and Strategy Lab promotion readiness now
  block when latest read-only broker evidence reconciles to unresolved material
  differences, while preserving manual-confirm-only live-like behavior.
- 2026-06-22: Added deterministic fake connector evidence-state coverage for
  healthy, disconnected, stale, permission-limited, duplicate, and incomplete
  snapshots. Disconnected snapshots now block without emitting stale evidence
  rows, incomplete snapshots surface explicit diagnostics, and duplicate
  connector rows are marked deterministically. This remains read-only broker
  evidence and does not submit broker orders, mutate production ledger entries,
  or change manual-confirmation defaults.
- 2026-06-22: Completed the v1.2 broker evidence reconciliation detail slice.
  Canonical broker statement previews and staged evidence now preserve optional
  transfer-fee and broker cost-basis method fields. Reconciliation reports
  expose trade gross amount, signed net cash impact, fee, tax, transfer-fee,
  and cost-basis differences as reviewable items. This is audit evidence only;
  it does not mutate production ledger entries, submit broker orders, or change
  manual-confirmation defaults.
- 2026-06-22: Added shared public formatting for generated Trading manual-order
  notes. Decision-generated order notes now render as user-readable copy on
  Trading queue and audit surfaces without exposing internal action ids; order
  execution behavior and manual-confirmation defaults are unchanged.
- 2026-06-22: Moved the Overview latest-ledger cards onto the shared public
  ledger formatter for entry titles, instrument labels, and cleaned public
  notes. Legacy note prefixes and technical note segments remain hidden from
  the user-facing ledger cards.
- 2026-06-22: Stopped Decision manual-order preparation from writing internal
  signal action ids into order notes. Prepared manual orders now use the
  shared public queue note from the Trading API hook while preserving manual
  confirmation and broker-submit defaults.
- 2026-06-22: Localized Decision signal-journal audit event labels on
  user-facing candidate and journal surfaces. Dotted internal event keys remain
  backend audit identifiers, while the Web UI now shows public event copy
  without changing signal, journal, risk-gate, or manual-confirm behavior.
- 2026-06-22: Connected Risk explainability recent-driver and timeline titles
  to the shared public ledger formatter for generated ledger kinds. Internal
  ledger kind values such as cash-flow entry types now render as localized
  public titles while existing human-authored titles are preserved. This is UI
  formatting only; it does not change risk computation, ledger facts, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Localized Account Truth review evidence references for
  user-facing reconciliation items. Broker evidence ids now render as readable
  source, subject, event-type, and import-run labels instead of raw
  machine-formatted reference strings. This is review-surface formatting only;
  it does not change import parsing, reconciliation, ledger mutation, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Localized Account Truth reconciliation item categories on the
  Web review surface. Difference cards now display public labels such as cash,
  position, fee, and cost basis through the shared public-label formatter
  instead of rendering raw backend category fields. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
- 2026-06-22: Replaced Account Truth reconciliation report summary shorthand
  such as raw cash/fee delta labels with localized public labels for cash
  difference and fee difference. This is report-summary display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
- 2026-06-22: Localized generated Account Truth reconciliation detail copy on
  the Web review surface. Known backend-generated reconciliation explanations
  now pass through the shared public-note formatter in Chinese locale instead
  of exposing English operational sentences. This is detail-text display
  formatting only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
- 2026-06-22: Added stable Account Truth reconciliation detail codes alongside
  the legacy detail text. Reconciliation item generation and the Account Truth
  report API now expose a machine-stable `detail_code`, and the Web review
  surface prefers that code for localized public-note rendering while keeping
  old `detail` payloads as fallback. This is an additive review-surface
  contract change only; it does not change reconciliation math, manual review
  decisions, ledger mutation, broker behavior, or manual-confirmation defaults.
- 2026-06-22: Structured dynamic Account Truth reconciliation detail context
  for broker cost-basis method evidence. Cost-basis reconciliation items now
  expose `detail_context` for values such as the broker cost-basis method, and
  the Web review surface renders those context fields as localized labels and
  values instead of exposing raw method codes in generated detail text. This is
  an additive review-surface contract change only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Added category-aware numeric formatting to Account Truth
  reconciliation item values on the Web review surface. Position differences
  now show share units, cost-basis differences show four-decimal CNY price
  values, and cash/fee/tax-like differences use CNY amount formatting instead
  of unqualified raw numbers. This is display formatting only; it does not
  change reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Extended Account Truth report summaries to use the same
  category-aware money formatting for cash and fee differences. Report cards
  now display localized CNY amounts instead of raw decimal strings while the
  reconciliation report payload remains unchanged. This is display formatting
  only; it does not change reconciliation math, manual review decisions,
  ledger mutation, broker behavior, or manual-confirmation defaults.
- 2026-06-22: Added tax-difference visibility to Account Truth reconciliation
  report summary cards. Existing `tax_difference` payload values now render as
  localized CNY amounts alongside cash and fee differences, making fee/tax
  evidence visible without changing the reconciliation payload or accounting
  calculations. This is display formatting only; it does not change
  reconciliation math, manual review decisions, ledger mutation, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Extended the shared public ledger formatter to render structured
  trade cost facts on Web ledger surfaces. Activity and Overview ledger rows
  can now show gross trade amount, signed net cash impact, commission, stamp
  tax, transfer fee, and localized cost-basis method labels from structured
  fields instead of hiding those facts in notes. This is display formatting
  only; it does not change ledger persistence, fee calculation, trading,
  broker behavior, or manual-confirmation defaults.
- 2026-06-22: Moved holding-detail ledger traces onto the same structured
  ledger cost formatter used by Activity and Overview. Holding detail now
  exposes gross amount, signed net cash impact, commission, stamp tax,
  transfer fee, and localized cost-basis method labels from structured ledger
  fields while keeping public notes separate. This is display formatting only;
  it does not change ledger persistence, fee calculation, trading, broker
  behavior, or manual-confirmation defaults.
- 2026-06-22: Localized Risk explainability ledger fallback details for
  generated cash-flow and ledger adjustment events. Risk review surfaces now
  use the active Web language for public fallback descriptions after shared
  ledger-note cleanup removes internal import notes. This is display
  formatting only; it does not change risk math, ledger persistence, trading,
  broker behavior, or manual-confirmation defaults.
- 2026-06-23: Moved Backtest strategy validation rows to use localized
  strategy display names as the primary label while keeping strategy ids as
  secondary audit metadata. This makes research-gate status easier to read
  without changing strategy execution, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Moved Decision candidate strategy evidence to the same
  user-facing strategy display-name convention. Candidate cards and evidence
  chains now show localized strategy names first while preserving internal
  strategy ids as secondary audit metadata. This is display formatting only; it
  does not change decision generation, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Added strategy identity to the Web strategy contribution report
  using localized display names first and internal strategy ids as secondary
  audit metadata. This makes contribution evidence attributable to a readable
  strategy without changing attribution math, ledger facts, broker behavior,
  trading, risk gates, or manual-confirmation defaults.
- 2026-06-23: Extracted shared Web strategy display formatting for readable
  strategy names and secondary audit ids. Backtest, Decision, and Strategy
  Contribution surfaces now use the same formatter instead of page-local
  copies. This is display formatting only; it does not change strategy
  execution, attribution math, ledger facts, broker behavior, trading, risk
  gates, or manual-confirmation defaults.
- 2026-06-23: Risk explainability events now hydrate shared ledger formatting
  with instrument names from the current account snapshot. Generated broker or
  ledger event titles that only carry a symbol now render readable name +
  symbol labels in recent drivers, timeline events, and position drivers. This
  is display formatting only; it does not change risk math, ledger
  persistence, broker behavior, trading, risk gates, or manual-confirmation
  defaults.
- 2026-06-23: Localized Risk blocking-register alert kinds so user-facing risk
  cards show readable labels such as cash buffer instead of raw internal codes.
  This is display formatting only; it does not change risk calculations,
  trading, broker behavior, risk gates, or manual-confirmation defaults.
- 2026-06-23: Localized Risk blocking-register severity labels so user-facing
  alert badges show review labels such as warning instead of raw severity
  codes. This is display formatting only; it does not change risk
  calculations, trading, broker behavior, risk gates, or manual-confirmation
  defaults.
- 2026-06-23: Promoted cash-interest ledger entries to first-class cash income
  in portfolio projection, explainability timeline flow breakdown, and the
  shared public ledger formatter. Activity now reuses shared action titles,
  short labels, signed amounts, and cash-impact semantics instead of
  page-local ledger type branches. This changes cash-interest classification
  from market movement to income flow where evidence exists; it does not change
  ledger persistence, fee math, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Moved holding-detail ledger traces onto the shared public ledger
  activity summary for action titles, cash-impact wording, and signed primary
  amounts while keeping structured gross amount, net cash impact, fee, tax, and
  transfer-fee lines visible. Cost-basis method is no longer mixed into
  execution detail lines and should remain in dedicated cost-basis views. This
  is presentation alignment only; it does not change ledger persistence, fee
  math, broker behavior, trading, risk gates, or manual-confirmation defaults.
- 2026-06-23: Updated portfolio projection cost math to consume structured
  trade fee breakdowns when present, including commission, stamp tax, transfer
  fee, and other fee components. This keeps local moving-average buy cost and
  cash projection aligned with the same ledger fee evidence shown in user
  surfaces. It does not mutate ledger entries, change broker behavior, submit
  orders, bypass risk gates, or alter manual-confirmation defaults.
- 2026-06-23: Added Portfolio holding-detail support for broker-facing
  cost-basis evidence when the position API provides it. The Web detail view
  now distinguishes local moving average cost, broker displayed unit cost,
  broker displayed cost basis, localized cost-basis method, and the difference
  between broker and local cost-basis totals. The positions API can carry these
  optional evidence fields without mutating ledger entries. This is
  presentation and payload-surface work only; it does not change projection
  math, reconciliation decisions, broker behavior, trading, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Hydrated Portfolio position cost-basis fields from staged broker
  evidence when no explicit broker cost-basis fields are already attached to
  the projected position. The positions API now reads the latest imported
  position snapshot cost basis from Account Truth evidence and derives broker
  displayed unit cost, broker displayed total cost basis, local-vs-broker
  difference, method, and availability status. This uses already-imported
  evidence only; it does not read broker credentials, mutate the production
  ledger, submit orders, bypass risk gates, or change manual-confirmation
  defaults.
- 2026-06-23: Added a Portfolio holding-detail cost-basis review prompt when
  broker displayed cost evidence differs from Karkinos local moving-average cost
  by a material display threshold. The prompt is localized and points users back
  to Account Truth evidence before relying on cost-basis P/L. This is
  presentation-only audit guidance; it does not change ledger math, broker
  behavior, trading, risk gates, or manual-confirmation defaults.
- 2026-06-23: Moved the Activity page net-cash-impact summary onto the shared
  public ledger summary formatter. The page now respects structured
  `net_cash_impact` evidence and first-class cash-interest entries instead of
  using a local `entry_type` branch. This is UI summary alignment only; it does
  not mutate ledger entries, change broker behavior, submit orders, bypass risk
  gates, or alter manual-confirmation defaults.
- 2026-06-23: Extended the shared public ledger execution-detail formatter so
  holding details, Activity audit rows, and Risk explainability cards show
  structured net cash impact alongside gross amount, quantity, price, and fee
  evidence. This is display formatting only; it does not mutate ledger entries,
  change fee calculation, change broker behavior, submit orders, bypass risk
  gates, or alter manual-confirmation defaults.
- 2026-06-23: Updated the Risk page manual approval table to resolve
  instrument display names from the same portfolio position evidence used by
  the Trading page, so pending manual approvals show readable name + symbol
  labels instead of symbol-only rows. This is presentation-only; it does not
  change order approval, rejection, broker behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Added explicit public labels for reconciliation fee, tax, gross
  amount, net cash impact, and transfer-fee categories so Account Truth review
  cards show specific user-facing difference types instead of generic fallback
  labels. This is label formatting only; it does not change reconciliation
  math, review decisions, ledger mutation, broker behavior, risk gates, or
  manual-confirmation defaults.
- 2026-06-23: Paper broker fill metadata now records the structured fee
  breakdown produced by the shared commission contract, including commission,
  stamp tax, transfer fee, other fees, fee rule ID, and known limitations while
  preserving the legacy total commission field for compatibility. This is
  paper-only simulation evidence; it does not mutate the production ledger,
  submit broker orders, bypass risk gates, or alter manual-confirmation
  defaults.
- 2026-06-23: Decision candidate cards now pass backend detail notes through
  the shared public-note formatter before rendering, matching the existing
  signal action queue behavior. This prevents internal strategy-assignment
  evidence phrases from leaking into localized user-facing action cards. This
  is display formatting only; it does not change decision generation, risk
  gates, broker behavior, order submission, or manual-confirmation defaults.
- 2026-06-23: Risk blocking-register detail text now uses the shared
  public-note formatter, and Account Truth review tests pin specific
  reconciliation action-code localization. This prevents internal market data
  and review codes from appearing in localized review surfaces. This is
  display formatting and regression coverage only; it does not change risk
  calculations, reconciliation math, broker behavior, order submission, or
  manual-confirmation defaults.
- 2026-06-23: Account strategy contribution reports now expose a derived
  strategy-health status with `healthy`, `degraded`, `stale`, `paused`, and
  `needs_review` states, plus machine-readable reasons. The Web strategy
  contribution card renders the health status with localized labels. This is
  a read-only evidence and display slice; it does not change strategy
  assignment, contribution math, risk gates, broker behavior, order
  submission, or manual-confirmation defaults.
- 2026-06-23: Overview ledger cards now use a shared ledger dashboard
  presentation formatter for action titles, structured details, amounts, and
  public notes instead of local one-off formatting helpers. This continues the
  v1.4 shared public ledger formatter work without changing ledger storage,
  accounting math, broker behavior, order submission, or manual-confirmation
  defaults.
- 2026-06-23: Shared public ledger notes now suppress generated cash and
  dividend remarks when the same amount and entry type are already available
  as structured ledger fields. This keeps core accounting facts such as cash
  interest amounts out of free-text public notes while preserving user-authored
  notes. This is display formatting only; it does not change ledger storage,
  accounting math, broker behavior, order submission, or manual-confirmation
  defaults.
- 2026-06-23: Risk/explainability ledger details now reuse the shared
  execution-detail formatter for non-trade cash and dividend events, so
  generated cash movements expose structured amounts instead of generic
  fallback text or legacy English operational notes. This is display
  formatting only; it does not change ledger storage, accounting math, broker
  behavior, order submission, or manual-confirmation defaults.
- 2026-06-23: Account Truth review now localizes known broker cost-basis
  mismatch detail text even when the backend only provides the legacy English
  detail string and no `detail_code`. This continues the v1.4 review-surface
  cleanup for public notes and does not change reconciliation math, review
  decisions, ledger mutation, broker behavior, order submission, or
  manual-confirmation defaults.
- 2026-06-24: Extended the shared ledger evidence-reference formatter so
  Account Truth review cards can show instrument display name plus symbol for
  broker evidence references, including trade and position-snapshot evidence.
  This is user-facing formatting only; it does not change reconciliation math,
  review decisions, ledger mutation, broker behavior, order submission, or
  manual-confirmation defaults.
- 2026-06-24: Backtest fill tables now render buy/sell directions through the
  shared public ledger action labels, so saved research reports use localized
  user-facing trade directions instead of raw `BUY` / `SELL` text. This is
  report display formatting only; it does not change backtest fills, cost
  calculation, broker behavior, order submission, risk gates, or
  manual-confirmation defaults.
- 2026-06-24: Manual order approval tables now render order directions through
  shared public labels, including a safe localized fallback for future or
  unknown backend side codes. This is approval-table presentation only; it does
  not change order approval, rejection, broker behavior, order submission,
  risk gates, or manual-confirmation defaults.
- 2026-06-24: Overview pending-approval cards now show instrument display name
  plus symbol and render order directions through shared public labels,
  including a safe fallback for future backend side codes. This is dashboard
  presentation only; it does not change order approval, rejection, broker
  behavior, order submission, risk gates, or manual-confirmation defaults.
- 2026-06-24: Activity ledger source labels now use localized public fallback
  copy for future or unknown non-empty source codes instead of rendering raw
  internal source ids. This is ledger presentation only; it does not change
  ledger storage, accounting calculations, broker behavior, order submission,
  risk gates, or manual-confirmation defaults.
- 2026-06-24: Portfolio positions now show broker-versus-local cost-basis
  differences when broker cost-basis evidence includes a non-zero difference,
  using localized cost-basis copy in both desktop rows and mobile cards. This
  is cost-basis presentation only; it does not recalculate position cost,
  mutate ledger entries, change broker behavior, submit orders, or bypass
  manual confirmation.
- 2026-06-24: Exchange bond / convertible-bond fee modeling now returns the
  same structured fee-breakdown contract as A-share and ETF calculations, and
  manual trade fee resolution can produce bond fee evidence without stock stamp
  tax or transfer-fee assumptions. This is deterministic fee-evidence plumbing
  only; it does not enable broker submission, change default execution, or
  bypass manual confirmation.
- 2026-06-24: Activity manual-trade fee prefill now stays a UI estimate unless
  the user edits the fee field; default trade submissions omit explicit
  commission so the backend configured fee contract can generate structured
  commission, stamp-tax, transfer-fee, other-fee, total-fee, and fee-rule
  evidence. Edited fees still submit as manual fee input. This does not change
  broker behavior, order submission, risk gates, or manual-confirmation
  defaults.
- 2026-06-24: Public operational-note formatting now treats dotted backend
  note identifiers the same as snake-case note identifiers, so Trading order
  rows, Trading audit rows, manual approval risk hints, and Account Truth
  review cards fall back to localized review copy instead of rendering raw
  backend codes. This is display formatting only; it does not change order
  state, review state, broker behavior, risk gates, automatic trading
  defaults, or manual-confirmation requirements.
- 2026-06-24: Shared public ledger-note formatting now splits semicolon and
  multiline note segments before suppressing generated structured trade facts,
  so a user remark can remain visible while repeated quantity, price, amount,
  and fee text stays in structured fields. This is display formatting only; it
  does not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-25: Shared public review labels now cover strategy review promotion
  states and Account Truth manual-review action buttons, so review surfaces
  show localized user actions such as simulation-review readiness and
  ledger-correction candidates instead of backend status nouns or generic
  fallback labels. This is display formatting only; it does not change
  reconciliation math, review persistence semantics, ledger mutation, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-25: Portfolio compact holding cards now label locally projected
  cost-basis evidence as ledger-projected unit cost instead of broker-displayed
  cost when no broker cost-basis evidence has been imported. This is display
  formatting only; it does not change cost-basis math, ledger mutation, broker
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-25: Backtest fills now carry the same structured fee-breakdown
  payload used by paper broker evidence, manual trade previews, and ledger
  projections while preserving the legacy total `commission` field. The v1.4
  broker fee / cost-basis acceptance audit now records this shared fee-contract
  evidence. This is research and simulation evidence only; it does not submit
  broker orders, change live-like defaults, bypass risk gates, or bypass
  manual confirmation.
- 2026-06-25: Account Truth cost-basis reconciliation now compares broker
  reported per-share cost basis against the Karkinos broker/local cost-basis
  method context and exposes comparison unit, precision policy, and rounding /
  fee-allocation limitations to the Web review surface. The v1.4 broker fee /
  cost-basis acceptance audit records this evidence. This is reconciliation
  evidence only; it does not mutate ledger entries, submit broker orders,
  change risk gates, enable automatic trading, or bypass manual confirmation.
- 2026-06-25: The v1.4 broker fee / cost-basis acceptance audit now records
  the shared public ledger formatter contract used across Overview, Activity,
  Portfolio holding detail, Risk explainability, Decision, and Account Truth
  review surfaces. Existing Web tests cover localized action titles, entry
  types, instrument names, timestamps, quantities, prices, amounts, fees, cash
  impact, evidence references, and suppression of internal ledger/action codes.
  This is presentation/audit-manifest evidence only; it does not change ledger
  storage, accounting math, broker behavior, order submission, risk gates,
  automatic trading defaults, or manual-confirmation requirements.
- 2026-06-25: Shared public ledger-note formatting now suppresses dash-prefixed
  legacy manual-trade notes such as generated "manual trade - instrument buy"
  facts when the same quantity, price, amount, fee, and cash-impact values are
  already available as structured fields. The v1.4 acceptance audit now records
  the broader user-facing contract that raw entry types, reason codes, legacy
  prefixes, duplicate symbol/name fragments, and mixed operational notes should
  not leak into public ledger surfaces. This is display cleanup only; it does
  not change ledger storage, accounting math, broker behavior, order
  submission, risk gates, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-25: Shared public ledger-note formatting now keeps genuine user
  remarks while suppressing generated accounting-fact note segments such as
  cost-basis, net-cash-impact, amount, quantity, price, and fee fragments when
  those facts already have structured fields. The v1.4 acceptance audit records
  the localized public-note contract so future ledger surfaces do not smuggle
  core accounting facts into free-form notes. This is display/audit evidence
  only; it does not change ledger storage, accounting math, broker behavior,
  order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-25: Portfolio cost views now consistently distinguish local moving
  average buy cost from broker displayed cost-basis evidence across the
  positions table and holding detail page. The positions table now prefers the
  explicit broker-displayed unit cost from the API when present instead of
  deriving a unit value from total remaining cost, matching the holding detail
  page and reducing confusion when broker precision or remaining-cost methods
  differ. The v1.4 acceptance audit records the localized Portfolio cost-view
  evidence. This is display/evidence handling only; it does not change cost
  calculation, ledger storage, broker connector behavior, order submission,
  risk gates, automatic trading defaults, or manual-confirmation requirements.
- 2026-06-25: The v1.4 acceptance audit now records the existing sell-side net
  proceeds projection evidence: partial sells reduce broker-display-style
  remaining cost by proceeds after commission, stamp tax, transfer fees, and
  other configured fee components, while realized P/L uses the same net cash
  math. This records existing deterministic projection and ledger-fee evidence;
  it does not change cost calculation, ledger storage, broker connector
  behavior, order submission, risk gates, automatic trading defaults, or
  manual-confirmation requirements.
- 2026-06-25: Manual trade fee resolution now treats `convertible_bond` as an
  exchange-bond fee class for configured ledger and preview fee evidence,
  preserving commission, other-fee, total-fee, fee-rule, and net-cash-impact
  fields without adding stock stamp tax or transfer fees. Deterministic backend
  tests now cover the v1.4 fee/cost-basis contract across A-share fees,
  Shanghai/Shenzhen transfer-fee differences, ETF/fund-style fees,
  convertible-bond fees, broker displayed cost basis, realized P/L, and net
  cash impact. This is fee evidence and ledger projection handling only; it
  does not introduce broker order submission, automatic real-money trading,
  broker password storage, or changes to manual-confirmation requirements.
- 2026-06-25: The v1.4 acceptance audit now records frontend coverage for
  user-facing fee and cost-basis surfaces: Activity, Trading, Portfolio
  positions, holding detail, manual trade preview, and shared ledger formatting
  tests cover fee-breakdown display, cost-basis-method labels, broker/local
  cost-basis difference warnings, and suppression of raw entry types, fee-rule
  ids, backend note codes, and internal reason codes. This is test/audit
  coverage only; it does not change UI behavior, ledger storage, broker
  behavior, order submission, automatic trading defaults, or manual-confirmation
  requirements.
- 2026-06-26: Portfolio cockpit responses now include read-only construction
  recommendation evidence for action-linked positions. A recommendation is
  marked actionable only when account-truth status is `pass` and the matching
  risk gate is `passed`; missing/degraded account truth or blocked/unchecked
  risk returns required review actions and a localized rationale instead. This
  is portfolio-construction evidence only; it does not write production ledger
  entries, submit broker orders, enable automatic trading, or bypass manual
  confirmation.
- 2026-06-26: Portfolio now surfaces cockpit construction recommendations in a
  localized read-only card next to strategy attribution and risk summaries.
  Blocked/degraded items show user-readable review actions instead of raw
  internal action codes, while actionable items are labeled as manual-review
  candidates only after account-truth and risk gates pass. This is UI evidence
  surfacing only; it does not write production ledger entries, submit broker
  orders, enable automatic trading, or bypass manual confirmation.
- 2026-06-26: Portfolio holding detail now links each held instrument directly
  into the Backtest single-instrument strategy research flow with the current
  symbol and asset class prefilled. This improves the user-visible path from a
  specific holding to dataset snapshot, strategy registry, after-cost backtest,
  signal preview, risk preview, paper/shadow simulation, and attribution
  boundary review. It is navigation/context handoff only; it does not run a
  strategy automatically, write ledger entries, submit broker orders, enable
  automatic trading, or bypass manual confirmation.
- 2026-06-26: Portfolio-to-Backtest handoff now carries an explicit
  `source=portfolio` query context, and Backtest displays a localized holding
  research context instead of reusing decision handoff wording. This keeps the
  single-instrument strategy loop user-readable when launched from a holding
  detail page. It remains navigation/context handoff only; it does not run a
  strategy automatically, write ledger entries, submit broker orders, enable
  automatic trading, or bypass manual confirmation.
- 2026-06-26: Backtest run results now keep a localized single-instrument run
  context summary beside the evidence chain, including handoff source, symbol,
  asset class, strategy, and the research-only/no-broker-order boundary. This
  helps users keep the selected holding context visible while reviewing dataset,
  signal, risk, paper/shadow, and attribution evidence. It does not change
  strategy execution, ledger writes, broker order submission, automatic trading,
  or manual-confirmation defaults.
- 2026-06-26: Backtest run context now links back to the current instrument's
  Portfolio holding detail page, closing the user-visible loop from holding
  evidence into strategy research and back to holding/PnL review. The link is a
  read-only navigation affordance; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
- 2026-06-26: Portfolio holding detail now shows a localized strategy
  attribution boundary card whenever holding PnL is still account-level
  evidence. The card explains that PnL is not assigned to a strategy until a
  strategy signal, review decision, order, and fill can all be linked, and it
  points back to the single-instrument strategy research evidence flow. This is
  read-only attribution guidance; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
- 2026-06-26: Portfolio holding detail now upgrades the attribution boundary
  card only when a symbol-level account-strategy assignment matches the current
  holding and linked fill/evidence references exist. The card shows strategy,
  contribution status, linked-fill count, and evidence-reference count, but it
  still withholds strategy P/L amounts until attribution review is complete.
  This is read-only evidence surfacing; it does not mutate attribution records,
  production ledger entries, broker orders, or manual-confirmation state.
- 2026-06-26: Account Strategy now exposes a read-only holding-level
  attribution report at `/api/account-strategy/holdings/{symbol}/attribution`.
  The report filters linked signal, action, risk, review, order, and fill
  evidence to the requested symbol, and Portfolio holding detail uses that
  symbol-level report before showing evidence counts. It remains evidence
  indexing only; it does not calculate strategy P/L for the holding, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
- 2026-06-26: Portfolio holding detail now renders the symbol-level
  attribution report as a localized evidence chain. Signal, candidate-action,
  risk, review, order, and fill references are shown as user-readable evidence
  types with audit identifiers instead of raw internal ref strings. This is
  read-only audit surfacing; it does not attribute P/L by default, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
- 2026-06-26: Portfolio holding detail now includes a localized attribution
  review readiness gate. The gate shows whether strategy signal, manual
  review, risk check, order evidence, and fill evidence are linked for the
  current holding, and it keeps the explicit boundary that holding P/L is not
  assigned to the strategy until review is complete. This is explanatory UI
  only; it does not calculate strategy-attributed holding P/L, mutate
  production ledger entries, submit broker orders, enable automatic trading, or
  bypass manual confirmation.
- 2026-06-26: Shared Web evidence-reference formatting now turns internal
  dataset, signal, risk, paper/shadow, order, and fill reference strings into
  localized public audit labels before they appear in Portfolio attribution
  surfaces. The raw evidence identifiers remain in API/storage for auditability,
  but user-facing evidence chains no longer expose strategy ids, preview ids,
  or colon-delimited backend refs. This is presentation-only; it does not
  mutate attribution records, production ledger entries, broker orders,
  automatic trading defaults, or manual-confirmation state.
- 2026-06-26: English Backtest copy now uses user-facing "simulation review"
  wording instead of the internal "paper/shadow" workflow label across the
  single-instrument loop, signal preview, evidence chain, and next-step
  messages. Internal API keys and stored evidence refs are unchanged. This is
  presentation-only; it does not mutate attribution records, production ledger
  entries, broker orders, automatic trading defaults, or manual-confirmation
  state.
- 2026-06-27: The single-instrument strategy loop acceptance audit now treats
  localized Web UX and hidden raw evidence refs as an explicit product
  contract. Its manifest references Backtest, Portfolio holding detail, shared
  public-label tests, and copy tests so CI/release review can catch regressions
  where internal reason codes, workflow labels, or colon-delimited evidence refs
  leak back into user-facing strategy-loop surfaces. This is audit coverage
  only; it does not mutate attribution records, production ledger entries,
  broker orders, automatic trading defaults, or manual-confirmation state.
- 2026-06-27: Overview now starts with a daily asset workbench that puts account
  state, A-share/fund/total daily PnL, data confidence, manual-confirmation
  queue state, and strategy-evidence readiness before chart and position
  details. The detailed quote diagnostics, equity curve, return calendar,
  ledger, strategy contribution report, and holding table remain available
  below the first screen. This is presentation-only; it does not mutate
  valuation, ledger, trading, broker, risk-gate, automatic-trading, or
  manual-confirmation behavior.
- 2026-07-02: v1.7 broker gateway now requires account-truth, research,
  pre-trade risk, paper/shadow, and manual-confirmation evidence before
  previewing or recording a manual broker ticket. Manual-ticket preview remains
  read-only, ticket creation records an audit event only, and both paths keep
  `submitted_to_broker=false`.
- 2026-07-02: Added execution reconciliation routes at
  `/api/execution-reconciliation/runs` so OMS order state, broker gateway
  events, and staged broker trade evidence can be compared from the API. The
  reconciliation output identifies missing gateway actions, missing broker
  evidence, and broker evidence awaiting review; it does not mutate production
  ledger entries, submit broker orders, cancel broker orders, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-02: Broker Gateway now exposes read-only connector configuration
  health at `/api/broker-gateway/connectors/health`. The endpoint reports
  configured connector ids, aliases, read capabilities, and incomplete/disabled
  states without contacting broker clients, storing credentials, submitting
  orders, cancelling orders, or enabling automatic trading.
- 2026-07-04: Execution reconciliation now classifies same-symbol/same-side
  broker trade evidence with a quantity mismatch as
  `broker_evidence_mismatch` instead of treating it as missing evidence. This
  makes manual-ticket execution deviations visible for operator review without
  mutating production ledger entries, submitting broker orders, cancelling
  broker orders, or bypassing manual confirmation.
- 2026-07-04: Broker Gateway now supports manual-ticket dry-run validation at
  `/api/broker-gateway/orders/{order_id}/manual-ticket/dry-run`. Accepted and
  rejected dry-runs are recorded as gateway audit events, while OMS status stays
  unchanged and `submitted_to_broker=false`; the path does not contact broker
  clients, submit orders, cancel orders, mutate ledger entries, or bypass
  manual confirmation.
- 2026-07-04: Broker Gateway now exposes a read-only manual-ticket query
  contract at `/api/broker-gateway/orders/{order_id}/query`. It returns local
  OMS state, gateway audit events, and staged broker trade/fill evidence for
  one order, and it marks matching staged fills without contacting broker
  clients, creating gateway events, mutating OMS status, mutating production
  ledger entries, submitting orders, or cancelling orders.
- 2026-07-04: Broker Gateway now exposes read-only staged account facts at
  `/api/broker-gateway/account-facts`. The endpoint summarizes cash balances,
  positions, and fills from imported broker evidence only; it does not contact
  broker clients, store credentials, create gateway events, mutate OMS status,
  mutate production ledger entries, submit orders, cancel orders, or imply that
  staged facts are a live broker account snapshot.
- 2026-07-04: Broker Gateway now exposes a disabled broker-cancel contract at
  `/api/broker-gateway/orders/{order_id}/broker-cancel`. The endpoint rejects
  broker-side cancellation by default, records a `live_cancel_rejected` audit
  event with `submitted_to_broker=false` and `cancelled_at_broker=false`, and
  does not contact broker clients, mutate OMS status, mutate production ledger
  entries, submit orders, cancel orders, or bypass manual confirmation.
- 2026-07-04: Broker Gateway manual-ticket preview, dry-run, and creation now
  enforce the global kill switch from `TradingControlState`. When the kill
  switch is enabled, preview/create return a rejected validation error without
  mutating OMS status; dry-run records a rejected gateway audit event while
  keeping `submitted_to_broker=false` and without contacting broker clients,
  mutating production ledger entries, submitting orders, or cancelling orders.
- 2026-07-04: Broker Gateway status now exposes the global kill-switch state.
  When the kill switch is enabled, the `manual_ticket` gateway reports
  `blocked_by_kill_switch`, disables preview/dry-run capabilities in the
  status payload, and still keeps broker submission/cancellation disabled.
- 2026-07-04: Decision Cockpit now reads `/api/broker-gateway/status` and
  shows broker gateway status, kill-switch state, manual-ticket capability,
  and disabled live execution as read-only automation evidence. The UI adds no
  broker submit or cancel controls and does not mutate OMS status, production
  ledger entries, broker orders, automatic-trading defaults, or manual
  confirmation state.
- 2026-07-06: Decision Cockpit now also reads broker connector health and
  staged account facts from `/api/broker-gateway/connectors/health` and
  `/api/broker-gateway/account-facts`. It shows read capability, submit/cancel
  disabled state, broker evidence count, cash/position/fill evidence counts,
  and connector ids without local client paths or credentials; the surface is
  read-only and does not contact broker clients, submit/cancel broker orders,
  mutate OMS status, mutate production ledger entries, enable automatic
  trading, or bypass manual confirmation.
- 2026-07-06: Decision Cockpit now reads recent execution reconciliation runs
  from `/api/execution-reconciliation/runs?limit=5` and shows the latest run
  status, open-item count, first review item, and suggested action as read-only
  automation evidence. The surface adds no ledger-sync, fill-apply, broker
  submit, or broker cancel controls, and does not mutate OMS status,
  production ledger entries, broker orders, automatic-trading defaults, or
  manual confirmation state.
