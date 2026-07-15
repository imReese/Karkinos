# Karkinos

Karkinos: Investing is a chronic condition. Here is your scalpel.
（Karkinos：投资是一种慢性病。这是你的手术刀。）

Karkinos：面向中国市场的个人量化投研与交易平台。

一个集回测、策略实验、账户事实、风控、信号、对账与复盘于一体的个人金融应用。

Karkinos: A China-market personal quant research and trading platform.

An integrated personal finance app for backtesting, strategy research, account
truth, risk control, signals, reconciliation, and review.

长期目标是建设一个人为可控、资本授权有界且只可依据审阅证据扩缩容的量化交易系统。
策略不得直连券商；默认没有实盘提交权限，账户事实、风控、对账和 kill switch 始终先于
任何执行能力。

AI 原生化遵循同一原则：AI 可以围绕冻结的持久化证据进行多角色分析、工具读取、争论、
报告和研究记忆，但 provider、model 与 agent role 相互解耦，模型输出不是账户事实、
风控结论或交易权限。研究 workflow 仍只使用 deterministic local fixture provider；
canonical evidence 只读边界可保存并重读显式捕获的不可变投影，并提供一个必须由人
明确启动的 model-free context capture POST 入口。该入口只复用持久化 canonical
projection、校验 valuation/ledger identity 并写 AI 审计事实；它不启动 workflow。
在此基础上，Strategy Lab 现可由人显式打开研究任务边界：先冻结 context，再记录
证据绑定任务，并对完整性进行人工接受、要求修订或关闭复核。任务和复核各自幂等，
事件可哈希链回放。只有人工接受完整 context 后，操作者才可再次显式启动一个离线、
确定性的 fixture workflow，生成带引用的 claim、debate、report 和待人工复核 memory；
证据漂移会使其绑定与 memory 失效。人工还可对精确完成的分析选择接受为已复核研究记忆、
要求修订或驳回；接受只赋予 AI 研究域内的回忆资格，且证据或 artifact 漂移会自动撤销该
资格。Phase 1.6 另设一个显式、固定且不含财务数据的 OpenAI-compatible 连通性探针，
只验证已授权 provider/model 的鉴权和响应协议，并保存脱敏审计元数据；它不进入研究
workflow。Phase 1.7 再增加一个受限例外：人必须选择一条已保存回测并明确同意把其
策略/区间、收益回撤、成本和证据缺口发送给已配置外部模型；系统只允许 complete 且
analysis-ready 的 canonical evidence，先经本地只读工具取证，再生成一份绑定精确
evidence/context fingerprint 的非权威 report。账户持仓、valuation/ledger identity、
OMS、风控、资本和券商事实不会外发，也不会生成 memory、Decision 输入或交易计划。
该边界保留已配置模型自身的推理模式，但最终内容使用带精确结构示例和量化证据审阅
清单及最终自检的版本化 JSON contract；DeepSeek-compatible 请求显式保留 thinking/high
effort，使用 4K 输出预算和可取消的 180 秒端到端硬时限。本地只做有界、确定性的
字段归一化，模型 reasoning 原文不落库。Phase 1.8 另增一个人工显式、精确 review-id
白名单的已复核记忆检索入口：它
重放原分析与审计链，把原证据按 canonical tool 映射到当前持久化 context 的完整证据，
并把 memory 标记为历史研究输入而非当前事实。漂移后不再返回 memory 内容。该入口不做
语义搜索、自动 prompt 注入或模型调用；仍没有自动记忆检索、后台 AI 任务或实盘入口，
真实 provider 也不会成为默认依赖。Phase 1.9 再提供一个人工显式的离线消费入口：本地
fixture 必须先通过只读工具逐条重读 retrieval 所绑定的当前 canonical evidence，才生成
带引用的 claim、debate 和 report。历史 memory 始终标为非当前事实；重启、重复、失败、
partial 和证据漂移可确定性回放。该入口不调用 DeepSeek 或其他真实模型，不生成新 memory、
Decision 输入、交易计划或任何财务/执行权限。Phase 1.10 再增加一个单独人工确认的真实模型
边缘入口：每个 claim/debate/report 阶段都先用本地只读工具重读全部当前证据，随后只把脱敏
canonical evidence、明确选择的历史 memory 和前序归一化 artifact 发给已配置的通用
OpenAI-compatible provider。它不会关闭模型自身的推理模式，也不向 provider 提供 tools；
原始 reasoning、响应、密钥、账户身份和权限事实不落库。未知证据引用或畸形输出 fail closed，
终态重放和 GET 不加载凭据、不重试调用。该入口同样不创建 memory、Decision、trade plan、
财务写入、券商动作或任何资本/执行权限，也不让 DeepSeek 或其他厂商成为默认依赖。
prompt v2 把精确 JSON schema、结构示例、证据 ID 目录和输出自检提升到系统 contract；
DeepSeek 边缘显式保留 thinking/high effort，并使用有界 180 秒、16K 输出预算，仍无 provider
tools 或自动重试。旧 prompt-v1 结果只保留为历史，不会被静默改写或重跑。
Phase 1.11 再把“schema 合格”与“人工认可”分开：人必须针对精确 external analysis 记录接受为
已复核研究、要求修订或拒绝，并填写证据落地、反方处理、不确定性和有用性 rubric，以及事实
错误/无证据主张数量。系统同时冻结 citation、token、latency、provider/model/prompt 和 replay
证据；成本只依据人工提供的定价快照与 provider token 确定性估算，缺价格或 usage 会明确标为
unpriced/partial。复核不再调用模型，接受也不创建 memory、不晋级 provider、不进入 Decision
或交易权限。Phase 1.12 再增加独立、显式且可撤销的提升边界：只有当前仍可重放的 Phase 1.11
`accept_as_reviewed_research` 才能复制精确规范化 report，形成新的历史研究 memory artifact。
artifact 绑定 source review/report/context/retrieval/provider/model/prompt/evidence 指纹；后续漂移会
隐藏内容并撤销召回资格。人工撤销只追加审计事件，不删除源分析、复核或 memory 历史。该边界
不调用模型，不改写既有 retrieval v1，不自动召回，也不产生当前事实、Decision、trade plan、
provider 晋级或任何财务/券商/资本/执行权限。
Phase 1.13 以独立版本契约增加对这些 promotion 的人工显式检索：请求必须列出精确 promotion id
和一个既有 current context，系统会重放源链并把每个 canonical tool 重新绑定到唯一的当前
`complete` 证据。撤销或源/当前/审计漂移会隐藏内容；Phase 1.8 v1 的请求指纹、schema、表和
历史 replay 不变。该检索没有语义搜索、自动 prompt 注入或模型调用，也不产生 Decision、
财务写入或任何交易权限；后续模型消费仍需单独的数据外发确认与审查。
Phase 1.14 增加这个独立消费边界：人必须再次确认把所选 promoted memory 与其绑定的当前
canonical evidence 外发，claim/debate/report 每个阶段仍先通过本地只读 tools 重读全部当前
证据，再调用已配置的 provider-neutral OpenAI-compatible 边缘。它保留 DeepSeek 的
thinking/high effort，不开放 provider tools，也不保存原始 reasoning/响应；旧 retrieval-v1 和
Phase 1.10 表均不改写。输出仍需另行人工复核，不会自动形成新 memory、Decision、trade plan、
财务写入、券商动作、资本变化或执行权限。
Phase 1.15 增加这一独立人工复核：复核人必须对精确 Phase 1.14 输出选择接受为已复核研究、
要求修订或拒绝，并记录质量 rubric、事实错误/无证据主张数量与人工确认的定价证据。复核同时
绑定 promotion 来源、当前 retrieval、report/artifact、citation、provider/model/prompt、token、
latency 和审计回放；任一来源或证据漂移都会撤销当前资格但保留历史。接受仍不创建新 memory、
不自动召回、不进入 Decision，也不产生任何财务、券商、资本或执行权限。
Phase 1.16 再增加独立、显式、可撤销的提升：只有当前仍有效的 Phase 1.15 已接受复核才能复制
精确规范化 report，形成绑定 review/retrieval/source promotions/context/evidence/provider/model/
prompt/quality/cost/audit 的新历史 memory。撤销只追加事件，漂移会隐藏内容；Phase 1.12 schema
保持不变。Phase 1.17 再用隔离契约增加人工显式检索：请求必须列出精确 Phase 1.16 promotion id
和既有 current context，每个历史证据工具都必须重绑定到唯一当前 `complete` 证据；撤销或任一
来源、当前证据、target、审计漂移都会隐藏内容。Phase 1.8/1.13 保持不变；检索不是自动召回或
外发许可，不调用模型，也没有 Decision、trade plan、财务、券商、资本或执行权限。
Phase 1.18 增加首个完整但仍由人分段授权的策略研究闭环：从已保存 canonical 回测和精确
持久化 dataset snapshot 出发，外部模型只可提出 1–3 条非可执行假设；本地白名单 Formula DSL
会冻结 universe/window/frequency/cost、拒绝任意代码和未知算子。人选定有效 draft 并再次确认后，
受限 adapter 才把已完成 bar 的信号放到下一 bar，通过既有 canonical `BacktestEngine` 生成并保存
扣费后结果；第三次确认才允许把所选公式与规范化结果交给模型批判，最终仍由人接受、要求修订
或拒绝。DeepSeek 仅是可替换的 OpenAI-compatible provider，thinking 保持启用但原始 reasoning
不落库。全链路不注册生产策略，不创建 Decision/trade plan，也不修改 OMS、账本、风控、
kill switch、券商、资本或执行权限。

