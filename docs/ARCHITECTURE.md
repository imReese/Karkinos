# Karkinos Architecture

Karkinos is a China-market personal quant research and trading platform. Its
purpose is to improve after-cost trading outcomes through disciplined,
auditable, risk-gated decisions. Automatic broker submission is a future
execution capability, not the source of edge and not the default product mode.
The target execution model is human-supervised and capital-bounded: authority
may grow with reviewed evidence, but it is always explicit, limited, expiring,
observable, and revocable.

The core architectural rule is:

```text
prove the decision first
-> simulate and reconcile the execution path
-> require explicit human authority by default
-> start live validation with a deliberately small risk envelope
-> only then consider evidence-based capital scaling
```

This keeps Karkinos focused on process quality instead of turning a
possibly weak or unverified signal into a faster real-money mistake.

## North-Star Workflow

The platform should answer the daily operating question:

> Given my portfolio, market data, risk limits, account truth, and validated
> strategies, what should I do today -- buy, sell, hold, rebalance, or do
> nothing -- and why?

The end-to-end workflow is:

```text
market data and account facts
-> reproducible research dataset
-> strategy runtime / backtest / replay
-> research evidence bundle
-> strategy promotion gate
-> daily decision
-> daily trading plan
-> pre-trade risk gate
-> paper/shadow run
-> divergence review
-> manual confirmation or valid bounded operator authorization
-> manual ticket or controlled broker bridge
-> broker evidence import
-> execution/account reconciliation
-> journal and post-decision review
```

Each step produces evidence. Later steps consume that evidence; they do not
overwrite it or silently bypass it.

An optional AI-native research loop may operate alongside the canonical flow:

```text
human research question
-> evidence-bound context snapshot
-> deterministic multi-role workflow
-> permission-checked read-only tools
-> cited claims / debate / report / trade-plan draft
-> explicit review
-> versioned memory artifact
```

This loop may explain or propose; it cannot promote its own output into account
truth, risk decisions, execution authority, OMS state, or broker actions.

## Layered Architecture

```text
Web cockpit
  Overview / Decision / Operations / Trading / Account Truth / Market
    |
    v
Application services
  Decision, daily trading plan, operations, automation, capital authority,
  OMS, gateway, execution reconciliation, strategy promotion, account truth
    |
    v
Domain and engine layer
  EventBus, Strategy Runtime, Portfolio, Risk, Paper Broker, Backtest
    |
    v
Local evidence and state
  SQLite facts, market bars, broker evidence, run records, reports
    |
    v
External adapters
  Market data providers, read-only broker connectors, future gateway
```

The service layer owns workflow authority. Strategy code can propose signals
and candidate actions, but it cannot submit broker orders. Broker connectors
can contribute evidence, but they cannot mutate production ledger state without
review and reconciliation.

The AI research runtime is an isolated application-side boundary. Its first
production integrations are explicit human-started context capture, task
review, and accepted-task offline fixture commands. It is not registered as a
strategy runtime, scheduler, OMS service, gateway, background worker, external
model endpoint, or application-startup dependency.

### Explicit AI Context Capture Boundary

`POST /api/ai/research-contexts/capture` is a command, not a financial GET and
not an AI task. It requires an exact acknowledgement, operator label, research
question, account alias, idempotency key, and evidence selection. Research
Evidence and paper/shadow selections additionally require exact persisted ids;
the capture source never substitutes a latest row.

```text
explicit human capture request
-> canonical Portfolio snapshot
-> Account State from that same Portfolio object
-> existing persisted-fact Operations builder / exact research rows
-> verify the valuation snapshot is persisted and replayable
-> re-read valuation snapshot + ledger identity and reject drift
-> immutable ai_canonical_evidence records
-> one ai_context_snapshot
-> ai_context_capture_runs lifecycle audit
```

The capture source reuses existing canonical builders; it does not calculate a
second portfolio, allocation, PnL, account truth, operations summary, research
bundle, or paper/shadow result. It may preserve incomplete evidence for
diagnosis, but `partial`, `blocked`, `missing`, `stale`, `estimated`, and
`unreconciled` records remain non-authoritative. A completed duplicate restores
the original content-addressed context without re-reading sources. The same
idempotency key with changed intent is rejected; an interrupted or failed run
may replay the exact command without duplicating immutable evidence.

This POST may initialize and write only the `ai_*` audit boundary, including
`ai_canonical_evidence`, `ai_context_snapshots`, and
`ai_context_capture_runs`. It must not contact a market-data or broker provider,
refresh facts, invoke a model, start a research workflow, create an OMS intent,
write the production ledger, issue a risk decision, change reconciliation or
kill-switch state, create/widen capital authority, or submit/cancel an order.

### Human Research Task and Review Boundary

Phase 1.3 adds a second explicit command boundary after capture. It records
human intent and review; it is still not model execution:

```text
completed ai_context_capture_run
-> replay exact context and evidence fingerprints
-> POST /api/ai/research-tasks
-> awaiting_human_review | blocked_by_evidence
-> POST /api/ai/research-tasks/{task_id}/reviews
-> context_accepted | context_revision_requested | closed_without_analysis
```

`ai_research_tasks` binds the capture id, context fingerprint, valuation
snapshot, ledger cutoff/fingerprint, and immutable evidence summaries.
`ai_research_task_reviews` records an explicit human decision, while
`ai_research_task_events` forms a per-task SHA-256 hash chain for deterministic
replay. Create and review commands use separate idempotency keys; retries return
the same fact, and changed input under an existing key is rejected.

The service replays the completed capture before task creation and again before
review. Missing/tampered evidence, context drift, or a non-completed capture
fails closed. `partial`, `blocked`, `missing`, `stale`, `estimated`, and
`unreconciled` evidence creates a visibly blocked task and cannot receive
`context_accepted`. Requesting revision or closing without analysis remains
available so humans can record the disposition of incomplete evidence.

The Strategy Lab UI keeps this boundary closed and performs no request until a
human explicitly opens it. Recording a task first calls the existing context
capture command and then binds the returned capture id. An exact saved
backtest result may be selected; no UI substitutes a latest research row. Task
GET routes never initialize schema or write audit rows; schema creation is
limited to explicit POST commands.
There is no polling, scheduler, startup task, provider/model selector, API key,
model invocation, workflow start, or background agent in Phase 1.3. Human
`context_accepted` means only “this frozen context is suitable for a future,
separately authorized analysis”; it has no accounting, risk, capital, OMS,
gateway, submission, or cancellation effect.

### Explicit Accepted-Task Offline Fixture Boundary

Phase 1.4 adds a third command boundary. Context acceptance alone still starts
nothing; the human must explicitly acknowledge an offline deterministic run:

```text
context_accepted human research task
-> replay task hash chain and exact context/evidence identity
-> POST /api/ai/research-tasks/{task_id}/fixture-analyses
-> claim stage reads every bound canonical evidence reference
-> deterministic debate
-> deterministic report
-> context-bound memory draft requiring later human review
-> workflow hash-chain replay + evidence-binding validity
```

The runtime registers only `karkinos.fixture.offline.v1` and its local fixture
model identity for that explicit run. These identities exercise the
provider/model/role contracts; they are not production AI registrations and do
not perform network I/O or read an API key. Stage order is fixed by the
deterministic orchestrator. Every claim/debate/report/memory artifact cites the
task evidence, and the claim stage must successfully read every exact reference
through the permission registry before later stages proceed.

`ai_research_task_analyses` maps one idempotent human command to one existing
workflow. Restarting the service or repeating the exact command reuses the
mapping, workflow, runs, tool calls, and artifacts rather than executing a
duplicate. GET/list/replay routes tolerate an absent schema as an empty/not-
found read and never initialize tables. There is no polling, scheduler, startup
hook, background execution, or implicit retry loop.

Before start, the task status, task event replay, context fingerprint,
valuation snapshot, ledger cutoff/fingerprint, and immutable evidence records
must all match. The same checks run when an analysis is read or replayed. If
evidence drifts after completion, historical artifacts remain in the audit log
but the binding becomes `evidence_drift`, replay is invalid, and memory becomes
`invalidated_by_evidence_drift`; the system never silently carries that memory
forward.

Fixture artifacts are non-authoritative research output. This boundary cannot
write Account Truth, Portfolio, OMS, ledger, risk, reconciliation, kill switch,
capital authorization, broker submission/cancellation, or Decision handoff
state. It does not create a trade-plan draft in this increment.

### Human Fixture-Analysis Review and Recall Eligibility

Phase 1.5 adds a fourth explicit command boundary. A completed fixture memory
is not reviewed merely because the workflow finished; a human must record one
final disposition:

```text
completed fixture analysis
-> rebuild exact analysis target
-> POST /api/ai/research-task-analyses/{analysis_id}/reviews
-> accept_as_reviewed_memory | request_revision | reject
-> append-only review + one-event SHA-256 chain
-> revalidate target on every GET/replay
-> reviewed_memory | invalidated_by_evidence_drift
```

The analysis target fingerprint binds workflow status/failure/partial state,
context identity, evidence-binding status, every stored and recomputed artifact
fingerprint, evidence references, tool-call completion, memory source artifact
ids, and the workflow audit chain. Acceptance requires `completed`, non-
partial, exact binding, valid workflow replay, the complete claim/debate/report/
memory lifecycle, exactly one memory artifact, matching memory sources, and no
incomplete tool call. Invalid output may still receive `request_revision` or
`reject` so the human disposition is not lost.

`ai_research_task_analysis_reviews` stores one final review per analysis, while
`ai_research_task_analysis_review_events` stores its hash-chained event. The
write uses `BEGIN IMMEDIATE`: exact concurrent or restarted duplicates reuse
one row and one event, changed input under an idempotency key is rejected, and
a second final decision is rejected. List/detail/replay GET routes do not
initialize schema.

An accepted record grants only `memory_recall_eligible` inside the isolated AI
research domain. Every read reconstructs the current target. Evidence,
artifact, context, or audit drift preserves the append-only historical review
but derives `invalidated_by_evidence_drift`, makes combined replay invalid, and
removes recall eligibility. Review-event-chain validity remains separately
visible from current target validity.

No retrieval engine consumes reviewed memory in Phase 1.5. The review is not an
account fact, Portfolio input, Decision input, risk decision, trade-plan draft,
capital authorization, OMS transition, broker instruction, or permission. It
does not contact a provider/model or modify any financial state.

### Explicit External-Provider Connectivity Verification