[中文文档](docs/README.zh.md) | [English Docs](docs/README.en.md)

Strategic goal, architecture, roadmap, and implementation history live in
[docs/KARKINOS_GOAL.md](docs/KARKINOS_GOAL.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/ROADMAP.md](docs/ROADMAP.md)
([中文路线图](docs/ROADMAP.zh.md)), and
[docs/IMPLEMENTATION_LOG.md](docs/IMPLEMENTATION_LOG.md). The staged plan for
human-supervised broker execution and capital scaling is
[docs/CONTROLLED_EXECUTION_PLAN.md](docs/CONTROLLED_EXECUTION_PLAN.md).

---

**Disclaimer**

Karkinos is a personal quant research and trading platform, not investment
advice. Market data, portfolio valuation, backtest results, and trading
outcomes are not guaranteed to be accurate or complete. Do not use this project
as the sole basis for investment decisions.

Do not commit real account data, brokerage credentials, transaction exports,
personal financial data, runtime databases, logs, or screenshots containing
private information. Use example configuration and fake or sanitized data for
public demos and development.

**Highlights**

- Event-driven architecture with deterministic backtesting
- AI-native research runtime foundation with provider/model/agent-role
  separation, valuation-and-ledger-bound context, restartable workflows,
  deny-by-default read-only tools, typed cited artifacts, and hash-chained audit
  replay. The first canonical-evidence read boundary stores content-addressed
  immutable captures and rejects snapshot/ledger drift; incomplete evidence is
  explicitly non-authoritative. An explicit human-started POST can now capture
  selected canonical Portfolio, Account State, Operations, Research Evidence,
  Account Truth, and paper/shadow facts into one replayable context without
  starting a workflow. Human-created task and review records can now bind that
  completed context, block incomplete evidence, and replay a per-task hash
  chain from an explicitly opened Strategy Lab panel. Context acceptance alone
  starts nothing. A second explicit human command may run the deterministic
  offline fixture through claim, debate, report, and review-required memory
  stages; exact retries reuse the run and evidence drift invalidates the
  output. A final explicit human disposition may accept exact output only as
  reviewed research memory, request revision, or reject it. Recall eligibility
  is revalidated on every read and disappears on evidence or artifact drift;
  no automatic retrieval or Decision handoff exists. A separate explicit
  connectivity POST may send one fixed non-financial prompt through a reviewed
  OpenAI-compatible HTTPS adapter. It stores no key, prompt, or response body,
  starts no workflow, and grants no OMS or broker authority. A separate
  explicit saved-backtest report POST may send only the selected canonical
  backtest evidence after an exact data-export confirmation. It permits one
  local `research_evidence.read` and one schema-validated, cited,
  non-authoritative report; account holdings and execution/authority facts stay
  outside the provider request. The configured model may keep its reasoning
  mode, while a versioned JSON-only prompt supplies an exact structural example,
  an evidence-review rubric, and a final self-check. DeepSeek-compatible calls
  explicitly retain thinking/high effort within a 4K output budget and a
  cancellable 180-second end-to-end deadline. Only sanitized
  reasoning-presence metadata is audited; raw reasoning is never persisted. An
  additional explicit reviewed-memory retrieval POST accepts only exact review
  ids and an existing current context, replays all source bindings, and maps
  each source canonical tool to one current complete evidence record. It does
  not perform semantic search, automatic prompt injection, or any model call;
  recalled content remains non-factual historical research input. A further
  explicit offline fixture boundary consumes only that exact retrieval,
  independently rereads every current canonical evidence record through local
  read-only tools, and emits cited claim/debate/report artifacts. Restart,
  duplicate execution, stage failure, partial output, and later evidence drift
  are replayable; no real model, new memory, Decision input, trade-plan draft,
  financial mutation, or authority is involved. A separately confirmed
  external-memory boundary may now run the same three-stage lifecycle through
  an explicitly configured provider-neutral OpenAI-compatible edge. Every
  stage rereads all current evidence locally; the provider receives sanitized
  evidence, selected historical memory, and prior normalized artifacts but no
  tools, account identity, credentials, or authority state. Model reasoning is
  not disabled, raw reasoning/response bodies are not stored, schema or citation
  failures stop the workflow, and exact terminal reads never reload credentials
  or automatically retry a billable call. Prompt v2 elevates the exact schema,
  structural example, evidence-id catalog, and final self-check into a Karkinos
  system contract. The DeepSeek edge explicitly requests thinking/high effort
  with bounded 180-second/16K output limits while provider tools remain absent.
  Prompt-v1 terminal runs remain immutable history rather than being rewritten
  or retried. The result remains a non-authoritative research artifact with no
  memory, Decision, trade, broker, capital, or execution effect. A further
  human-only review boundary separates JSON/schema
  success from research acceptance. It binds the exact analysis/report,
  citations, provider/model/prompt, tool and audit replay, token usage, latency,
  a four-part human rubric, and known factual/unsupported-claim counts. Optional
  reviewed pricing produces a deterministic token-cost estimate; absent pricing
  or usage remains explicitly unpriced/partial. Review performs no model call,
  and acceptance still creates no memory, provider promotion, Decision input,
  trade plan, financial mutation, or authority. Phase 1.12 adds a separate
  human-confirmed and revocable promotion. Only a currently replay-valid
  accepted review can copy its exact normalized report into a new historical
  memory artifact bound to source review/report/context/retrieval/evidence and
  provider/model/prompt fingerprints. Drift hides its content; revocation
  appends an audit event without deleting history. It does not modify retrieval
  v1, invoke a model, enable automatic recall, create current facts or Decision
  inputs, promote a provider, or grant financial, broker, capital, or execution
  authority. Phase 1.13 adds a separate versioned retrieval for exact promoted
  memory ids plus an existing current context. It replays every source and
  rebinds each canonical tool to one current complete evidence record; source,
  revocation, current-evidence, or audit drift hides content. Phase 1.8 request
  fingerprints, tables, and replay remain unchanged. The new retrieval has no
  semantic search, automatic prompt injection, model call, Decision handoff,
  financial mutation, or authority effect.
  Phase 1.14 adds one separately confirmed consumer of that retrieval. Every
  claim/debate/report stage rereads all current evidence through local
  permission-checked tools before the provider-neutral edge receives sanitized
  evidence, promoted reviewed memory, and prior normalized artifacts. The
  configured model keeps its reasoning mode; provider tools, raw reasoning
  persistence, automatic recall, and automatic retry stay disabled. Isolated
  tables preserve the Phase 1.8/1.10 contracts, and the result still requires
  human review with no memory, Decision, trade, broker, capital, or execution
  effect.
  Phase 1.15 supplies that review as a separate immutable command. It binds the
  exact Phase 1.14 report to its Phase 1.13 promotion selections, current
  retrieval target, artifacts, citations, provider/model/prompt, token usage,
  latency, reviewer rubric, pricing evidence, and audit replay. Factual or
  unsupported claims block acceptance, while later source/evidence/usage/audit
  drift removes eligibility without deleting history. Acceptance creates no
  memory artifact, automatic recall, Decision input, trade plan, financial
  mutation, provider promotion, broker action, capital change, or authority.
  Phase 1.16 adds the required separate, explicit, revocable promotion. Only a
  currently eligible Phase 1.15 review can copy the exact normalized report
  into a new historical memory bound to the review, retrieval, source
  promotions, context, evidence, provider/model/prompt, quality/cost, and audit
  fingerprints. Revocation appends history and drift hides content. The Phase
  1.12 schema remains unchanged. Phase 1.17 adds a separate exact-ID retrieval
  that rebinds every source tool to unique current complete evidence under an
  existing context. It leaves Phase 1.8/1.13 unchanged and adds no automatic
  recall, model consumption, Decision, trade-plan, financial, broker, capital,
  or execution capability.