Phase 1.6 adds a deliberately separate connectivity boundary. It does not put
a production provider inside the research orchestrator. A human must send the
exact confirmation to `POST /api/ai/provider-connectivity/checks`; only then may
the reviewed `openai_compatible_https` adapter send one versioned, fixed prompt
that contains no account, portfolio, valuation, ledger, strategy, research, or
broker data. There are no provider tools, retries, workflow stages, artifacts,
or background invocations.

Configuration remains provider/model neutral. Provider id, model name, HTTPS
base URL, adapter kind, timeout, and credential source are resolved separately;
generic environment variables take precedence over the ignored local-config
compatibility entry. The API key exists only in request memory and the
Authorization header. It is never returned or stored. An optional edge-profile
default may supply a public endpoint, but no vendor is canonical.

The request is idempotent before network I/O. Exact retries reuse the existing
check and cannot incur a second provider call; reuse with different immutable
input fails closed. `ai_provider_connectivity_checks` stores only provider,
model, endpoint origin, timestamps, sanitized status/error, token counts, and
request/response fingerprints. It stores neither prompt nor response body.
Provider and model identity reuse the existing registration contracts. The
result always declares `financial_context_sent=false`, no context/snapshot/
ledger identity, no tools/workflow/artifact, and `authority_effect=none`.

This probe proves authentication and protocol compatibility only. It is not a
model-quality evaluation, research result, memory source, Decision handoff,
risk input, capital authorization, OMS action, or broker capability. Connecting
an external model to any broader evidence-bound workflow remains a later
independent review.

### Explicit Saved-Backtest External Report

Phase 1.7 introduces one reviewed, human-started external-model use case; it
does not make an external provider the default research runtime. The only
write entry is `POST /api/ai/external-research/backtest-reports`. Its exact
confirmation states that the selected saved-backtest evidence will be sent to
the configured external model. The exported payload is limited to the
persisted backtest result id/time, strategy and test window, saved performance
metrics, after-cost/cost evidence, research-evidence gate, and recorded
limitations. It excludes account aliases, holdings, valuation/ledger identity,
Account Truth, Operations, paper/shadow, OMS, risk, capital, broker, and
permission facts.

The local sequence is:

```text
explicit human request + selected saved backtest
-> canonical research-evidence capture v2
-> require complete + analysis_ready
-> exact context/evidence binding
-> permission-checked research_evidence.read
-> one OpenAI-compatible JSON request with the configured reasoning mode,
   an exact trusted system contract, bounded output, a cancellable wall-clock
   deadline, and no provider-side tools
-> bounded deterministic schema normalization and validation
-> cited non-authoritative REPORT artifact
-> workflow hash-chain replay
```

The external model never receives the valuation snapshot or ledger cutoff.
Those identities, the context fingerprint, and evidence fingerprint are added
locally to the stored report so replay remains exact without exporting account
identity. `ai_external_backtest_report_requests` obtains an atomic run claim
before the billable turn: concurrent exact duplicates observe the in-flight or
terminal workflow instead of calling the model twice. A failed workflow is
terminal under that idempotency key; a deliberate retry requires a new human
request. There is no automatic retry, scheduler, startup hook, background
model task, memory creation, Decision handoff, trade-plan draft, or authority
effect. Provider timeout/error text is sanitized; malformed raw provider output
is not stored.

The external edge does not disable a model's configured reasoning mode. Its
versioned prompt separates evidence-review requirements from final
serialization, includes an exact JSON example and self-check in the trusted
system message, and gives the final response a bounded output budget suitable
for reasoning-oriented models. DeepSeek-compatible requests explicitly use
thinking/high effort, a 4,096-token completion budget, and a cancellable
180-second end-to-end deadline; other compatible providers retain
deterministic temperature zero. Raw
`reasoning_content` is never persisted; only sanitized presence/length and
finish metadata may enter report provenance. Local normalization accepts a
small reviewed set of wrapper, nesting, and Chinese/common field aliases but
cannot invent missing claims or counterarguments. Missing per-item evidence
summaries remain explicitly `reference_only` and require human review.

### Explicit Reviewed-Memory Retrieval and Current-Evidence Rebinding

Phase 1.8 consumes only the recall eligibility produced by Phase 1.5; it does
not add an autonomous memory engine. A human must name the exact review ids and
one already-persisted current context:

```text
explicit human request + exact review-id allowlist
-> replay each review, source analysis, artifact, and source evidence
-> read one existing current EvidenceBoundContextSnapshot
-> verify every current canonical evidence row and financial identity
-> map each source evidence tool to exactly one current complete record
-> persist retrieval request + one-event hash chain
-> return historical reviewed input + current-evidence bindings
```

The source and current evidence identities may differ. Rebinding means the
result records which current canonical record a future research workflow must
read for each source tool; it does not assert that old prose remains true under
the new data. The retrieval result therefore declares
`memory_is_current_fact=false` and `current_evidence_must_be_read=true`, while
binding the current valuation snapshot, ledger cutoff, and ledger fingerprint.

Current-context validation checks the content-addressed context id, every
evidence-reference fingerprint, exact valuation/ledger identity, `complete`
status, and a unique canonical tool mapping. Source eligibility independently
replays Phase 1.5. Any source or current drift changes the recomputed retrieval
target, invalidates replay, and removes memory content from the response while
preserving the append-only request and audit event.

`ai_reviewed_memory_retrievals` and
`ai_reviewed_memory_retrieval_events` are isolated AI audit tables. POST is the
only initializer; GET/list/replay do not initialize or refresh anything. Exact
restart/concurrent duplicates reuse one retrieval and one event; changed input
under the same idempotency key fails closed.

Phase 1.8 deliberately has no semantic/vector search, embedding, scheduler,
automatic recall, prompt injection, provider/model call, provider-side tool, or
registered orchestrator retrieval tool. It cannot write Account Truth,
Portfolio, Decision, risk, OMS, ledger, reconciliation, kill switch, capital
authorization, broker submission/cancellation, or execution permissions.

### Offline Memory-Informed Analysis Boundary

Phase 1.9 connects a Phase 1.8 retrieval to the deterministic orchestrator only
after another explicit human command. This proves the evidence, prompt-input,
tool, artifact, restart, and replay contracts without claiming that a real
model has produced intelligence:

```text
explicit human command + exact retrieval id
-> revalidate retrieval/review/context/evidence binding
-> claim role reads every current canonical evidence reference via local tools
-> bind reviewed memory as historical non-fact input
-> deterministic claim -> debate -> report
-> persist artifacts, tool calls, workflow audit, and run mapping
-> recompute binding and replay validity on every GET
```

The retrieval itself is deliberately not a registered tool. Its exact target
fingerprint and historical memory payload are bound by the local service, while
the orchestrator tool registry contains only the existing canonical persisted-
evidence readers. The claim stage must complete the exact current evidence read
set before the fixture can emit output. Debate and report receive no tools.

Every artifact cites the current evidence references and carries the retrieval
id/target fingerprint, current context fingerprint, historical-memory labels,
`memory_input_is_current_fact=false`, `current_evidence_must_be_read=true`, and
`authority_effect=none`. The lifecycle contains exactly claim, debate, and
report; it does not create a new memory or trade-plan draft.

`ai_memory_informed_fixture_analyses` maps the request to one workflow and uses
a short database lease to prevent duplicate execution across threads or
restarts. Workflow idempotency also binds the full request fingerprint. Failed
and intentionally partial stages are terminal audit facts, not automatic retry
signals. Detail/list/replay GETs do not initialize schema or resume workflows.

Every read replays the current Phase 1.8 target, canonical records, tool-call
set, artifact fingerprints, stage lifecycle, and workflow hash chain. Later
drift preserves historical artifacts but derives an invalid current binding.
There is no external model, network, API key, semantic retrieval, automatic
recall, provider-side tool, Decision input, financial mutation, permission
change, broker action, or execution/capital authority in Phase 1.9.

### External Memory-Informed Analysis Boundary

Phase 1.10 adds a separately confirmed external edge around the Phase 1.8/1.9
contracts. It does not replace the offline fixture or register a default
provider:

```text
explicit human evidence-export confirmation + exact retrieval id
-> replay retrieval/review/context/evidence eligibility
-> claim stage rereads every current evidence record via local tools
-> send sanitized current evidence + selected historical memory
-> validate and persist normalized cited claim
-> debate stage rereads every current evidence record via local tools
-> send current evidence + memory + normalized claim
-> validate and persist normalized cited debate
-> report stage rereads every current evidence record via local tools
-> send current evidence + memory + normalized claim/debate
-> validate and persist normalized cited report
-> replay tool/model/artifact/audit bindings on every read
```

The deterministic orchestrator owns stage order and the local permission
registry owns tool access. The external model receives no tools and cannot ask
the provider to refresh facts. Every stage must observe the complete exact
current read set; memory remains `historical_reviewed_research_input` with
`is_current_fact=false`. Outbound recursive filtering removes account aliases,
account/broker numbers, client identity, credentials, secrets, and tokens. OMS,
risk, kill-switch, capital, broker, permission, and execution state are outside
the provider input contract.

The versioned prompt leaves the configured model's normal reasoning mode
available while requiring a single JSON object. Prompt v2 places the exact
schema, structural example, allowed citation ids, and final self-check in a
Karkinos-generated system contract instead of relying on instructions buried
inside the evidence payload. A compact evidence catalog maps each exact id to
its local tool, kind, as-of, schema, and available top-level fields; it is
metadata over the same exported persisted record, not a new fact source. The
prompt declares embedded evidence and memory strings untrusted and prohibits
trading or authority output. Its closed-world rule also forbids expanding a
symbol into an unprovided name, importing market conventions/correlations or
unstated thresholds, and proposing provider refresh, broker export, kill-switch
release, submission enablement, position changes, or authority expansion.
Interpretations must be labelled as inference with the missing evidence named;
follow-up checks are limited to local read-only ingestion, reconciliation, and
human review.

Provider-specific reasoning controls stay at the replaceable HTTPS edge. For a
configured DeepSeek adapter, Karkinos explicitly requests thinking mode with
high reasoning effort and omits the ignored temperature parameter; other
OpenAI-compatible providers retain deterministic temperature zero unless their
edge profile says otherwise. Provider-side tools remain absent. Each explicit
stage has a bounded 180-second timeout and 16,384-token output budget so
reasoning does not silently consume the entire final-JSON allowance. There is
still no automatic retry after a claimed call.