- Controlled automation architecture: research evidence, daily plan, risk
  gate, paper/shadow, OMS, manual ticket, reconciliation, and future gated
  broker bridge remain separate authority layers
- Capital-bounded execution target: account capital never grants authority by
  itself; future machine authority is explicit, expiring, revocable, and
  limited by the strictest operator/account/strategy/symbol/risk/liquidity gate
- Strategy registry exposes typed parameter schemas, and backtest requests can
  use validated generic `params` while preserving legacy moving-average fields
- Backtest parameter sweeps run bounded typed grids, persist each tested
  configuration, and return deterministic rankings with multiple-testing
  warnings plus a versioned robustness artifact for local-neighbor stability
  and per-parameter sensitivity; the Web Strategy Lab can run the same bounded
  sweep and review the ranked configurations without approving execution
- Backtest strategy comparisons can run multiple strategies or parameter sets
  against one frozen dataset snapshot, reject mismatched snapshots, and return
  saved result ids for audit; the Web Strategy Lab can submit same-strategy
  parameter-set comparisons and review the shared snapshot evidence
- Backtest reports record a dataset snapshot with data-source/cache metadata,
  requested range, symbol universe, row counts, adjustment mode when available,
  and data-quality diagnostics, and the Web report exposes that audit panel for
  saved and freshly run results
- Backtest runs attach a versioned `research_evidence_bundle` with analyzer
  outputs, data-quality gate status, after-cost evidence references,
  China-market assumption gaps, and a manual-review promotion gate that does
  not enable execution
- Backtest results persist a strategy metadata snapshot with strategy identity,
  parameter schema, normalized params, benchmark role, and validation
  requirements so saved reports remain auditable when the registry changes; Web
  reports render the snapshot with readable strategy and parameter labels while
  keeping API keys as secondary audit fields
- Web Backtest reports surface after-cost evidence, single-split or rolling
  out-of-sample status, benchmark comparison, structured cost/slippage
  assumptions, and limitations without turning research output into execution
  approval
- Web Backtest Strategy Lab selects registry strategies, renders typed
  parameter controls with readable labels, exposes strategy metadata and
  validation requirements, and can run a single-symbol research backtest from
  the browser
- Web Backtest now summarizes the single-instrument research loop from dataset
  snapshot through signal preview, risk gate, paper/shadow simulation, and
  attribution boundary in user-readable copy without exposing internal reason
  codes or enabling execution
- Multi-asset: A-shares / ETF / Gold / Bond
- Target-weight signals — strategy outputs 0~1, Portfolio handles share counts
- T+1 freeze/thaw built into Position
- Live monitoring with Telegram / WeChat push notifications
- React + TanStack Query + TanStack Router personal finance app
- Responsive platform layout: primary pages reflow at desktop/narrow widths, while wide tables scroll inside their own panels
- Portfolio quote board summarizes asset classes; instrument-level quote, cost, and OHLC/K-line context lives in holding detail pages and the Market research page.
- Portfolio holdings and detail pages expose per-instrument daily PnL, daily return, quote price, cost basis, and baseline source so account-level changes can be traced back to individual stocks or funds.
- Holding detail pages link directly into the single-instrument Strategy Lab
  flow with the current symbol and asset class prefilled for research review.
- Portfolio cockpit construction recommendations are read-only evidence: they
  become actionable only after account-truth and risk gates pass, and they do
  not submit broker orders or bypass manual confirmation.
- Account Truth import preview documents a canonical broker statement CSV format and provides a read-only parser, staged broker evidence store, and reconciliation report core that validates, normalizes, fingerprints, duplicate-checks, persists local CSV rows, and compares broker evidence against cash, positions, fees, taxes, and cost basis without mutating the production ledger.
- Account Truth review APIs expose staged import runs and computed reconciliation
  reports for local review, including row counts, validation status, duplicate
  counts, source metadata, report status, unresolved counts, per-item
  differences, suggested review actions, and broker evidence references.
- Web Account Truth Review Center at `/account-truth` surfaces the latest
  Account Truth Score, import runs, status-filtered reconciliation reports,
  per-item broker/Karkinos differences, evidence references, and manual review
  actions without mutating the production ledger. Cost-basis reconciliation
  items include broker and Karkinos method context, per-share comparison units,
  and precision limitations so broker display rounding and local projections
  can be reviewed explicitly.
- Decision and Strategy Lab promotion review surfaces show Account Truth gate
  status, score, unresolved-difference context, and evidence availability so
  account-truth issues are visible before manual review or research promotion.
- Overview Today’s to-dos: review today’s conclusion, execution state, account
  truth, risk blockers, strategy candidate pool, manual-confirmation queue,
  stock/fund/total daily PnL, top position contributors, market pulse,
  valuation confidence, equity curve, and return calendar summaries before
  drilling into Portfolio, Market, Trading, Decision, or Backtest. Candidate
  counts are shown as research supply, not as the number of trades to execute.
- Market pulse uses a small default China-market index universe as background
  context. Manual quote refresh and the Web scheduler can refresh those index
  quotes alongside account holdings, and missing index move fields are shown as
  data gaps instead of empty values; index quotes do not become user holdings,
  strategy tradables, broker orders, or execution approval.
- Return calendar platform view: inspect audited attribution by day, week, month, or year with calendar/curve/table views and amount/return-rate toggles. The calendar starts weeks on Sunday, uses market PnL for cells, reads historical daily close from the local `market_bars` OHLC cache before falling back to daily-close snapshots, breaks daily market moves into stock/fund/other buckets, keeps deposits, withdrawals, dividends, and manual adjustments as external-flow context, skips non-trading, stale, or intraday terminal quote moves, treats estimated, cached, stale, or confirmed-NAV-missing periods as valuation gaps instead of confirmed returns, and includes axes in the curve view.
- Read-only decision APIs with portfolio, market-health, and after-cost/OOS evidence review, without automatic trading
- Docker one-click deploy

**Architecture**

```
DataHandler → EventBus → Strategy → Portfolio → OrderIntent → Risk Gate → Order/Gateway
                        ↑                                                     |
                        └──────────────── FillEvent ──────────────────────────┘
```

The full architecture is documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Karkinos is designed to improve
after-cost trading outcomes through evidence, risk control, simulation,
reconciliation, and review. Broker submission is a future controlled-bridge
capability, disabled by default, not the default source of trading edge.

**Quick Start**

```bash
git clone <repo-url> && cd Karkinos
cp .env.example .env                   # optional: set tokens / runtime paths
uv sync                                # install dependencies
uv run python -m tools.run_backtest    # run local backtest tool
uv sync --extra server                 # install server extras
cd web && npm install && cd ..
uv run python scripts/configure_data_source.py  # optional: choose AKShare or TuShare safely
./scripts/start_server.sh dev --host 127.0.0.1 --port 8000
./scripts/stop_server.sh
```

`http://localhost:8000` is the product/customer entry. It serves the built React app from `web/dist`, so direct links such as `/portfolio`, `/activity`, `/risk`, `/decision`, `/market`, and `/settings` can be refreshed without returning home.

The data-source setup command writes ignored local `config.json` for you. It hides TuShare token input, never accepts tokens as CLI arguments, and is optional when you are happy with the default AKShare provider. Settings saved from the Web app persist local runtime preferences such as `data_source`, `live_poll_interval`, and account fee assumptions back into the same ignored config file. Account commission settings are stored under `broker_fee_schedule`; legacy top-level commission fields are read only as a migration path. `broker_fee_schedule` stores fee rule parameters, optional Shanghai/Shenzhen transfer-fee rates, and known limitations only, not account identifiers or broker credentials. See [docs/config-reference.zh.md](docs/config-reference.zh.md) for field-level configuration notes.
Manual trade ledger entries that omit an explicit fee use the configured account
fee rule and structured broker fee schedule to record commission, stamp tax,
exchange-specific transfer fee when configured, other fees, total fee, and net
cash impact. Bond and convertible-bond manual trades use the exchange-bond fee
model without stock stamp tax or transfer fees. Entries with an explicit fee
keep the `manual_fee_input` audit marker.

Use this storage boundary:

- `config.json`: local runtime preferences and deploy-specific knobs, including provider selection, poll interval, notification settings, CORS origins, structured broker fee schedule, and read-only broker connector client paths/account aliases. Broker passwords, tokens, secrets, account identifiers, screenshots, and private exports do not belong in broker connector or fee-schedule config.
- SQLite under `data/store/`: mutable financial facts and cache state, including watchlists, instrument metadata, ledger entries, quotes, bars, portfolio snapshots, trading controls, and saved backtest indexes.
- `reports/`: human-readable generated artifacts such as backtest JSON reports and data reconciliation outputs. Reports are runtime evidence, not source code.

**Market Data Reliability Workflow**

Karkinos labels market data with the shared statuses `confirmed`, `live`,
`cache`, `estimated`, `missing`, `stale`, and `confirmed_nav_missing`.
Overview, return calendar, Backtest data-audit panels, and strategy replay
evidence use those labels to distinguish confirmed values from local cache,
estimate-only values, missing quotes, stale quotes, and delayed fund NAVs.

Manual refresh and scheduled refresh flows can update intraday quotes, close
prices, and fund NAV confirmation without changing trading behavior. Frozen
market-data datasets can be replayed for research review, paper/shadow
comparison, and audit evidence. Estimated, cached, stale, missing, or
confirmed-NAV-missing values are data-quality evidence only; they are not
investment advice, profitability claims, or execution approval.

Initial screens do not seed portfolio assets, trades, or fund names. Effective
portfolio data comes from the local database or explicit private runtime
configuration; for example, Activity batch fund candidates are derived from
held fund positions instead of built-in defaults.

**Automation Maturity**

Karkinos is moving toward a professional automated-quant workflow whose goal is
better after-cost trading outcomes, not faster unchecked order submission. The
default product boundary remains daily plan generation plus manual
confirmation. v1.6 completed the persisted paper/shadow runbook, deterministic
reruns, divergence review, and Operations surfaces. v1.7 completed the
non-submitting controlled-bridge foundation: manual tickets, local read-only
connector evidence, capability/health contracts, manual execution evidence,
and execution reconciliation. This completion does not provide broker submit,
executable broker cancel, automatic ledger mutation, or auto-pilot authority.
v1.8 planning is active, but its real-money submission and automation authority
remain unimplemented and disabled. Unattended full-account real-money
automation remains outside the product target.

v1.8 planning is now organized as Capital-Bounded Controlled Execution. It
starts with a non-submitting authorization contract and a real read-only broker
soak, then advances to per-order human-confirmed submission, short-lived
session-bounded execution, and human-reviewed capital scaling. The first live
tier deliberately uses a small risk envelope to contain unknown failures; this
is not a permanent account-size or product limit. Manual confirmation remains
the default, no session may widen or renew itself, and strategy code never
receives broker authority. See the
[controlled execution plan](docs/CONTROLLED_EXECUTION_PLAN.md).

The first v1.8 Stage 0 implementation is available as non-submitting evidence
only. `/api/automation/capital-authority/status` always reports runtime
authority and broker submission disabled;
`/api/automation/capital-authority/preview` performs a side-effect-free policy
evaluation; and `/api/automation/capital-authority/evaluations` records or
lists append-only evaluation evidence. An `allowed=true` evaluation is not an
execution authorization. These endpoints cannot enable, resume, submit,
cancel, mutate OMS, write the production ledger, or expand capital authority.
The v2 evaluation contract separates `evidence_connector_ids` from
`execution_gateway_ids`: the evidence connector must remain read-only, the
execution gateway is a distinct scoped identity, and a verified same-account
binding is required. Identical or overlapping roles fail closed. Declared
gateway health/capability remains runtime-unverified evidence and cannot
authorize or contact a broker.