Local normalization remains bounded: it accepts reviewed JSON fences, content
parts, common field aliases, Chinese confidence labels, and a single cited
object where an array was requested, but never fabricates a citation or
financial value. Unknown/missing evidence ids, invalid structure, a length-
truncated response, or incomplete evidence fails closed. Raw reasoning and raw
provider responses are not persisted; only normalized artifacts,
fingerprints, status, bounded usage, finish reason, and reasoning-presence/
length metadata enter audit state. Existing prompt-v1 runs remain immutable
history and become visibly invalid under the v2 current-binding check; they are
not silently retried or rewritten, and a new explicit run needs a new
idempotency key.

`ai_external_memory_informed_analyses` binds the request, retrieval target,
current context, provider/model identity, prompt version, and one permanent run
claim. `ai_external_memory_model_calls` holds one insert-once call claim per
workflow stage. These claims deliberately prefer no duplicate external charge
over automatic recovery from an ambiguous interruption: a claimed or terminal
exact retry reads stored state and never calls the provider again. A changed
request under the same idempotency key fails closed. GET/list/replay do not
initialize schema, load credentials, contact the provider, or resume work.

Replay revalidates current retrieval eligibility, every evidence fingerprint,
all three exact tool-read sets, artifact fingerprints and citations, provider
provenance, model-call lifecycle, and the workflow hash chain. Drift preserves
historical audit facts but invalidates the current result. Phase 1.10 creates no
new memory, Decision input, trade-plan draft, Account Fact, financial write,
permission change, broker action, or execution/capital authority.

### External Analysis Human Review and Quality Evidence

Phase 1.11 separates model-output validation from human research acceptance.
Schema-valid external output remains `requires_human_review=true` until a
separate command records one final disposition:

```text
exact Phase 1.10 analysis id + human rubric + explicit confirmation
-> replay retrieval/context/evidence and workflow audit
-> re-fingerprint claim/debate/report, citations, tools, and model calls
-> aggregate provider-reported token and observed latency evidence
-> bind reviewed pricing snapshot or explicit unpriced reason
-> accept as reviewed research | request revision | reject
-> persist one review + one hash-chained event
-> rederive eligibility on every GET/replay
```

The objective target fingerprint covers workflow/context identity, retrieval
target, all artifact stored/actual fingerprints, evidence citations, every
local tool call, provider/model/prompt identity, model-call metadata and usage,
quality evidence, and the AI workflow audit. Acceptance requires a completed,
valid Phase 1.10 replay with exactly claim/debate/report, complete citations,
three completed model calls, and no known human-recorded factual errors or
unsupported claims. Revision and rejection remain recordable when the target
is invalid so failure evidence is not erased.

The human rubric records evidence grounding, contradiction handling,
uncertainty calibration, and decision usefulness on a bounded 1–5 scale. The
system exposes each score and the total but applies no hidden threshold and
does not promote the provider. Objective observations include citation counts,
prompt/completion/total tokens, per-stage/total latency, reasoning-presence
count, and evidence-read completion. They are quality evidence, not financial
facts, and raw reasoning/raw provider responses remain absent.

Pricing is never fetched during review. The request must provide either a
human-reviewed, effective-dated currency and prompt/completion price per
million tokens, or an explicit reason that pricing is unavailable. A priced
estimate uses exact decimal arithmetic over provider-reported token usage and
is labelled `provider_invoice=false`. Missing usage yields `partial_usage` and
no estimate; missing pricing yields `unpriced`. Neither status is silently
replaced by current web pricing or a vendor-specific default.

`ai_external_analysis_reviews` stores the immutable request, exact target,
provider/model/prompt binding, report artifact, review-time quality snapshot,
review-time cost snapshot, and disposition. Current quality is recomputed only
as a separately labelled drift comparison; it cannot rewrite the historical
review basis.
`ai_external_analysis_review_events` stores one hash-chained review fact. The
unique analysis and idempotency constraints make concurrent duplicates single-
fact and each analysis final only once. GET/list/replay do not initialize the
schema, load credentials, call a model, or refresh evidence. Drift in evidence,
artifacts, usage, provider identity, prompt, tool calls, or audit state preserves
history but invalidates current reviewed-research eligibility.

Acceptance intentionally ends at `reviewed_research_eligible=true`.
`memory_recall_eligible`, `provider_promotion_eligible`, Decision handoff,
trade-plan creation, financial writes, broker actions, capital changes, and
execution authority all remain false. A future memory promotion requires a
separate reviewed contract and cannot reinterpret this review as permission.

### Reviewed External Research Memory Promotion

Phase 1.12 implements that separate contract without changing the Phase 1.8
retrieval-v1 request, fingerprints, or replay:

```text
currently eligible Phase 1.11 review + explicit human promotion confirmation
-> replay exact review and Phase 1.10 source analysis
-> select exactly one normalized REPORT artifact
-> bind review/report/context/retrieval/evidence/provider/model/prompt identities
-> copy normalized report + safe provenance into a new historical MEMORY artifact
-> persist immutable promotion + hash-chained event
-> revalidate source and artifact on every GET/replay
-> optional explicit terminal revocation appends one event and hides content
```

The memory artifact is a namespaced promotion-domain record rather than a new
stage appended to the already completed external workflow. This preserves the
original claim/debate/report lifecycle and audit replay. Its content contains
the normalized report fields, human review note/rubric, source fingerprints,
and sanitized provider provenance. Raw reasoning, raw provider responses,
credentials, account identity, and authority state are absent.

`ai_external_reviewed_memory_promotions` stores the immutable human request,
source target, artifact content/fingerprint, evidence ids, and all source
identities. `ai_external_reviewed_memory_revocations` stores at most one
terminal revocation. `ai_external_reviewed_memory_events` forms a two-event
maximum hash chain: promotion, then optional revocation. Source or audit drift
preserves every row but hides artifact content and removes recall eligibility.
Revocation never deletes history and cannot be undone in place; a fresh
analysis and review are required.

Phase 1.12 deliberately does not add the new artifact to retrieval v1 or an
external-model prompt. It enables no semantic search, background recall,
provider call, current-fact promotion, Decision handoff, trade plan, financial
write, broker action, risk override, kill-switch change, capital change, or
execution authority. A later retrieval integration requires its own versioned
contract and migration review.

### Versioned Retrieval of Promoted External Research Memory

Phase 1.13 adds that integration as a new contract instead of widening Phase
1.8 retrieval v1:

```text
exact Phase 1.12 promotion ids + explicit human confirmation
+ existing persisted current context
-> replay every promotion, source review, analysis, artifact, and audit chain
-> reuse the canonical current-context financial-identity validator
-> map every source canonical tool to exactly one current complete record
-> persist immutable retrieval target + one hash-chained start event
-> revalidate promotion/current evidence/audit on every GET/list/replay
-> hide memory content whenever any binding becomes invalid
```

`ai_external_reviewed_memory_retrievals` stores the versioned request and exact
target fingerprint. `ai_external_reviewed_memory_retrieval_events` stores one
append-only start event. The request explicitly selects 1–20 promotion ids;
there is no semantic search, scheduler, background recall, or automatic prompt
injection. Current context validation remains single-sourced by adapting the
existing Phase 1.8 validator without changing its request, fingerprint, table,
or replay contract.

This retrieval is historical non-factual research input plus current-evidence
bindings, not a current fact or model instruction. Phase 1.13 registers no
provider tool and performs no provider/model call. Consumption by an offline
or external workflow requires another separately reviewed, explicit contract.
The boundary cannot write OMS, ledger, risk, reconciliation, kill switch,
capital authorization, broker submit/cancel, Decision, or trade-plan state.

### External Analysis of Promoted Reviewed Memory

Phase 1.14 consumes only the Phase 1.13 versioned retrieval through another
explicit contract; it does not widen Phase 1.8 retrieval v1 or treat retrieval
as permission to export data:

```text
eligible Phase 1.13 retrieval + exact human export confirmation
-> reload the bound context and every current canonical evidence record
-> claim stage rereads all evidence through local permission-checked tools
-> send sanitized evidence + selected promoted memory to the configured edge
-> debate stage repeats all local evidence reads, then receives prior claim
-> report stage repeats all local evidence reads, then receives claim + debate
-> validate exact JSON fields and current evidence citations
-> persist normalized artifacts and redacted call metadata
-> require a separate future human disposition before any memory use
```

The workflow deliberately reuses the Phase 1.10 prompt v2, deterministic
orchestrator, provider/model/role registry, canonical evidence executors, and
closed-world response validator. DeepSeek-compatible configuration explicitly
keeps `thinking` enabled and requests high reasoning effort; other providers
remain interchangeable edge adapters. No provider-side tool is registered.
The model receives neither account alias nor credentials, permission state,
OMS, risk, kill-switch, capital, broker, submit, or cancel capabilities. Raw
reasoning and raw provider envelopes are never persisted.

`ai_external_promoted_memory_analyses` binds the request, Phase 1.13 retrieval
target, context, provider/model/prompt identity, and one permanent run claim.
`ai_external_promoted_memory_model_calls` permits at most one attempt per
claim/debate/report stage and stores only fingerprints, status, normalized
usage, latency-adjacent timestamps, completion metadata, and sanitized error
codes. The older Phase 1.10 analysis tables and Phase 1.8 retrieval-v1 tables
remain unchanged and are not canonical for this new source contract.

POST is the only billable boundary. Exact terminal retries and every
GET/list/replay path are read-only, load no credentials, call no provider,
refresh no facts, and never resume a failed stage. Source revocation or
promotion/current-evidence/audit drift preserves the historical artifacts but
invalidates replay. A completed report is still non-authoritative research: it
creates no new memory, automatic recall, Decision handoff, trade-plan draft,
financial write, broker action, capital change, or execution authority.

### Human Review of Promoted-Memory External Analysis

Phase 1.15 keeps schema success, human acceptance, and memory promotion as
three different authority boundaries:

```text
exact Phase 1.14 analysis + explicit human review confirmation
-> rebuild canonical report/citation/token/latency quality target
-> replay Phase 1.13 retrieval and exact promotion selections
-> bind current context + report + provider/model/prompt + audit identities
-> record accept / request revision / reject plus human rubric
-> freeze reviewer pricing evidence or explicit unpriced reason
-> append one hash-chained review event
-> revalidate every source and target on GET/list/replay
-> create no memory, Decision input, financial write, or authority
```

The implementation reuses the Phase 1.11 `_review_target` and deterministic
cost calculation, so citation completeness, provider-reported usage, latency,
and artifact lifecycle have one canonical definition. A second composed target
adds the Phase 1.13 retrieval request/target/audit identity, exact promotion and
selection fingerprints, and Phase 1.14 source contract. The reviewer must
record evidence grounding, contradiction handling, uncertainty calibration,
decision usefulness, factual-error count, and unsupported-claim count. Known
errors block acceptance; pricing remains reviewer-supplied evidence rather than
a live provider lookup or invoice.

`ai_external_promoted_memory_analysis_reviews` stores the immutable request,
composed target, source/report/provider identities, frozen quality/cost
evidence, and decision. `ai_external_promoted_memory_analysis_review_events`
stores exactly one append-only hash-chained event. They reference, but do not
modify, the Phase 1.14 analysis and Phase 1.13 retrieval contracts. Exact
duplicates are idempotent; a second final disposition fails closed. Read paths
initialize no schema, load no provider credentials, perform no model call, and
recompute the target so revocation or evidence/artifact/usage/audit drift
removes eligibility without deleting the historical decision.

Acceptance is still not memory promotion. It creates no artifact, automatic
recall, semantic search, provider promotion, Decision handoff, trade plan,
account fact, financial mutation, broker action, capital change, or execution
authority.

### Revocable Memory from Reviewed Promoted-Memory Analysis

Phase 1.16 implements the separate promotion required by Phase 1.15:

```text
currently eligible Phase 1.15 accepted review + exact human confirmation
-> replay review and Phase 1.14 report/artifact/audit target
-> replay Phase 1.13 retrieval and exact source-promotion lineage
-> bind context/evidence/provider/model/prompt/quality/cost fingerprints
-> copy only the normalized report and sanitized provenance
-> persist a new historical MEMORY artifact in isolated Phase 1.16 storage
-> append one promotion event
-> optionally append one terminal revocation event
-> revalidate every binding on GET/list/replay
-> provide no automatic retrieval, model call, Decision input, financial write, or authority
```

`ai_external_promoted_analysis_memory_promotions` owns the new immutable
promotion request, target, historical content, evidence references, source
promotion selections, and report/review identities.
`ai_external_promoted_analysis_memory_revocations` stores at most one terminal
revocation, and `ai_external_promoted_analysis_memory_events` records the
promotion/revocation hash chain. These are new canonical Phase 1.16 tables;
Phase 1.12 rows, fingerprints, and schema remain unchanged.

The artifact says `is_current_fact=false`, `automatic_recall_allowed=false`,
and `requires_current_evidence_rebinding=true`. Promotion is restart- and
concurrency-idempotent; a second final promotion fails closed. Revocation is
append-only and deletes nothing. Every read recomputes the Phase 1.15 review,
report, Phase 1.13 retrieval, source-memory lineage, evidence, and audit target.
Any drift hides content and removes recall eligibility. Even a valid artifact
is not automatically retrievable or injectable. Phase 1.17 supplies a
separately versioned explicit retrieval and current-evidence rebinding review.

Promotion/revocation load no provider credentials, invoke no model, and cannot
create a current fact, semantic search result, automatic prompt injection,
provider promotion, Decision handoff, trade plan, OMS/ledger/risk write, broker
submit/cancel, permission, capital change, or execution authority.

### Current-Evidence Retrieval for Promoted-Analysis Memory

Phase 1.17 consumes only the recall eligibility established by Phase 1.16:

```text
exact Phase 1.16 promotion-id allowlist + persisted current context
-> exact human confirmation, identity, purpose, and idempotency key
-> replay every promotion, memory artifact, report/review lineage, and audit chain
-> validate the current context's valuation snapshot and ledger cutoff/fingerprint
-> map every source canonical tool/kind to exactly one current complete record
-> bind source/current reference ids and fingerprints into a composed target
-> persist one isolated retrieval request and one hash-chained start event
-> revalidate source, current evidence, request, target, and event chain on reads
-> expose historical research input only; provide no model call or authority
```

`ai_external_promoted_analysis_memory_retrievals` owns the immutable request,
current-context identity, request fingerprint, and composed retrieval-target
fingerprint. `ai_external_promoted_analysis_memory_retrieval_events` stores the
single start event. These Phase 1.17 tables neither modify nor replace the
Phase 1.8 or Phase 1.13 retrieval tables, schemas, fingerprints, or replay.

The start transaction is restart- and concurrency-idempotent. A reused key
with changed input fails closed. Every GET/list/replay reconstructs the target;
revocation, partial/missing/duplicate current evidence, kind mismatch,
valuation/ledger drift, source artifact drift, or audit drift makes the result
ineligible and hides memory content without deleting history. Read paths do
not initialize schema, load provider credentials, contact a provider, or write
financial state.

This retrieval is not automatic recall, semantic search, prompt injection, or
data-export permission. It creates no model call, provider promotion, Decision
input, trade plan, OMS/ledger/risk mutation, broker submit/cancel, capital
change, or execution authority. Any future consumer must be a new explicit
workflow with its own evidence-export review.

### Evidence-Bound Formula Strategy Research

Phase 1.18 is an isolated research-artifact chain, not a strategy or execution
chain:

```text
saved analysis-ready canonical backtest + exact persisted dataset snapshot
-> human selects immutable universe/window/frequency/cost and confirms export
-> local read tools expose sanitized evidence, Formula DSL catalog, selection
-> one provider-neutral model call proposes 1..3 non-executable hypotheses
-> local schema, citation, frozen-input, formula and fingerprint validation
-> human confirms one valid draft
-> restricted adapter reads the exact persisted bars
-> completed-bar signal is applied only on the next available persisted bar
-> existing canonical after-cost BacktestEngine runs without a database sink
-> existing backtest-result persistence stores the canonical result
-> human separately confirms normalized result export
-> one model call creates a non-authoritative evidence critique
-> human records accept / revise / reject
```

The Formula DSL permits only reviewed JSON AST operators over OHLCV fields,
bounded lag/window parameters, boolean/arithmetic composition, and bounded
equal-weight sizing. Unknown operators, fields, keys, future/invalid periods,
non-finite numbers, arbitrary code, URLs, paths, provider tools, and model
changes to the frozen selection fail closed. Formula identity includes the AST,
universe, dataset snapshot, window, frequency, cost model, anti-lookahead
assumptions, parameter values, and initial cash. The formula is research-only:
it is never inserted into the production strategy registry.

`RestrictedFormulaBacktestAdapter` is deliberately narrower than the public
backtest route. It cannot fetch market data, contact a provider, or persist
engine order/fill events into shared trading tables. It reconstructs the
selected `DataStore` bars, recomputes and verifies the exact dataset-snapshot
identity, and delegates all prices, fills, commissions, slippage, equity,
returns, drawdown, turnover, and other metrics to the existing canonical
backtest implementation. The model cannot supply or replace those metrics.
Negative, partial, blocked, and failed outcomes remain visible audit facts.

The domain storage is additive and isolated:

* `ai_strategy_research_sessions` binds the idempotent request, selected saved
  result, context/evidence identity, provider/model/prompt identity, and stage;
* `ai_strategy_hypothesis_drafts` stores normalized drafts plus local
  validation and formula fingerprints;
* `ai_strategy_formula_backtests` binds the selected draft to the exact
  canonical saved-backtest result and research evidence;
* `ai_strategy_backtest_critiques` stores only normalized critique artifacts
  and redacted provenance;
* `ai_strategy_research_reviews` stores the immutable human disposition;
* `ai_strategy_research_events` provides hash-chained replay.

Provider/model/role registration remains runtime-decoupled. DeepSeek is one
replaceable OpenAI-compatible edge; it is not imported by the domain and has no
provider-side tools. Thinking may remain enabled, but raw reasoning, raw
responses, credentials, account identity, valuation-snapshot ids, ledger-cutoff
ids, and permission facts are not sent or persisted as model content. Only
normalized output, content/request fingerprints, model identity, finish reason,
token usage, latency, and whether reasoning was present are retained. A saved
backtest that uses no account facts marks valuation/ledger binding as explicitly
not applicable; if account-derived facts are ever added, the canonical
valuation snapshot and ledger cutoff become mandatory local bindings and remain
outside the provider payload.

All mutating steps are explicit POST commands with distinct confirmation
phrases and atomic external-cost claims. Terminal duplicate requests replay
without another model call; changed inputs under one idempotency key fail
closed. GET formula/session paths initialize no schema, load no credentials,
contact no provider, refresh no data, and write no state. No step creates a
Decision input, trade plan, paper/shadow promotion, OMS/ledger/risk mutation,
kill-switch change, broker submit/cancel, permission grant, capital change, or
execution authority.

## Financial Data Integrity and Valuation

Financial accuracy takes precedence over freshness and UI convenience across
market data, account facts, valuation, PnL, risk, paper/shadow evidence,
reconciliation, and controlled execution.

### Authority Boundary

External providers and broker connectors produce observations, not account
truth. A collector must persist each observation with its provider, effective
timestamp, received timestamp, status, and ingestion run id before an
authoritative calculation may consume it. Runtime caches are provisional
telemetry only. Query endpoints are pure reads: they do not contact providers,
schedule refreshes, or mutate market-data state.

The authoritative flow is:

```text
provider or broker observation
-> auditable ingestion run
-> persisted observation
-> immutable valuation snapshot
-> canonical calculation
-> Overview / Portfolio / Decision / Operations / Explainability projection
```

### Immutable Valuation Identity

Every authoritative result binds:

* `valuation_snapshot_id`, effective `as_of`, and market `trade_date`;
* valuation-policy version;
* exact selected quote, close, or NAV observation for each instrument;
* exact previous-close/NAV baseline used for daily attribution;
* ledger cutoff and ledger fingerprint;
* quote-set fingerprint and completeness/freshness/estimation status.

Policy `karkinos.persisted_valuation.v2` freezes both the valuation price and
daily baseline in the content address. A persisted same-day `1d` market bar is
treated as confirmed close/NAV evidence with an effective China-market close
time of `15:00 Asia/Shanghai`; the original intraday observation remains in the
snapshot for audit. Partial intraday bars must never be stored under that `1d`
confirmed-evidence contract.

`valuation_as_of` follows the newest selected valuation or ledger fact.
`valuation_trade_date` follows market evidence and is not advanced by a later
non-market ledger event. Request time never changes fact time. Historical
reconstructions do not inherit the current snapshot id and current quotes are
never backfilled into past dates.

Snapshots are published only at committed fact boundaries:

* successful or partially successful quote-ingestion completion;
* ledger-entry insertion;
* broker-settlement confirmation;
* application-startup backfill for facts created before this contract.

Successful publication advances the persisted
`valuation_snapshot_publication` pointer. If committed facts imply a different
content id before publication succeeds, authoritative financial reads return
HTTP `503`. They never expose an id that cannot be resolved through
`/api/portfolio/valuation-snapshots/{snapshot_id}`. A quote batch whose facts
persist but whose snapshot cannot publish is recorded as failed, not successful.

### Canonical Daily Accounting

Daily account change obeys one equation:

```text
ending_equity - starting_equity = event_flow + market_move

market_move = symbol_price_contribution
            + trading_fees_and_taxes
            + other_attributed_components
            + explicit_residual
```

Holdings, asset-class totals, symbol contributors, Overview, intraday/daily
equity, and Explainability are projections of the same canonical daily
performance result. Known fees belong to the traded asset class; `Residual` is
reserved for genuinely unexplained differences. A residual above tolerance is
a data-quality failure, not a rounding bucket.

Current positions split overnight quantity from same-day buy lots. Overnight
quantity uses the persisted previous close; same-day lots use their actual
execution cost including the complete persisted fee breakdown. Same-day sells
remain unavailable until realized and remaining-lot attribution can be
performed deterministically.

### Fail-Closed Rules

Authoritative calculations block or degrade explicitly when:

* an ingestion batch is incomplete or cannot link observations to its run;
* a required quote, close, NAV, ledger entry, fee, or corporate action is
  missing;
* confirmed evidence is required but only stale or estimated evidence exists;
* same-day trading cannot be attributed deterministically;
* account reconciliation has unresolved material differences;
* current committed facts have not produced a replayable snapshot.

Missing daily baselines propagate as unavailable (`null` / `--`), never zero.
Historical reconstruction requests prices only for positions open on that date,
so a closed instrument cannot degrade later valuations.

### Deterministic Verification

Trading-related changes cover the relevant cases below:

* overnight holding with no trade;
* full same-day buy and partial same-day addition;
* same-day sell or buy/sell fail-closed behavior;
* fees and taxes;
* deposits, withdrawals, income, and manual adjustments;
* missing, stale, estimated, and unpublished observations;
* cross-endpoint accounting invariants;
* deterministic replay from a frozen snapshot and ledger cutoff.

## Current Core Flows

### AI-Native Research Runtime and Canonical Evidence Boundary

The Phase 1 runtime lives under `server/ai_runtime`. Only its explicit
human-started context-capture, task/review audit, and fixed connectivity routes
are registered; it has no scheduler, startup worker, automatic model endpoint,
or application-lifecycle execution hook. Its contract separates:

* `ProviderRegistration`: provider identity, adapter kind, capabilities, and
  disabled/enabled registration state without credentials;
* `ModelRegistration`: model identity and purpose bound to one provider;
* `AgentRole`: research purpose, allowed artifact kinds, and explicit tool
  allowlist independent of any model;
* `EvidenceBoundContextSnapshot`: immutable account alias,
  `valuation_snapshot_id`, ledger cutoff/fingerprint, and typed persisted
  evidence references;
* `WorkflowDefinition` / `ResearchWorkflow`: ordered stages, durable status,
  idempotency key, current checkpoint, partial/failure state, and exact context
  fingerprint;
* `AgentRun` and `ToolCall`: provider/model/role identity, request and response
  fingerprints, permission outcome, and failure evidence;
* `Claim`, `Debate`, `Report`, `TradePlanDraft`, `Review`, and
  `MemoryArtifact`: typed, evidence-citing research artifacts with no authority
  effect.

The deterministic orchestrator, not a provider, owns stage order, resume
checkpoints, idempotency, terminal status, permission checks, artifact
validation, and audit events. A model may request a tool; only the local
permission registry can allow it, and only an injected executor can run it.
Unknown tools and authority namespaces fail closed. Persisted-read tool results
must return an evidence id already present in the frozen context and explicitly
assert `persisted_facts_only=true` before they can enter the next provider turn.

The general research-task lifecycle still ships only
`DeterministicFixtureProvider`. It selects immutable local responses by
workflow stage and turn, performs no network I/O, accepts no API key, and is
enabled only by explicit test/runtime registration. The Phase 1.6 connectivity
probe remains outside the orchestrator. Phase 1.7 separately registers a
purpose-limited external-report provider/model/role only after an explicit
request for one selected saved backtest; it cannot run another stage or tool.
Phase 1.10 separately registers content-addressed provider/model identities and
three purpose-limited roles only after the exact reviewed-memory evidence-export
confirmation. That edge may execute only the three-stage read-only lifecycle
above; it is not a general provider binding and is never registered at startup.
No DeepSeek, OpenAI, or other vendor is canonical or registered by default.

The AI runtime audit stores create and write only namespaced tables:

```text
ai_provider_registrations / ai_model_registrations / ai_agent_roles
ai_context_snapshots / ai_workflows / ai_agent_runs
ai_tool_calls / ai_artifacts / ai_workflow_events
ai_provider_connectivity_checks
ai_external_backtest_report_requests
ai_external_memory_informed_analyses
ai_external_memory_model_calls
ai_external_analysis_reviews
ai_external_analysis_review_events
ai_external_reviewed_memory_promotions
ai_external_reviewed_memory_revocations
ai_external_reviewed_memory_events
ai_external_reviewed_memory_retrievals
ai_external_reviewed_memory_retrieval_events
ai_external_promoted_memory_analyses
ai_external_promoted_memory_model_calls
ai_external_promoted_memory_analysis_reviews
ai_external_promoted_memory_analysis_review_events
```

Workflow events form a per-workflow SHA-256 hash chain. Agent runs, tool calls,
and artifacts use content fingerprints and uniqueness constraints so restart,
duplicate requests, partial stages, and replay are deterministic. Evidence
identity drift blocks before provider invocation. The store exposes no method
for production ledger, OMS, risk decision, kill switch, capital authorization,
broker gateway, submission, or cancellation state.

The implemented integration direction remains one-way and read-only:

```text
canonical persisted projection or evidence
-> reviewed read adapter
-> evidence reference in frozen AI context
-> research artifact

AI artifact -X-> canonical financial fact / risk decision / execution authority
```

The first read-boundary increment adds `CanonicalEvidenceRecord`,
`CanonicalEvidenceRepository`, `EvidenceContextBuilder`, and
`CanonicalEvidenceToolExecutors`. An explicit capture caller may freeze an
already-computed canonical payload under one content-addressed reference. The
envelope always includes the exact valuation snapshot id, ledger cutoff,
ledger fingerprint, source schema, as-of time, completeness status, and payload
fingerprint. If the payload contains any of those identities, a contradiction
fails closed instead of being accepted as a second truth.

The repository writes only `ai_canonical_evidence`; it does not expose or
mutate source financial tables. Duplicate content is idempotent, changed
content receives a different reference, and a context can be assembled only
when every record has the same valuation/ledger identity. Read executors exist
for the registered Portfolio, Account State, Operations, Research Evidence,
Account Truth, and paper/shadow tool names. Each executor accepts only an
`evidence_reference_id`, re-reads the immutable row, checks the context
reference and fingerprint, and performs no provider refresh or canonical
calculation.

Statuses such as `partial`, `stale`, `estimated`, and `unreconciled` remain
readable for diagnosis but return `authoritative=false` with an explicit
blocker. They are never silently promoted to complete. Phase 1.2 registers only
the explicit capture route, and Phase 1.3 registers only human task/review audit
routes. Neither route connects a provider, model, scheduler, startup hook, or
background task.

### Research and Strategy Runtime

Karkinos learns from external strategy-platform ergonomics through lifecycle hooks,
strategy context, parameter schemas, and one strategy API that can be reused
across backtest, replay, paper, and shadow modes.

The safe translation is:

```text
strategy hook
-> StrategyRuntimeOutput
-> StrategyRuntimeAuditRecord
-> evidence/risk/account/paper/manual gates
```

The strategy runtime context is read-oriented. It should expose market data,
portfolio facts, parameters, account facts, risk limits, and run metadata. It
must not expose direct broker-order authority.

### Daily Decision and Trading Plan

`build_daily_trading_plan` is the high-risk aggregation point that converts
decision evidence into manual-confirmation order intents. It consumes decision
payloads, account-truth status, market health, portfolio controls, candidate
actions, fees, cash impact, T+1 constraints, limit/suspension/ST checks, and
drawdown/concentration controls.

Its outputs are previews:

* `order_intents` are evidence-linked order candidates.
* `blockers` explain why an action cannot proceed.
* `submission_status` defaults to manual confirmation or blocked states.
* `broker_bridge_status` remains disabled by default.

Changing this flow has a broad blast radius because it feeds Decision,
Operations, and paper/shadow runs. Treat it as a platform contract.

### Operations and Paper/Shadow

Operations Center is the daily runbook. It answers:

```text
what ran
what failed
what is blocked
what is ready for review
what evidence is safe to rely on
what the operator should do next
```

`run_paper_shadow_from_trading_plan` creates or reuses a deterministic
paper/shadow run from the daily trading plan. It records simulated orders and
fills as evidence only. It must not create production ledger entries, mutate
cash or positions, store broker credentials, or submit broker orders.

The paper/shadow run should be the first place where execution assumptions meet
the current plan:

```text
daily trading plan
-> deterministic input fingerprint
-> paper/shadow order request
-> simulated OMS transitions
-> simulated fills / rejects / cancels / expirations
-> divergence status
-> next manual review step
```

### OMS and Gateway Boundary

OMS is the production-facing order lifecycle boundary. Its near-term role is
not "send orders"; its role is to make order authority explicit.

The safe lifecycle is:

```text
awaiting_manual_confirmation
-> manually_confirmed
-> manual_ticket_created
-> broker evidence imported
-> reconciled or exception review
```

Any future broker gateway must remain capability-based:

* manual-ticket gateway: copyable ticket, no broker API submission;
* dry-run gateway: validates payloads and records rejected/accepted previews;
* read-only connector: account/cash/position/order/fill evidence only;
* controlled live gateway: future, disabled by default, gated per account,
  strategy, symbol, order, risk state, account truth, and kill switch.

### Account Truth and Reconciliation

Account truth is the platform's reality check. Broker statements and connector
snapshots are staged as evidence before they influence decisions.

Execution reconciliation compares:

```text
OMS order state
-> broker gateway event
-> imported broker trade/fill evidence
-> local ledger/cash/position expectations
```

When an operator records manual execution evidence and later stages matching
broker trade evidence, reconciliation also compares quantity, price, gross
amount, fee, tax, transfer fee, and net amount. Matches and differences remain
review evidence; neither result changes OMS state or mutates the production
ledger automatically.

No automation path should directly mutate production ledger state just because
broker evidence exists. Matching evidence can recommend review actions; ledger
mutation remains explicit and auditable.

## Authority Boundaries

| Layer | May do | Must not do |
| --- | --- | --- |
| Strategy | Emit signals, candidates, warnings, explanations | Submit broker orders or bypass gates |
| Backtest/research | Produce reproducible evidence and assumptions | Claim deployability without OOS/after-cost/risk review |
| AI research runtime | Read explicitly bound persisted evidence; create cited research artifacts and non-executable drafts | Refresh providers, mutate financial/authority state, issue risk decisions, or call OMS/broker actions |
| Daily plan | Create order-intent previews and blockers | Create broker orders or ledger entries |
| Risk gate | Pass/block with reasons and policy snapshots | Be optional for actionable candidates |
| Paper/shadow | Simulate order/fill outcomes and divergence | Mutate production cash, positions, or ledger |
| Capital authority | Evaluate explicit operator scope, expiry, and remaining limits | Create its own authorization, widen limits, or bypass upstream gates |
| OMS | Track explicit order authority and transitions | Submit while broker submission is disabled |
| Broker gateway | Export tickets or future gated bridge actions | Store passwords or enable live submission by default |
| Account truth | Stage/import/reconcile broker evidence | Silently rewrite production ledger |
| UI | Explain next actions and evidence | Hide data-quality gaps or imply guaranteed returns |

## Automation Maturity

Karkinos is built to become more automated, but automation matures in layers:

| Level | Name | Meaning |
| --- | --- | --- |
| L0 | Research evidence | Backtests, sweeps, OOS, after-cost evidence, limitations |
| L1 | Daily trading plan | Candidate pool, blockers, risk, account truth, costs |
| L2 | Paper/shadow operating loop | Scheduled simulated execution and divergence review |
| L3 | Manual execution assist | OMS, manual tickets, broker evidence import, reconciliation |
| L4 | Controlled broker bridge | Per-order gated broker adapter, disabled by default |
| L5 | Capital-bounded controlled execution | Starts with a small pilot exposure, then supports human-approved evidence-based scaling |
| L6 | Unattended full-account automation | Non-goal; permanent unsupervised authority is not required |

This ladder preserves the money-making goal: the system should automate the
parts that increase discipline and evidence quality first. Broker submission
comes only after the system proves it can decide, simulate, reconcile, and stop.

## Capital Authority Model

Account capital and machine authority are different facts. Cash or positions in
an account never grant automation permission by themselves. Controlled
execution consumes an operator-issued authorization whose effective limit is
the strictest applicable account, strategy, symbol, liquidity, turnover, loss,
drawdown, time, reconciliation, and broker-fact constraint.

The authority modes are:

* `disabled`: evidence review only; no broker submission.
* `manual_each_order`: the operator confirms each evidence-fingerprinted order;
  the machine may submit and monitor only that confirmed order.
* `session_bounded`: the operator grants a short-lived envelope for specific
  accounts, strategies, symbols, sessions, and limits; qualifying orders may be
  submitted only while every upstream gate remains clear.

`manual_each_order` remains the default. `session_bounded` is a future
controlled mode, not unattended automation. It may pause or expire itself, but
it may not enable, renew, resume, or widen itself. Increasing capital requires
a new operator decision tied to reviewed live evidence.

The first real execution trial uses a deliberately small authorization envelope
to contain unknown connector, OMS, broker, and operational failures. This is a
deployment-stage safety limit, not a permanent account-size or product limit.

See [CONTROLLED_EXECUTION_PLAN.md](CONTROLLED_EXECUTION_PLAN.md) for the staged
delivery and promotion criteria.

## Controlled Live Bridge Requirements

A future real broker submission path is acceptable only if all gates below are
true for the specific account, strategy, symbol, and order:

* strategy stage allows controlled bridge pilot;
* latest research evidence is after-cost and OOS acceptable;
* Account Truth gate is fresh and pass or explicitly policy-accepted degraded;
* pre-trade risk passes with a stored policy snapshot;
* paper/shadow divergence is clear or manually accepted;
* kill switch is off;
* gateway capability and health checks pass;
* order is inside account, strategy, symbol, cash, turnover, and loss limits;
* user has explicitly enabled the account and strategy for the bridge;
* per-order confirmation is required until a later capital-bounded policy
  explicitly permits limited automation under a valid operator-issued session;
* any automated session has an immutable policy version, explicit scope,
  effective and expiry time, capital at risk, remaining limits, and revocation
  evidence;
* no session may automatically widen or renew its own authority;
* all transitions, broker responses, fills, rejects, cancels, and reconciliation
  outcomes are written as immutable evidence.

Capital-authorization v2 separates two identities that must never be collapsed:

* the **evidence connector** is read-only, supplies Account Truth/soak/account
  facts, and is blocked if it exposes submit capability;
* the **execution gateway** is a distinct policy-scoped future write boundary
  for the same reviewed account, but its declared id/health/capability is not
  runtime authority.

The policy lists both allowed identity sets, the context names one of each, and
an explicit same-account binding must be verified. Identical ids or overlapping
policy sets fail closed. Per-order and session fingerprints include the split
identities. The declared execution-gateway binding remains
`runtime_verification_status=unverified` and cannot contact a broker or submit
an order.

Stage 2.4 adds the separate verifier required to produce short-lived runtime
readiness evidence. It inspects a registered gateway's verified account
binding, required submit/cancel/query/dry-run/idempotency capabilities, and a
source-fingerprinted health snapshot no more than 60 seconds old. It derives an
idempotent client order id and runs an exact limit-order dry-run; readiness
requires `submitted=false`, no broker order id, a valid payload fingerprint,
and zero reported side effects. Accepted and rejected attempts are append-only.
Resolution re-runs all checks, detects source drift, and expires after five
minutes. This is non-submitting readiness evidence, not runtime authority. The
production registry is empty by default.

Stage 2.5 consumes that evidence through the per-order dossier boundary. The
request fingerprint must also be present as the exact typed
`execution_gateway_verification:<fingerprint>` reference in the recorded
`manual_each_order` capital evaluation. The dossier resolver then allowlists and
matches the current record's gateway id, evidence connector id, account alias,
OMS order id, and canonical order fingerprint, plus its disabled-authority and
disabled-submission assertions. It also independently compares the sanitized
dry-run order contract with the current OMS symbol, side, asset class, quantity,
order type, and limit price. Missing providers, expiry, source drift, or any
scope mismatch blocks review and changes the dossier fingerprint. A clear match
changes only `execution_gateway_runtime_not_verified`; it does not alter OMS,
reserve budget, create runtime authority, or make live submission available.

No strategy should call a broker adapter directly. The only allowed path is
through policy, risk, OMS, gateway, and reconciliation services. The current
strategy tree is covered by a static broker-boundary guard so adapter imports
and direct broker-style calls fail deterministic tests before future connector
work can rely on them.

Stage 1.1 adds a promotion evidence boundary above raw connector soak. It
selects exactly 20 unique healthy trading days only when each snapshot carries
clear zero-open-item execution reconciliation, requires passed startup,
intraday, and end-of-day evidence for every selected day, and requires all five
safe-degradation/replay drills. The dossier also binds the latest stable
connector account alias/hash and a sanitized Account Truth source fingerprint
recomputed from the persisted import, current ledger projection,
reconciliation items, manual-review states, and score. Only
pass/fresh/zero-unresolved Account Truth evidence is eligible. The owner signs
the exact dossier with Ed25519 and explicitly attests that the import belongs
to the same account alias and that full process/broker-terminal recovery was
performed outside the service; the existing `restart_recovery` drill itself
proves only new-service-instance replay. A matching acceptance means Stage 1
evidence is ready for later review. It does not enable a connector, issue
capital/runtime authority, or remove the independent Stage 2 gateway gates.
The Stage 2 dossier resolves this evidence through the application state and
binds the promotion dossier fingerprint, operational source fingerprint,
Account Truth source fingerprint, and verified acceptance id. Provider failure,
connector mismatch, malformed evidence, or source drift fails closed without
exposing provider details. Resolution uses only the capital policy's read-only
`evidence_connector_id`; its distinct `execution_gateway_id` is bound separately
and remains runtime-unverified until the exact current Stage 2.4 record is
resolved through the Stage 2.5 binding.

The Stage 2 per-order confirmation foundation is a separate evidence boundary,
not a gateway method. It canonicalizes immutable order terms and fingerprints a
dossier containing the current OMS state, capital evaluation, required gateway
evidence, connector-soak status and current freshness, prior reconciliation,
and kill-switch state.
An operator may attest only that exact dossier after its review gates pass, but
the record now requires a short-lived Ed25519 approval whose canonical
challenge binds the operator/key, action, artifact type, exact dossier
fingerprint, server nonce, and expiry. Only configured public keys are stored;
disabled or rotated keys invalidate approval resolution. The attestation cannot
mutate OMS or authorize a broker call. Any evidence change produces a new
dossier fingerprint. The prior reconciliation is an explicit append-only batch
manifest: the request and capital evaluation must name the same recorded clear
fingerprint, and current OMS/transition/fill/reconciliation facts are rehashed
on every preview. A current signed Stage 1 promotion can clear only the Stage 1
Account Truth-linkage, owner-acceptance, and promotion sub-blockers. A reviewed
execution gateway may clear only its runtime-verification blocker after the
capital reference, identities, OMS order, fingerprint, and dry-run terms all
match. Runtime authority, live gateway, and broker submission remain hard-
blocked independently of the verified attestation.

The Stage 3 session foundation follows the same separation. It accepts an
explicit order set only as a non-executing projection under a short-lived
`session_bounded` policy. Budget math is conservative: gross order value is not
reduced by buy/sell netting, and capital, cash, turnover, per-order,
position-change, liquidity, and projected rate constraints block independently.
The envelope fingerprint excludes only the continuously changing age counter;
the source time, maximum age, and fresh/stale state remain bound. An attestation
requires the same exact prior-batch evidence binding and an independent signed
operator approval for the exact envelope. It does not reserve budget or create
runtime authority. Atomic budget consumption, automatic pause, authenticated
session issuance, and broker submission remain separate future components and
hard blockers.