Stage 1 now has a broker-neutral read-only soak foundation. The
`/api/automation/broker-soak/capture`, `/status`, and `/observations` endpoints
can consume an explicitly configured generic local read-only export, persist sanitized
snapshot evidence, track freshness and provider-calendar trading-day coverage,
and emit Operations alerts for degraded or blocked observations. Raw account
ids are not returned or stored in snapshot facts, any submit capability is
blocked, and 20 healthy trading days complete only the operational soak. Broker
promotion is never inferred from day count alone; the legacy status remains
blocked until separately reviewed evidence is resolved.
`/api/automation/broker-soak/runs` adds deterministic startup, intraday, and
end-of-day evidence with a mandatory clear reconciliation gate at end of day;
`/drills` records disconnect, schema-drift, stale, duplicate-evidence, and
service-instance restart-recovery checks. See
[`docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md`](docs/BROKER_CONNECTOR_SOAK_RUNBOOK.md).

Stage 1.1 adds a separate signed promotion dossier under
`/api/automation/broker-soak/promotion`. It requires 20 unique healthy days
with clear zero-open-item reconciliation, passed startup/intraday/end-of-day
evidence for every selected day, all five recovery drills, and a current
pass/fresh/zero-unresolved Account Truth source fingerprint. Owner acceptance
uses a short-lived Ed25519 approval for the exact dossier and explicitly
attests the same account alias plus full process/broker-terminal recovery,
which the service cannot verify automatically. Source drift invalidates the
acceptance. `promotion_ready` here means Stage 1 evidence readiness only; it
does not issue capital/runtime authority. Stage 2 now binds this exact current
promotion dossier and acceptance into each per-order dossier, but that linkage
does not enable the broker bridge.

The Stage 2 foundation is also non-submitting. The
`/api/automation/controlled-bridge` status, dossier preview, confirmation, and
history endpoints bind one OMS order to the current capital evaluation,
Account Truth/research/risk/paper-shadow gates, connector soak, prior
reconciliation, and kill-switch state. Exact-fingerprint attestations remain
short-lived Ed25519-verified identity evidence bound to the exact dossier and a
configured operator public key. The dossier also binds the current Stage 1
promotion, operational, Account Truth, and owner-acceptance fingerprints for
the capital-policy evidence connector, while the distinct execution gateway is
bound separately. It remains runtime-unverified unless the request, recorded
capital evaluation, current gateway verification, OMS order, connector,
account alias, and canonical order fingerprint all match exactly; missing
evidence, role overlap, expiry, or source drift fails closed. Karkinos stores no
operator private key, and a verified attestation still cannot change OMS, grant
authority, submit or cancel an order, resume automation, or scale capital.

Stage 2.4 adds `/api/automation/execution-gateway-verification` status, preview,
record, resolve, and history endpoints. A registered runtime gateway must expose
verified evidence-connector/account binding, fresh source-fingerprinted health,
submit/cancel/query/dry-run/idempotency capabilities, and an exact dry-run that
returns no broker order id, `submitted=false`, and zero side effects. Recorded
evidence expires after five minutes and is rechecked for source drift. No
execution gateway is registered by default, and even clear verification cannot
issue authority or submit an order.

Stage 2.5 binds that exact short-lived verification into each per-order
dossier. The capital evaluation must already contain the typed
`execution_gateway_verification:<fingerprint>` reference, and every preview or
confirmation re-resolves the current source before accepting the dossier.
Gateway, read-only connector, account, OMS order, and order fingerprint drift
re-block review and invalidates the prior operator approval. A clear binding
removes only the runtime-verification blocker; runtime authority, live gateway,
and broker submission remain disabled.

The Stage 3 foundation remains proposal-only. The
`/api/automation/controlled-sessions` status, envelope preview, attestation, and
history endpoints project an explicit OMS order set inside a timezone-aware
window of at most 30 minutes. Capital, cash, conservative gross exposure,
turnover, per-order, position-change, liquidity, and rate budgets are checked,
and the v2 evidence-connector/execution-gateway split is fingerprinted. Stage 3.3
additionally requires one unique, current gateway verification per OMS order and
the exact same typed reference set in the recorded capital evaluation; one
missing, reused, expired, drifted, or mismatched order proof blocks the whole
envelope. No budget is reserved and no runtime session is issued. There are no
enable, resume, runtime-revoke, submit, cancel, or automatic scale-up operations.

Stage 3.4 adds `/api/automation/session-start-account-truth` status, preview,
record, resolve, and history evidence. The source is rebuilt from the latest
Account Truth import, reconciliation, ledger projection, and manual reviews; it
must be pass/fresh/clear with zero unresolved mismatches and no more than 120
seconds old. The session request and capital evaluation bind the same typed
fingerprint, connector, and account alias. Source drift or expiry re-blocks the
envelope, while a clear record still cannot reserve budget or issue a session.

Stage 3.5 adds
`/api/automation/controlled-sessions/budget-reservations` status, preview,
record, resolve, and history evidence. A reservation is allowed only for a
still-current signed envelope; SQLite `BEGIN IMMEDIATE` serializes overlapping
capital, cash, China-trading-day turnover, and order-count checks. The record
is a bounded budget hold, not a runtime session or broker permission: OMS,
ledger, submit/cancel, resume/renew, and capital scaling remain unavailable.

Stage 3.6 binds an explicit per-symbol runtime-limit map into the same signed
envelope and atomic reservation. Each limit must cover exactly the projected
symbol set, remain below the recorded capital evaluation's symbol ceiling, and
cover its conservative gross projection. Concurrent overlapping reservations
are summed per symbol; same-symbol excess fails while disjoint symbols still
share the stricter account budget. This does not issue a session or enable a
broker action.

Stage 3.7 adds an internal atomic runtime rate-admission ledger with a
server-time 60-second sliding window, exact session/reservation/order/request
binding, idempotent retries, shared account-rate enforcement, and concurrent
last-slot serialization. Stage 3.9 now supplies its authenticated persistent
session provider, while the API still exposes only read-only status/history:
there is no public runtime-admit, OMS mutation, or broker action.

Stage 3.18 now requires every such internal admission to bind the exact latest
persisted clear live-gate snapshot, including its id, fingerprint, session
identity, and observed time, with a 30-second maximum age. The SQLite writer
transaction re-reads that snapshot, so a newer blocked or changed fact wins
over an earlier clear preview. Missing, stale, future, blocked, or identity-
drifted evidence fails closed. Production still exposes status/history only;
this does not contact a broker, mutate OMS/fills/ledger/capital/kill-switch
state, or grant submit/cancel authority.

Stage 3.19 adds a persisted-fact operator view and explicit broker-lifecycle
read boundary. Automation Cockpit shows bounded-session authorized capital,
effective capital at risk, cash/capital/turnover headroom, remaining order
slots, expiry, last order/submission, reconciliation, live-gate, pause, and
blocker evidence without contacting a provider. Broker health and alerts read
only recorded generic collector runs; missing or blocked evidence requires an
explicit ingestion command. The former runtime snapshot entry is migration-
only and returns no live account facts. These views cannot issue, renew, resume,
widen, submit, cancel, mutate OMS/ledger/risk/kill-switch state, or scale
capital automatically.

Stage 3.8 adds an internal durable automatic-pause controller. It evaluates an
allowlisted snapshot of Account Truth, risk, reconciliation, paper/shadow,
gateway, market-data, budget, rate, kill-switch, loss/drawdown, rejection,
account-change, and consecutive-error facts. The first failure persists a
one-way `paused` state, and runtime rate admission rechecks that state inside
its write transaction. Stage 3.9 supplied authenticated session identity while
that slice still had no live gate provider. Stage 3.10 now supplies persisted
gate orchestration, and Stage 3.11 supplies signed replacement rather than
automatic resume. Stage 3.12 adds the first one-shot OMS submit-intent
transition and an injectable broker-contact boundary, but production still
registers no write gateway or signed release-evidence provider by default.