Stage 3.3 applies the shared gateway-verification binding to every projected
order independently. The request is an exact order-id-to-fingerprint map with
no missing, extra, invalid, or reused fingerprints; the capital evaluation must
contain exactly that typed verification-reference set. Every envelope rebuild
re-resolves all sources and matches gateway id, read-only connector, account
alias, OMS order id, canonical order fingerprint, dry-run order terms, and the
disabled-authority/submission assertions. One failed order blocks the entire
envelope and restores `execution_gateway_runtime_not_verified`. A fully clear
set removes only that blocker: it neither reserves budget nor issues a runtime
session and cannot reach broker submit/cancel behavior.

Stage 3.4 adds a separate session-start Account Truth record. Its provider
rebuilds the current sanitized Account Truth source from the latest broker
import, reconciliation, current ledger projection, and manual-review decisions.
The fact must be clear/pass/fresh, have zero unresolved mismatches, carry a
valid source fingerprint, and be no more than 120 seconds old. Accepted and
rejected attempts are append-only; resolution re-runs the source and expires
the record after 120 seconds. The session request and capital evaluation bind
the same typed fingerprint, evidence connector, and account alias. Drift or
identity mismatch changes the envelope and invalidates its approval. A clear
binding removes only `session_account_truth_snapshot_not_bound`; it cannot
reserve budget, issue authority, mutate Account Truth/OMS/ledger, or contact a
broker.

Stage 3.5 introduces an immutable budget-reservation record after the exact
signed envelope is re-resolved. Money is represented as conservative fixed
0.0001 CNY units, while SQLite `BEGIN IMMEDIATE` serializes overlapping
capital, cash, China-trading-day turnover, and order-count checks. Exact reruns
reuse one row and one attestation cannot reserve twice. Expired windows stop
overlap capital/cash use, but daily turnover stays reserved for that trading
day until explicit release semantics are implemented. This state transition
does not issue a session, mutate OMS/ledger, or add broker capability.

Stage 3.6 makes symbol concentration explicit at both signed-review and
transaction boundaries. The envelope must contain exactly one positive,
canonical limit per projected symbol; every limit is capped by the recorded
capital evaluation's symbol and effective-capital ceilings. The reservation
stores projected/capacity maps in fixed units and, under the same write lock,
sums overlapping reservations per symbol. A legacy overlapping reservation
without symbol evidence blocks rather than being treated as zero. The initial
contract applies the capital evaluation's conservative symbol ceiling to every
symbol in the signed policy scope; future account facts may tighten individual
symbols but may never widen this signed map implicitly.

Stage 3.7 adds the runtime admission primitive. Its authenticated session
provider must return a current enabled session, immutable session/reservation
fingerprints, verified budget reservation, clear upstream and kill-switch
gates, exact scope/order set, active window, verified authority, and explicit
maximum rate.
The limiter uses server time and `BEGIN IMMEDIATE` to serialize one shared
authorization/account 60-second window, choosing the strictest overlapping
session rate. Admissions and rejections are evidence only. Stage 3.9 wires the
persistent token-authenticated provider, but production publishes no admission
mutation endpoint and the limiter has no broker or OMS capability.

Stage 3.8 adds the companion automatic-pause state without enabling session
issuance. A future authenticated session provider supplies only immutable
session identity, while a gate provider is reduced to an allowlisted snapshot.
Missing/failed or non-clear hard facts produce deterministic reasons and one
immutable pause event. SQLite persists only a `paused` runtime state; there is
deliberately no update-to-active method. Runtime admission reads that state
again after its own `BEGIN IMMEDIATE`, closing the stale-provider race. The
Stage 3.8's production route factory used Stage 3.9 session identity but still
supplied no live gate provider. Stage 3.10 later replaced that temporary closure
with persisted gate orchestration, and Stage 3.11 added signed replacement.
Gates becoming clear still never mutate a paused state back to enabled.

Stage 3.9 introduces the durable runtime-authority boundary. Envelope approval
and budget reservation remain non-authorizing inputs; issuance re-resolves both
and requires a distinct Ed25519 approval plus possession of the matching
signature over a deterministic issuance fingerprint. Verification and history
APIs omit signature bytes, so a public approval id is not a runtime capability.
One reservation can create only one session under `BEGIN
IMMEDIATE`. The raw capability token is returned only on the first successful
response and only a salted SHA-256 hash is persisted. Internal admission must
authenticate that token, then its own write transaction rechecks the persisted
session fingerprint, reservation, enabled status, effective/expiry time, and
pause state. Revocation is a separately signed, allowlisted-reason, one-way
enabled-to-revoked transition under the same database lock, so a stale provider
cannot race it. Public APIs expose issue/revoke review actions and sanitized
state, but no runtime admit, resume, renew, widen, OMS/ledger write, broker
submit, or broker cancel action. At Stage 3.9 the remaining automatic-pause
blocker referred to live gate-provider orchestration; Stage 3.10 closes it.

Stage 3.10 closes that orchestration blocker with append-only,
fingerprint-bound live-gate snapshots. A monitoring-only resolver deliberately
survives upstream source drift so the originally persisted enabled session can
still be paused, but explicitly grants no runtime authority. Snapshot capture
reduces persisted Account Truth, signed-envelope risk/paper-shadow/
reconciliation/gateway facts, materialized quotes, runtime admissions and
rejections, and the kill switch to a typed allowlist; missing facts fail toward
pause. The initial runtime order-count view treats persisted admissions as
budget consumption. Loss and drawdown use the current attestation's remaining
budgets until broker execution and production-ledger sources exist; any absent
replacement source pauses rather than inferring clear. Snapshots expire after
30 seconds, quotes after 120 seconds, and three rejection events inside 60
seconds form a spike. The explicitly started scheduler evaluates enabled
sessions; the only mutation route requires that session's token and can only
evaluate/pause. There is still no automatic resume or broker, OMS,
production-ledger, or capital mutation capability.

Stage 3.18 closes the remaining time-of-check/time-of-use gap between that
snapshot and internal order-rate admission. Admission v2 requires the exact
latest live-gate snapshot id, fingerprint, session fingerprint, and observed
time, independently enforces a 30-second maximum age, and includes those fields
in its deterministic admission identity. The same `BEGIN IMMEDIATE` transaction
that rechecks session enabled/expiry/pause and the shared rate window now
re-reads the latest persisted snapshot. Missing, blocked, stale, future,
identity-drifted, or superseded evidence rejects before an admission row is
written. A newer blocked snapshot therefore wins over an older clear preview.
The snapshot is evidence, not Account Truth itself, and an admitted row is not
broker authority: production still exposes no runtime-admit endpoint and the
path cannot contact a gateway or mutate OMS, fills, the production ledger,
capital limits, or the kill switch.

Stage 3.19 adds a read-only operator projection over persisted runtime sessions,
reservations, rate admissions, live-gate snapshots, controlled submit intents,
pause state, and execution reconciliation. The projection computes authorized
capital, effective capital at risk, capital/cash/turnover headroom, remaining
order slots, allowed symbols, effective/expiry time, latest order/submission,
related reconciliation, gate evidence, pause reasons, and blockers. Missing,
stale, future, expired, revoked, paused, unreconciled, invalid, unavailable, or
truncated sources fail closed. It is telemetry over database facts rather than
runtime authentication and exposes no issue, renew, resume, widen, submit,
cancel, or automatic scale action.

Stage 3.11 implements recovery as a new signed authority, never as a mutable
`paused -> enabled` transition. Normal issuance queries durable paused state and
blocks an unexpired matching authorization/account/strategy scope. A
replacement binds the predecessor fingerprint and pause event, a fresh current
attestation and reservation, and the latest continuous suffix of clear gate
snapshots: at least two observations over 60 seconds, with the newest at most 30
seconds old. Any blocked observation restarts the window, and the write
transaction rejects a newer superseding fact. Authorization, account, strategy,
operator, order/symbol scope, reserved gross/buy/turnover/order count,
per-symbol amount, request rate, and session duration can only remain equal or
shrink. A distinct Ed25519 replacement approval plus signature possession
authorizes one `BEGIN IMMEDIATE` handoff that records replacement and revocation
evidence, revokes the old token, and inserts the new salted-token-hash session.
No raw token is persisted or reissued on retry. This is human-reviewed runtime
authority recovery only; it adds no broker, OMS, production-ledger, capital-
scale, renew, or widen operation.

Stage 3.12 introduces a separate one-shot broker-contact boundary for one exact
`manually_confirmed` order. The boundary re-resolves current per-order evidence,
then binds gateway verification, signed operational release evidence, fresh
health, dry-run output, idempotent client order id, and a distinct final
operator signature into one submit fingerprint. A SQLite `BEGIN IMMEDIATE`
transaction records the intent and moves OMS to `submission_pending` before the
external call, so concurrent duplicates cannot both submit. Explicit broker
accept/reject outcomes are persisted; ambiguity becomes `submission_unknown`.
Recovery waits 30 seconds and can only query by client order id—there is no
resubmit operation. Production dependency injection remains empty by default,
and the boundary cannot cancel, apply fills, mutate the production ledger,
expand capital, accept session-wide authority, or expose a strategy path.

Stage 3.13 places a serialized cross-order interlock in front of that boundary.
The read-only preview reports sanitized unresolved intent ids, while the same
`prepared`/`submitted`/`submission_unknown` check runs again under the
`BEGIN IMMEDIATE` insert transaction. Consequently two different orders cannot
both become externally callable, and an acknowledgement is not confused with
reconciliation. Execution reconciliation maps the persisted intent and OMS
state to explicit unknown, awaiting-evidence, evidence-available, mismatch, or
definitive-rejection facts. Unknown states raise critical Operations alerts and
offer query-only recovery. In this stage only a definitive rejection/not-found
result releases the interlock; accepted broker evidence remains open and cannot
self-clear, create fills, mutate OMS/ledger, or authorize another order.

Stage 3.14 adds the only current accepted-submission exit from that interlock.
An operator selects the latest matching reconciliation fact, Karkinos re-reads
one validated broker import and fresh Account Truth (maximum age 120 seconds),
and a distinct Ed25519 signature binds the exact full-fill evidence. One
`BEGIN IMMEDIATE` transaction records evidence-linked real fills, advances OMS
through `accepted` to `filled`, persists the clearance, and writes a terminal
no-action reconciliation fact. It deliberately does not apply the production
ledger. Partial totals and cross-import aggregation remain blocked. Because the
canonical CSV v2 evidence contract accepts optional `broker_order_id` and
`client_order_id`, controlled clearance requires both values to match the
persisted submit intent exactly. Missing or conflicting identity evidence fails
closed and cannot release the interlock. These identifiers remain imported
facts, never broker-write authority; a real adapter must still supply
broker-order-linked callback/poll partial-fill and cancel evidence before a
pilot.

Stage 3.15 introduces the canonical broker-neutral order-lifecycle **evidence
contract**, while deliberately leaving broker connectivity outside Karkinos.
The input is one UTF-8 JSON `exact_order_lifecycle` snapshot for one exact pair
of broker/client order ids. `provider` identifies provenance; it does not select
or load an adapter. Preview is pure and default; the only write command requires
`--record` and the exact non-authority acknowledgement. No query or
reconciliation path opens the source file, calls a broker, or refreshes facts.
Instead an explicit ingestion transaction persists a hashed account reference,
sanitized provenance, file/evidence fingerprints, account-scope source
sequence, capture time, the normalized order, and exact fill rows. It validates
timezone-aware timestamps, a 120-second default capture window, strict fields,
credential absence, status/filled/cancelled arithmetic, fill aggregation,
average price, and one-to-one order identity. `BEGIN IMMEDIATE` makes exact
retry idempotent and serializes sequence, account, identity, and order-contract
drift checks; a read-only resolver never creates its tables.

Execution reconciliation consumes only those persisted rows. It projects open,
partial-fill, partial-fill-plus-cancel, zero-fill cancel, full-fill-awaiting-
independent-evidence, identity conflict, or blocked evidence while leaving OMS,
fills, the production ledger, and the global interlock unchanged. Lifecycle
full-fill does not replace canonical broker-statement trades or Account Truth.
One canonical lifecycle-clearance predicate is also evaluated inside the Stage
3.14 signed-clearance transaction and the next-order submit transaction under
the same SQLite writer lock. Therefore an observation committed before a
clearance rejects that clearance when it is partial/cancelled/conflicting; an
observation committed after a prior clearance turns reconciliation back to an
open mismatch and makes that old intent unresolved for both preview and the
serialized next-order gate.

Stage 3.16 adds a separate broker-neutral collector-ingestion boundary around
that contract. A collector run is accepted only through an explicit local
command and binds a deployment fingerprint, reviewed release reference,
user-authorization reference, provider/account scope, connection and batch
status, cursor transition, callback counters, and exactly one normalized
lifecycle fact for a complete batch. Preparing a run persists the sanitized
lifecycle observation first; committing the run then advances the cursor in a
serialized transaction. A restart repeats the same prepared observation and
run id, an exact retry is idempotent, a different run with the same evidence is
marked duplicate, and cursor reuse, gaps, regressions, deployment drift,
disconnects, and partial batches fail closed without cursor advance. Callback
and poll are evidence labels only: the boundary never opens a socket, imports
a broker SDK, or polls a provider. Tests use deterministic local fixtures.

Stage 3.17 makes collector operation part of the lifecycle resolver's persisted
evidence projection. The derived
`karkinos.broker_order_lifecycle_collector_binding.v1` result is scoped by
provider, gateway, and account alias; it reports whether collection has ever
been adopted for that scope, whether the selected lifecycle observation came
from a matching recorded run, and whether the latest effective run and cursor
state are consistent. Scopes without collector history remain
`not_configured` and may continue to use the explicit Stage 3.15 offline import.
After the first collector run, however, a newer direct import is `unbound`
rather than an implicit escape hatch. A prepared run is `recovery_pending`; a
disconnect, partial batch, or other blocked run is `blocked`; run/state drift is
`inconsistent`. Different-run duplicates are excluded when choosing the latest
effective operational run, so replay cannot hide a later failure.

The collector binding is recomputed only from persisted SQLite facts. A required
non-healthy binding adds one canonical lifecycle-clearance blocker that is
evaluated by reconciliation, the Stage 3.14 signed-clearance transaction, and
the serialized next-order gate. It can therefore reject or invalidate a
clearance but cannot make incomplete evidence sufficient for clearance. It
does not refresh a provider, infer account truth, mutate OMS/fills/ledger/risk/
kill-switch/capital state, release an interlock, or grant submit/cancel/live
authority.

Stages 3.15-3.17 do not register an edge adapter by default. QMT,
PTrade, local-file watchers, and other third-party integrations may implement
the batch contract only after a separate dependency, credential, capability,
failure-mode, release, and user-authorization review. Their existence does not
mean Karkinos depends on or officially supports them. Collector ingestion is
read-only evidence: it cannot submit/cancel, call strategy code, modify OMS or
fills, write the production ledger, change risk/kill-switch state, issue
capital authority, or release the interlock. The retired QMT v1 JSON schema is
accepted only by the explicit offline migration command; it is not canonical
and is rejected by the normal importer.

Stage 3.19 also replaces implicit connector polling on GET/alert paths with the
canonical `karkinos.broker_lifecycle_evidence_health.v1` persisted projection.
Health is derived from the latest effective generic collector run for each
provider/gateway/account scope, including batch, connection, cursor, validation,
release-review, and user-authorization blockers. A registered edge descriptor
is metadata only and is never called. Missing evidence reports explicit
ingestion required; unreviewed releases, disconnects, partial batches, pending
restart recovery, or cursor conflict remain blocked. The legacy runtime
snapshot endpoint is a labelled compatibility migration to this evidence view
and intentionally returns no current cash, position, order, or fill facts.

The Stage 2.1/3.1 batch manifest accepts only a unique non-paper terminal OMS
order set bound to one explicit reconciliation run. Every selected order must
have exactly one persisted `no_action` item whose OMS status has not drifted.
Filled orders additionally require exact real-fill quantity and provider,
broker-order, Account Truth import, and same-run reconciliation linkage. The
record is append-only and source-sensitive; later order, transition, fill,
item, or run changes invalidate it. A clear record satisfies only the prior-
batch evidence gate. It cannot authorize the next batch, accept a mismatch,
reserve budget, modify OMS/ledger state, or contact a broker.

Stage 4 treats capital scaling as a review decision, not a reward for recent
profit. A versioned current/proposed tier is evaluated against execution quality,
cost, drawdown, capacity, liquidity, reconciliation, divergence, disconnect,
policy-violation, and incident evidence with explicit provenance. Protective
recommendations take precedence over expansion: severe evidence recommends
disable, degraded evidence recommends scale-down, insufficient evidence holds,
and only a fully passing review may request a separate new authorization. Human
review can choose a safer result but cannot turn hold/scale-down/disable evidence
into scale-up. The review log never mutates the active authorization or runtime
limits.

Stage 4.1 separates declared metrics from persisted provenance. The public
scaling-review service resolves broker-soak observations, execution-
reconciliation runs, paper/shadow runs, and risk decisions by typed identifiers,
checks their review-window membership and clear state, and returns only sanitized
source fingerprints. The review-input fingerprint and resolution fingerprint
form a separate evaluation identity, so a changed source cannot reuse an older
human decision. Missing or non-clear facts fail closed. Account Truth,
after-cost, incident-window, and capacity/liquidity references must resolve
through one recorded computed evidence window; caller-declared aggregates alone
cannot support scale-up. Protective hold/scale-down/disable analysis remains
evidence-only and does not mutate Account Truth, OMS, runtime authority, gateway
state, or ledger state.

Stage 4.2 provides that computed window without accepting caller-supplied metric
values. Point-in-time Account Truth snapshots keep only a sanitized score/gate
summary and must be captured within 15 minutes of the broker import. A review
window requires distinct clear snapshots near both boundaries. Account-level
after-cost return uses Modified Dietz over persisted total-equity snapshots and
external cash flows. Incident evidence scans persisted critical alerts, rejected
live-write attempts, and connector disconnect observations. Capacity, liquidity,
and slippage use only non-simulated fills whose metadata links broker/provider/
order facts, Account Truth, execution reconciliation, a capacity model, and
market data. Missing coverage records a blocked fact instead of a default value.
The window and every fact are fingerprinted; the resolver rechecks schema,
window, fingerprints, fact status, metric equality, and fill coverage. A fully
resolved result can only record a request for a separate authorization and still
cannot issue authority or mutate execution state.

Stage 4.3 adds an `operating_sample` fact to the same append-only window. It
derives reviewed trading days from healthy read-only connector observations;
counts non-paper OMS orders and their filled, rejected, partial, cancelled,
expired, and nonterminal outcomes; requires real fills to link broker order,
Account Truth import, and execution-reconciliation facts; requires the latest
reconciliation to cover every sampled order; computes p95 latency to the first
persisted no-action reconciliation; counts paper/shadow divergence; and computes
maximum drawdown on cash-flow-unitized portfolio equity. The resolver requires
this fact and compares its nine review inputs exactly. Missing coverage,
nonterminal state, invalid quantity, or a capped 5,000-row scan fails closed.

Stage 4.4 closes the remaining provenance gap with a separate required
`execution_scope` fact. Its order ids come from the same computed operating
sample, never from caller input. Each order must bind either one persisted
controlled-session rate admission or one recorded exact batch-reconciliation
fact that is still current and clear. Session bindings recheck immutable
admission payload fields, runtime-session identity, and the historical
effective/expiry window; exact batches must be wholly contained in the review
sample and are resolved again so later OMS/fill/reconciliation drift wins.
Unbound orders, multiple competing session/batch bindings, in-window admissions
without an OMS sample order, invalid identities, source drift, or capped scans
block the whole window. Evidence-window, resolution, review, decision, and audit
contracts advance to v2. V1 records remain listable history but are not current
scaling evidence; migration means append-only recomputation, never rewriting an
old record. This layer reads persisted facts only and cannot mutate Account
Truth, OMS, fills, ledger, risk, kill switch, runtime sessions, capital limits,
or broker state.

## Design Implications

* The architecture optimizes for decision and execution quality, not for the
  fastest order submission.
* The default UI should surface "what to review next" before "what to buy".
* Runtime data, broker evidence, reports, logs, and screenshots remain local
  and out of source control.
* Tests should be deterministic and use synthetic fixtures for live-like paths.
* Every trading-related feature should state what it assumes, what it blocks,
  what evidence it records, and what it refuses to automate.
* Capital should scale through reviewed evidence tiers, not through a permanent
  fixed "small account" restriction and never through automatic scale-up.