Stage 3.9 adds separately signed runtime-session issuance and one-way
revocation. A current envelope attestation and atomic reservation are
re-resolved, then the owner must sign the exact issuance fingerprint with the
new `issue_controlled_session` action and submit the matching signature as
possession proof; public approval history omits signature bytes. The high-
entropy session token is shown only once and only its salted hash is stored.
Expiry, source drift, pause, or a
separately signed revocation blocks authentication; rate admission atomically
rechecks persistent state against stale providers. This is bounded internal
runtime authority, not broker authority: no public admit/resume/renew/widen,
OMS/ledger mutation, or broker submit/cancel path exists.

Stage 3.10 wires persisted live-gate snapshots into the one-way pause
controller. Account Truth, risk, paper/shadow, reconciliation, gateway,
market-data freshness, runtime budget/rate, kill switch, loss/drawdown,
rejection, account-change, and consecutive-error facts are captured before
each evaluation; missing or invalid facts pause rather than pass. The scheduler
runs this orchestration only when explicitly started, and a token holder may
request only a self-check that can preserve or reduce authority. Snapshots use
a 30-second freshness window, market data uses 120 seconds, and three rate
rejections inside 60 seconds trip the rejection-spike gate. This still creates
no broker submit/cancel, OMS/ledger write, resume/renew/widen, or automatic
capital-change path.

Stage 3.11 adds a signed paused-session replacement protocol without adding an
in-place resume. Ordinary issuance cannot bypass an unexpired paused session in
the same authorization/account/strategy scope. Replacement requires a fresh
attestation and reservation, two continuously clear post-pause snapshots over
at least 60 seconds, a newest snapshot no older than 30 seconds, and a distinct
Ed25519 `replace_paused_controlled_session` approval with signature possession.
One SQLite transaction revokes the predecessor and issues a same-or-narrower
session with a new one-time token; exact retries never reissue it. There is
still no renew, widen, public runtime admit, OMS/ledger mutation, automatic
capital increase, or broker submit/cancel path.

Stage 3.12 adds a deliberately narrow per-order broker submission foundation.
It re-resolves the current manually confirmed dossier and exact prior-batch
reconciliation, requires a separate final Ed25519 signature, current signed
broker/regulatory release evidence, gateway capability/health/dry-run checks,
and a clear kill switch. The submit intent and `submission_pending` OMS state
are committed before one external call; accepted, rejected, and unknown results
are distinct. Unknown results are never resubmitted and may only be recovered
by querying the same idempotent client order id after 30 seconds. Production
still has no configured write adapter or release provider, no automatic or
strategy-direct submission, no broker cancel, and no fill/ledger mutation.

Stage 3.13 adds a fail-closed cross-order submission interlock. Any different
order is blocked while a controlled intent is prepared, accepted but not yet
reconciled, or unknown; the check runs both in preview and inside the SQLite
write transaction, so different-order concurrency cannot bypass it. Execution
reconciliation now classifies those states, unknown outcomes produce a critical
alert, and Operations exposes the query-only recovery task. A definitive
rejection releases the interlock. Accepted broker evidence remains an open
human review item and cannot infer a fill, update the ledger, or clear the next
order; that signed reconciliation clearance is a later stage.

Stage 3.14 implements that narrow signed clearance for exact full fills. The
latest controlled-submission reconciliation item, all matching trade rows from
one validated broker import, and fresh clear Account Truth must agree on the
full OMS quantity and source file. A separate operator signature then permits
one atomic transaction to record linked real fills, advance OMS to `filled`,
persist the clearance, and release the next-order interlock. Partial totals,
cross-import aggregation, automatic ledger mutation, automatic/strategy-direct
submission, and production adapter registration remain disabled. The canonical
CSV v2 contract may carry optional `broker_order_id` and `client_order_id`
evidence. Controlled clearance requires both identities to match the persisted
submit intent exactly; missing, conflicting, cross-import, or partial evidence
fails closed. Those fields remain evidence, not write authority, and a broker-
specific callback/poll adapter is still required before an explicitly approved
pilot.

Stage 3.15 adds a broker-neutral **order-lifecycle evidence contract**, not a live
broker adapter. `scripts/import_broker_order_lifecycle.py` previews one normalized
`exact_order_lifecycle` JSON export by default; persistence requires explicit
`--record` plus the acknowledgement
`record_broker_order_lifecycle_evidence_without_execution_authority`. The command
never contacts a broker, and the database stores only sanitized account hashes,
source/file/evidence fingerprints, monotonic source sequence, exact broker and
client order ids, cumulative fill/cancel quantities, and linked fills. SQLite
serialization rejects sequence regression, same-sequence conflicts, account or
order-identity drift, and post-preview mutation. Execution reconciliation now
surfaces persisted open, partial-fill, partial-fill-cancel, cancel, filled, or
blocked lifecycle facts. Partial/cancel facts cannot mutate OMS or the ledger
and cannot clear the interlock; lifecycle full-fill evidence still needs the
independent broker statement, fresh Account Truth, and Stage 3.14 signature.
The same canonical check runs inside signed clearance and the next-order submit
transaction, so a newly persisted contradictory fact rejects clearance or
re-blocks an older clearance.

Stage 3.16 adds an explicitly started, local-only collector-ingestion boundary.
It binds deployment/release/user-authorization evidence, provider/account scope,
connection and batch status, cursor transitions, callback telemetry, and the
canonical lifecycle fact. Deterministic fixtures cover restart replay,
idempotency, duplicates, cursor conflicts/gaps, out-of-order input, disconnect,
and partial batches. Callback/poll are metadata only; no broker SDK, provider
connection, scheduler, or default registration is added. Collector evidence
cannot modify OMS, fills, ledger, risk, kill switch, capital authority, or the
interlock. QMT, PTrade, local-file, and other edge adapters require a separate
review and explicit user authorization; Karkinos does not claim official
support for them.

Stage 3.17 binds persisted collector run/state evidence back into the canonical
lifecycle resolver. A scope with no collector history remains explicitly
optional. Once collection has been adopted for a provider/gateway/account
scope, the selected observation must be tied to a matching recorded run and
the latest effective run must be cursor-consistent. Pending restart recovery,
blocked disconnect/partial batches, unbound direct imports, or inconsistent
state re-block signed clearance and the serialized next-order gate; duplicate
replay cannot hide a later failure. This read-only binding only removes
eligibility and still cannot contact a provider, mutate OMS/fills/ledger/risk/
kill-switch/capital state, or grant submit/cancel/live permission.

Operator contract and normalized JSON example:
[docs/broker-order-lifecycle-ingestion.zh.md](docs/broker-order-lifecycle-ingestion.zh.md).
The retired QMT v1 schema has only an explicit offline compatibility migration:
[docs/qmt-order-lifecycle-import.zh.md](docs/qmt-order-lifecycle-import.zh.md).

Stage 2.1/3.1 now removes the ambiguous "latest reconciliation" shortcut. The
batch-evidence API binds an exact non-paper terminal OMS order set to one
persisted reconciliation run, including current order/transition/fill/item/run
fingerprints and real-fill Account Truth linkage. Per-order and session reviews
must provide the same batch fingerprint already present in their recorded
capital evaluation. Missing, open, duplicated, quantity-incomplete, or later-
changed facts fail closed. A clear batch fact does not authorize the next batch
and adds no broker, OMS, ledger, budget, or runtime-session capability.

Stage 2.2/3.2 adds public-key operator approval evidence. The capital-authority
API can issue a short-lived, nonce-bearing challenge and verify an Ed25519
signature for either an exact per-order dossier or controlled-session envelope.
Per-order confirmations and session attestations require the resulting approval
id and matching operator label. Disabled/rotated keys, expired challenges,
invalid signatures, and cross-artifact reuse fail closed. These endpoints do
not issue authority or add gateway, OMS, ledger, budget, submit, cancel, resume,
or automatic scale-up capability.

The Stage 4 foundation is an evidence-only capital scaling review. The
`/api/automation/capital-scaling` status, preview, evaluation, decision, and
history endpoints compare versioned tiers against operating days, fill/reject
quality, slippage, after-cost result, drawdown, capacity/liquidity,
reconciliation, divergence, disconnect, violation, and incident evidence.
Passing evidence can only request a separate new authorization; it never applies
a tier, mutates limits, resumes execution, or automatically scales capital.
Stage 4.1 now resolves broker-soak, execution-reconciliation, paper/shadow, and
risk references to persisted source facts and binds their sanitized resolution
fingerprint into the evaluation identity. Missing, non-clear, or out-of-window
sources fail closed. Account Truth is now a required evidence kind. Stage 4.2
adds read-only Account Truth point snapshots and computed evidence-window APIs
under `/api/automation/capital-scaling/evidence`: after-cost uses Modified
Dietz over persisted equity/cash-flow facts, incident metrics scan persisted
alerts/write rejections/connector observations, and capacity/liquidity/slippage
require non-simulated reconciled fills with explicit source linkage. Callers
cannot submit aggregate metric values; incomplete coverage records a blocked
fact, and even a clear window can only support a separate authorization request.
Stage 4.3 adds a required computed operating sample to that window: healthy
broker-soak trading days, non-paper OMS outcomes, reconciled real-fill linkage,
latest order-level reconciliation coverage and p95 latency, paper/shadow
divergence, and cash-flow-unitized maximum drawdown are derived from persisted
facts and checked exactly against the review request. Missing or truncated
coverage fails closed. This remains evidence-only and cannot grant authority,
change runtime limits, mutate OMS/ledger state, or contact a broker.
Stage 4.4 adds a required exact execution-scope fact. Every reviewed order must
bind either a persisted controlled-session admission or a current clear exact
batch that is wholly inside the operating sample. Identity mismatch, competing
bindings, orphan admissions, batch/source drift, and truncated scans fail
closed. V1 windows remain historical only; a current review requires an
append-only v2 recomputation. No scope fact can issue, resume, renew, or widen
authority or submit/cancel a broker order.

The v1.6 paper/shadow run path is:
daily trading plan -> pre-trade risk -> local paper/shadow run -> divergence
review -> manual confirmation. `POST /api/operations/paper-shadow/run` creates
or reuses an idempotent run record, deterministic simulated order/fill facts,
and a latest-run summary for Operations and Decision. These artifacts are
simulation evidence only: they do not create manual orders, mutate production
ledger entries, change cash or positions, store broker credentials, or submit
broker orders. If an operator accepts a diverged paper/shadow review, Operations
keeps the raw divergence evidence while exposing a runbook handoff status for
manual confirmation.

After a manual-ticket export, Trading links the operator to Account Truth
broker-statement import and execution-reconciliation review. Reconciliation
compares matching manual-execution evidence with staged broker price, quantity,
gross amount, fee, tax, transfer fee, and net amount. Matches and differences
are shown as a read-only Decision comparison and remain review evidence: they
do not change OMS state, write production ledger entries, alter cash or
positions, contact a broker, or submit orders.

The Web app localizes portfolio asset classes in the selected UI language
and keeps ledger rows auditable: trade activity surfaces the instrument name
and symbol when present, amount, quantity, price, and commission without
exposing technical confirmation metadata.

Account Truth import preview can parse the canonical broker statement CSV
format documented in
[docs/account-truth-import.zh.md](docs/account-truth-import.zh.md). The preview
validates rows, computes file and row fingerprints, marks duplicate rows, and
returns broker evidence objects. Valid previews can be staged through
`BrokerEvidenceRepository.save_preview()`, which records import-run metadata and
broker evidence events while detecting duplicate files.
`build_reconciliation_report()` compares staged broker evidence with Karkinos
cash, position, fee, tax, and cost-basis facts and returns pass, warning,
mismatch, or blocked review evidence. `ManualReviewRepository.record_decision()`
can persist accepted, ignored, known-difference, ledger-candidate, or
needs-investigation review states for reconciliation items. Each review is
bound to the exact reconciliation-item fingerprint and appended to audit
history. A stale or current manual label cannot override a material mismatch;
the broker evidence, ledger fact, or explicit reconciliation tolerance must
actually remove the difference. Broker evidence older than the latest local
ledger fact also fails closed as stale.
`build_account_truth_score()` converts reconciliation state, manual review
state, freshness, and unresolved differences into a 0-100 score plus pass,
degraded, or blocked gate status. These paths do not write production ledger
entries, change holdings, or submit broker orders.
Decision review and strategy promotion readiness consume this score as gate
evidence; degraded, blocked, or missing account-truth evidence prevents
live-like manual-confirm readiness or promotion readiness without authorizing
execution.

The Account Truth review API exposes the same evidence for Web and local review
workflows:

- `GET /api/account-truth/import-runs`
- `GET /api/account-truth/reconciliation-reports`
- `GET /api/account-truth/reconciliation-reports/{import_run_id}`
- `GET /api/account-truth/score`
- `POST /api/account-truth/reconciliation-reports/{import_run_id}/items/{item_key}/review`

The listing and report routes are read-only. The review route records a manual
review decision such as `accepted`, `ignored`, `known_difference`,
`ledger_candidate`, or `needs_investigation` for a reconciliation item.
`ledger_candidate` is an audit label only: it does not mutate production ledger
entries, change holdings, store broker credentials, or submit broker orders.
The Web Review Center consumes the same endpoints and keeps those actions as
manual audit decisions, not execution approval.

Backtest results are indexed in the local SQLite database at
`data/store/app.db` so the Web app, risk review surface, and strategy promotion
checks can query them. Each saved backtest also writes a human-readable JSON
artifact under `reports/backtest/backtest-result-<id>.json` by default. Set
`KARKINOS_BACKTEST_REPORT_DIR` to place those local report files elsewhere.
The report directory is runtime data and should stay out of git.

Every Strategy Lab run should be read through its `research_evidence_bundle`.
Treat `gate_status` as the research review state: `pass` means the attached
evidence is internally consistent enough for human review, `degraded` means a
data/OOS/cost/analyzer warning needs review, and `blocked` means the run should
not be promoted until the blocking evidence gap is fixed. The bundle records
the dataset snapshot id, strategy metadata, analyzer outputs, after-cost and
OOS availability, fills/trade statistics, China-market assumptions, known
limitations, and `promotion_gate.does_not_enable_execution=true`. It is
evidence for review, not investment advice, not a profitability claim, and not
authorization to submit broker orders.

Backtest fill records keep the legacy `commission` total and now expose the
same structured fee-breakdown contract used by paper broker evidence, manual
trade preview, and ledger projections: commission, stamp tax, transfer fee,
other fees, total fee, fee-rule id, and known limitations.
When a backtest report includes fill records, the Web equity/drawdown chart
overlays buy/sell markers and a compact marker summary beside the curve. Those
markers are research evidence from the saved backtest fills only; they do not
approve execution or attribute live account returns by themselves.
`POST /api/backtest/signal-preview` can run a registered strategy over explicit
single-symbol bars or a server-side single-symbol date range and return
research-only strategy-runtime audit records
(`buy`, `sell`, `rebalance`, or `no_action`) with dataset snapshot and data
quality context plus a structured review-gate chain for data readiness,
account truth, pre-trade risk, paper/shadow preview, and manual review. It
validates the same strategy parameter schema as backtests and does not persist
signals, create action tasks, submit orders, create fills, or mutate ledger
entries.
`POST /api/backtest/risk-preview` can size one of those research candidates and
run the same pre-trade risk rules against current account context as a
read-only preview. The response reports pass/blocked reasons, requires manual
confirmation, and explicitly does not create orders, persist risk decisions, or
mutate ledger entries.
`POST /api/backtest/paper-shadow-preview` can then simulate a passed, sized
candidate as paper/shadow evidence. It returns paper order/fill evidence,
after-cost fee breakdown, and a shadow-review summary without writing order
facts, fills, ledger entries, or broker submissions.
`POST /api/backtest/attribution-preview` summarizes the same single-symbol
preview chain into an attribution evidence boundary. It reports preview
evidence versus production order/fill facts, returns a read-only manual review
linkage candidate, and keeps strategy P/L unavailable until real signal, review,
order, and fill evidence are linked.

For CI, release review, or manual acceptance checks, export the current
acceptance audit manifests as JSON:

```bash
uv run python scripts/export_acceptance_audit.py --audit all --pretty
uv run python scripts/export_acceptance_audit.py --audit research_evidence
uv run python scripts/export_acceptance_audit.py --audit account_truth
uv run python scripts/export_acceptance_audit.py --audit broker_fee_cost_basis
uv run python scripts/export_acceptance_audit.py --audit operations_runbook
uv run python scripts/export_acceptance_audit.py --audit controlled_broker_bridge_foundation
uv run python scripts/export_acceptance_audit.py --audit capital_authorization_policy
uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_foundation
uv run python scripts/export_acceptance_audit.py --audit broker_connector_soak_promotion
uv run python scripts/export_acceptance_audit.py --audit per_order_confirmation_foundation
uv run python scripts/export_acceptance_audit.py --audit controlled_session_envelope_foundation
uv run python scripts/export_acceptance_audit.py --audit controlled_broker_submission
uv run python scripts/export_acceptance_audit.py --audit controlled_submission_interlock
uv run python scripts/export_acceptance_audit.py --audit signed_operator_approval
uv run python scripts/export_acceptance_audit.py --audit capital_scaling_review_foundation
uv run python scripts/export_acceptance_audit.py --audit all --output reports/acceptance-audit.json
```

The command writes to stdout by default and only creates a file when `--output`
is provided. Add `--verify-evidence` to fail closed when an evidence path is
missing, escapes the repository, or declares an unsupported validation command.
CI additionally passes the completed backend and frontend JUnit reports through
`--backend-junit` and `--frontend-junit`; the exported verification section
records their counts and SHA-256 fingerprints instead of treating static
completion flags as test execution proof.

Backend tests are grouped with pytest markers so local runs can stay focused:

```bash
uv run python -m pytest -m unit
uv run python -m pytest -m api_contract
uv run python -m pytest -m acceptance
uv run python -m pytest -m "not slow"
```

Full verification remains `uv run python -m pytest`.

Historical OHLCV market bars are stored in the local SQLite table
`data/store/meta.db.market_bars`; Parquet files under `data/store/bars/` are a
local mirror for compatibility and inspection. To import existing Parquet
mirrors into SQLite without fetching remote data, run
`uv run python scripts/sync_market_bars_to_db.py`. Cached data is auditable by
provider, fetch time, range, row count, and diagnostics, but it is not a
guarantee that every provider or public website will show identical values;
differences can come from adjustment mode, delayed fund NAVs, suspended
sessions, stale source data, or provider corrections.
The portfolio return, cost-basis, cash-flow, and baseline-price
semantics are documented in [docs/return-accounting.zh.md](docs/return-accounting.zh.md).
For an explicit one-symbol reconciliation report, run for example:
`uv run python scripts/verify_market_bars.py --symbol <symbol> --start 2026-06-12 --end 2026-06-15`.
The verifier fetches provider bars for comparison and returns JSON differences;
it does not overwrite the local cache.

In `dev` mode the script also starts Vite at `http://localhost:5173` for hot-reload frontend editing. Treat `5173` as a developer-only URL; use `8000` for product-like demos and customer flow checks.

The API only trusts local Vite origins by default:
`http://localhost:5173` and `http://127.0.0.1:5173`. For a real deployment,
set `KARKINOS_CORS_ALLOWED_ORIGINS` or `cors_allowed_origins` in your private
runtime config to the exact browser origins you operate. Avoid `*` for public
or credentialed deployments.

**Strategy Extensions**

Local research strategies belong under `strategy/extensions/`. Karkinos
discovers sanitized `*.strategy.json` manifests from that directory, or from
`KARKINOS_STRATEGY_EXTENSION_DIR`, and exposes their typed parameter schema via
`/api/backtest/strategies`. The committed `.example` files show the interface;
copied private strategy scripts and manifests stay ignored by git.

For private scripts stored directly in the extension directory, `class_path`
may point to the local module in `module:ClassName` form, for example
`my_strategy:MyStrategy`. Karkinos loads that class only when a
registered extension is instantiated for a research backtest, then validates
its declared params before constructing the strategy.

Extension manifests cannot declare live trading, broker submission, or
real-money execution capabilities. Strategy Lab runs remain research evidence
and do not bypass risk gates, paper/shadow review, signal journaling, or manual
confirmation.

For plain-language explanations of the built-in strategies, see the bilingual
strategy primer: [中文](docs/strategy/README.zh.md) /
[English](docs/strategy/README.en.md). It covers the built-in trend,
allocation, mean-reversion, volatility-targeting, and long-only pair-rotation
research strategies without making investment-advice or return claims.

**Account Strategy Context**

The Backtest page can show and save the current research-only account strategy
assignment through `/api/account-strategy`, and it can save symbol-specific
research strategy bindings through `/api/account-strategy/assignments`. These
assignments never enable automatic trading. Attribution and contribution
endpoints summarize linked signals, actions, risk decisions, orders, fills,
commissions, slippage, and the latest local valuation evidence when those
references exist.

Contribution reporting excludes manual trades, cash flows, and missing-evidence
market movement by default. It is audit tooling and research evidence, not
investment advice or execution approval.

**Docker**

```bash
docker compose up -d                   # build & start → http://localhost:8000
```

Uses ignored local `./config.json` as runtime configuration and persists market cache / SQLite data in the `karkinos-data` Docker volume. Runtime config is not a market-data store; watchlists, quotes, bars, ledger entries, and portfolio state should live in the local database.

Runtime databases, local logs, exported files, screenshots, and local secret
files should stay on your machine and are not intended to be committed.

**Tech Stack**

Python 3.12 + FastAPI + React + TanStack Query + TanStack Router + ECharts + SQLite + Parquet

**License**

MIT
