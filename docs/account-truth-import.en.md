# Account Truth import preview

[中文](account-truth-import.zh.md) | [Documentation](README.en.md)

Account Truth converts a local broker statement, cash ledger, or position
snapshot into auditable broker evidence before reconciliation determines what
needs human action. The current implementation provides a read-only preview of
canonical broker-statement CSV plus local staged-evidence persistence. It does
not write the production ledger, change positions, submit an order, or retain
broker login information.

## Privacy boundary

- Never commit a real broker export, account screenshot, transaction/cash
  ledger, or runtime database.
- Documentation and tests use synthetic data. Real CSV stays local.
- Preview computes file-level and row-level SHA-256 fingerprints for audit and
  deduplication.
- Preview and staged evidence are audit material, not investment advice or
  automatic-trading authority.

## CITIC history-trade XLS preview

A legacy `.xls` `历史成交` export from the CITIC desktop client can first be
checked through a privacy-minimized local preview:

- On the Account Truth page, expand **Stage new broker evidence**, select up to
  24 files in **Inspect CITIC history trades by month**, and choose **Preview
  selected CITIC XLS files**. The browser reads and requests them sequentially,
  with at most one file in flight. It clears each base64 request state after
  success or failure before continuing. Local file names remain visible only in
  the current browser UI and are not sent to the API.
- The batch summary deduplicates returned SHA-256 file fingerprints. Duplicate
  files remain visible but do not add their rows or events twice, and one read
  or request failure cannot make another file appear successful. Every
  successful preview remains `blocked`. The local API response contains counts,
  validation issues, and a file fingerprint, but no event, account, instrument,
  amount, file-name, or path details. The preview action itself performs no
  persistence.
- After preview, the operator may open a second confirmation for one
  non-duplicate file and either record it as a **follow-up source** or reject it.
  Confirmation rereads the same browser `File`, and the server verifies the full
  SHA-256. Base64 is cleared after the request. The page retains the original
  `File` reference only until record, rejection, or explicit batch clearing;
  the local file name is still never sent to the API.
- A follow-up source persists only fingerprints, validation counts, error codes,
  required-evidence codes, and the operator disposition. It stores no parsed
  events, account, instrument, amount, file name, or path and never writes
  `broker_evidence_events`. Structurally unusable files cannot be marked for
  follow-up and may only be rejected. Rejection is terminal; changed content
  must be previewed under a new fingerprint.
- The command-line equivalent is:

```bash
uv run python scripts/preview_citic_history_xls.py \
  --path /absolute/private/directory
```

The command accepts one `.xls` file or scans only the direct `.xls` children of
the selected directory. Standard output contains only a source-name hash, file
fingerprint, row counts, status, error codes, and limitations. It excludes
instrument names and symbols, trade times, quantities, amounts, remarks,
account identifiers, and absolute paths. It does not write a database, ledger,
positions, OMS, risk, kill switch, or capital authority.

The reviewed financial-event mapping currently covers A-share `证券买入`,
`证券卖出`, and `股息入账` rows. A `指定交易` row is counted only as a
non-financial activity requiring human review when it exactly matches
`799999 / 指定交易 / 指定 / 上海A股 / zero quantity and amounts` and has valid
dates, application identity, and order identity. It never creates a broker
event; any shape drift remains an invalid row and fails closed. Other unknown
business types, markets, symbols, amount relationships, cash signs, dates, or
order identities also fail closed. Shareholder code, fund account, customer
code, and shareholder name are checked only as provider-schema columns; their
values never enter normalized events, errors, notes, event identities, or row
fingerprints.

The history export contains gross trade amount and signed settlement amount,
but no itemized commission, stamp tax, or transfer fee and no cash or position
snapshot. The parser projects known fields into canonical events for local
preview but always returns `blocked`, so those events cannot be staged. A
follow-up source is also not authoritative Account Truth and cannot participate
in reconciliation, scoring, risk, or execution gates. It must not infer fee
components from the gross/net difference. Complete Account Truth still requires
separately reviewed settlement or cash-flow evidence plus a current cash and
position snapshot.

Every preview also includes
`karkinos.account_truth.citic_broker_soak_candidate.v1`, a deterministic
fail-closed assessment of the v1.8 read-only connector boundary. History Trades
alone is never a versioned connector snapshot and cannot start or count toward
the 20-trading-day broker soak. The assessment lists the missing source
contract: a reviewed account-alias binding, provider capture time,
connector/deployment health identity, current cash, position, and order
snapshots, and itemized fill fees and taxes. It also keeps adapter-release,
provider-calendar, and clear execution-reconciliation evidence as separate
operational prerequisites. This assessment registers no connector, records no
soak evidence, contacts no broker, and grants no execution or capital
authority.

### Configured local directory scan

To avoid selecting the same monthly files repeatedly, a private absolute
directory can be enabled in the Git-ignored local `config.json`:

```json
{
  "account_truth": {
    "citic_history_xls_directory": {
      "enabled": true,
      "path": "/absolute/private/account-exports",
      "max_files": 120,
      "max_file_bytes": 10485760,
      "max_total_bytes": 67108864
    }
  }
}
```

This does not start a watcher. The Account Truth page first reads sanitized
configuration status, then scans only after the operator selects **Scan
configured directory**. The command considers direct-child `.xls` files only,
rejects symlinks, changing files and exceeded limits, deduplicates by full
content fingerprint, and returns no path, file name, event, account, instrument,
or amount details. The scan itself persists nothing.

The sanitized scan response also includes
`karkinos.account_truth.citic_history_xls_batch_assessment.v1`. It detects
within-file duplicates, cross-file duplicate events, conflicting event
identities, invalid event times, and sources with no recognized financial
events, then reports only aggregate counts, observed event months, blockers,
and a deterministic fingerprint. An `integrity_status: clear` means only that
the inspected file set has no detected structural or event-identity conflict.
Observed months never prove each export's query window or complete monthly
coverage; reviewed query windows, itemized settlement or cash-flow evidence,
current cash and positions, and account binding remain required. The assessment
therefore always has `status: blocked`, persists no events, and is ineligible
for Account Truth and reconciliation.

The explicit directory scan also returns
`karkinos.account_truth.citic_history_canonical_lineage_assessment.v1`. This
read-only runtime projection compares only the financial semantics available in
the XLS batch with the currently selected canonical import and reports sanitized
counts for semantic matches, unmatched source/canonical events, preserved
broker-order identities, and exact event identities. It never returns event,
account, source-name, or path details and never persists the comparison. A
semantic match without the same event and broker-order identity is partial
evidence, not canonical provenance. Even exact event lineage would not prove
query-window completeness, itemized settlement, current snapshots, or complete
account coverage, so the assessment cannot promote the batch into Account Truth
or reconciliation.

Recording a follow-up or rejection remains a separate second confirmation. The
server re-scans the configured directory and must find the exact previewed
SHA-256; missing or changed content fails closed. Only the same sanitized source
review metadata is stored. Browser file selection remains available when the
directory is disabled or unavailable.

### Explicit query-window review for one source

Each persisted `follow_up_required` source still has an unproven broker query
window. The owner may enter the exact start and end dates shown in the broker
query UI and explicitly attest that they apply to that exact export. Dates are
never inferred from observed event months. The server binds the review to both
the current file fingerprint and sanitized source-preview fingerprint, rejects
future dates and windows longer than 31 inclusive days, and requires every
recognized financial event to fall inside the attested window. A source with no
recognized financial event may still have its query window reviewed; it remains
an incomplete non-canonical source.

The review is append-only and idempotent. An active window must be explicitly
revoked before different dates can be accepted, and revocation is bound to the
active review id and fingerprint so stale UI state fails closed. The record
contains only source/review fingerprints, intake id, dates, decision, reviewer,
and audit timestamps. It contains no source name or path, account, transaction,
instrument, amount, or parsed event. Listing it opens the existing SQLite store
strictly read-only; absent schema means no review, while partial, incompatible,
or malformed state fails closed without repair.

An explicit directory scan also projects the still-active reviews that exactly
match current source fingerprints into
`karkinos.account_truth.citic_query_window_batch_assessment.v1`. This read-only
assessment checks only the calendar-day union, gaps, and overlaps of the
declared dates. Review identities bind its deterministic assessment fingerprint
without exposing intake ids, review fingerprints, source names, or paths. An
`integrity_status: clear` means only that every current source is reviewed and
the owner-declared dates are contiguous and non-overlapping. Its `status`
remains `blocked`: it cannot prove earlier or later dates, complete account or
asset scope, itemized settlement, current cash or positions, Account Truth,
reconciliation, execution, or capital authority.

Completing these reviews clears only the query-window blocker. The source-level
Operations follow-up remains blocked until every current source also has an
exact source-scope review. Query-window review does not prove complete period
coverage, bind an account, promote events into Account Truth, satisfy
settlement/current-snapshot/reconciliation gates, contact the broker, enable
submission, or change capital authority. Revocation immediately reopens the
query-window blocker.

### Explicit source-scope review for one source

For each active query-window review, the owner must separately declare a local
account alias, account type, market scopes, asset classes, an account-value-band
code, and business types. The owner must also attest that no other broker-query
filters applied, the file contains every row returned by that exact query, and
the declared account and scope apply to that exact export. All code lists and
the value-band code must be non-empty. The raw broker account identifier is
hashed in the browser and is never sent to the API or stored; the server
receives only a domain-separated SHA-256 binding. The value band is sanitized
query-scope metadata. It is not a current balance, an order limit, or capital
authority and must never be used to widen any authorization.

The append-only review binds the current intake id, file fingerprint,
source-preview fingerprint, and the exact active query-window review id and
fingerprint. A stale, rejected, or changed source/query binding fails closed.
An identical replay is idempotent; a conflicting active declaration must first
be explicitly revoked. The read path remains zero-write: missing schema means
no review, and partial, incompatible, or malformed persistence fails closed
without repair. Revoking a query window in the UI first revokes its active
source-scope review, preserving dependency order.

Directory scans project only exact active declarations into
`karkinos.account_truth.citic_source_scope_batch_assessment.v2`. The batch can
report `integrity_status: clear` only when every current source is reviewed,
all account-reference hashes agree, all declared scopes including the
account-value band agree, and the no-extra-filter and complete-returned-results
attestations are present. The response exposes the safe declared codes and a
deterministic assessment fingerprint, but not account-reference hashes,
intake/review identities, source names, paths, events, or transactions. Legacy
v1 records remain read-only compatible but are incomplete until explicitly
revoked and replaced by an append-only v2 review with a value band. Even a
clear declaration remains
`status: blocked`: legacy history-trade XLS files still do not prove complete
account coverage, itemized settlement, current cash/positions, reconciliation,
execution authority, or capital authority.

Only when both the query-window and source-scope batches are exact and
consistent can the Operations source follow-up advance to requesting canonical
Account Truth evidence or an explicit rejection of the legacy source. It still
cannot promote events, contact the broker, submit or cancel orders, or expand
capital authority.

A directory scan may derive one strictly formatted `YYYYMM` token from a local
file name and return only its sanitized `YYYY-MM` form as a runtime month hint.
The full name and path remain suppressed. The hint helps the owner distinguish
sources in one batch, but it is excluded from scan and review fingerprints,
never persisted, never used to prefill dates, and never treated as query-window
evidence. If no unique month token exists, directory-mode record/reject actions
fail closed and the owner must select the exact file in the browser instead of
guessing from directory order.

Listing reviewed sources is a strictly read-only path. Constructing the intake
repository or calling its GET/list projection does not create a database,
directory, table, or index. A missing intake schema means that no source has
been reviewed; a partial or incompatible schema fails closed and is not
silently repaired by the read path.

The same boundary applies to canonical broker evidence and reconciliation
review decisions. Repository construction and all GET/list calls open an
existing SQLite database in read-only mode; absent tables mean no evidence,
while partial/incompatible schema or malformed persisted records fail closed.
Only the explicit broker import and manual review commands may create or
migrate those tables.

Persisted `follow_up_required` reviews also appear in the Operations evidence
queue through `karkinos.account_truth.citic_source_follow_up.v1`. The projection
contains only counts, required-evidence/error codes, reviewed query-window
integrity, the latest review time, and deterministic fingerprints; it contains
no source path, file name, transaction detail, or account fact. Its bounded
read fails closed if the source scan reaches 200 rows, and reviewed windows with
a gap or overlap remain blocked. It stays outside canonical Operations health,
but the sanitized follow-up fingerprint is bound into the Account Truth
promotion evidence consumed by controlled execution. Pending, truncated,
unreadable, gapped, or overlapping source review can therefore only downgrade
promotion from clear to blocked. Rejecting a source clears that source-review
task but does not create Account Truth evidence or grant reconciliation, risk,
execution, or capital authority.

The Account Truth page projects those source reviews together with the
canonical score through `karkinos.account_truth.evidence_readiness.v2`. Its
`karkinos.account_truth.evidence_scope.v1` child reports the date span, asset
classes, currencies, and snapshot dates observed in the exact persisted import,
but never treats first/last rows as proof of complete account or period coverage.
Account binding, a declared coverage window, and asset-scope completeness remain
blocked until the owner explicitly reviews the exact import.

That explicit review hashes the broker account identifier in the browser; the
raw identifier is never sent to the API or persisted. The append-only record
binds the import fingerprint, observed-scope fingerprint, provider, local alias,
hashed account reference, reviewed dates, and reviewed asset classes. Repeating
the same action is idempotent; a later review is append-only, and revocation or
source drift fails closed. The action changes no broker evidence, ledger,
reconciliation result, execution authority, or capital authority.

The readiness checklist visibly includes the persisted query-window integrity
status and gap/overlap day counts. It also covers current cash/position snapshots, itemized
settlement fees and taxes, cost basis, freshness and ledger coverage, the
reconciliation gate, and known incomplete sources. It reports `ready` only when
the Account Truth gate and every requirement pass. Missing schema means no
evidence; partial/incompatible schema or malformed rows fail closed. This GET
does not scan the private directory, contact a provider, write the database, or
gain reconciliation, submit/cancel, or capital authority.

## Automatic local reading

Local daily operation may explicitly enable a read-only collector so the same
file does not need to be selected in the browser after every change:

```json
{
  "account_truth": {
    "broker_statement_collector": {
      "enabled": true,
      "path": "broker_statement.csv",
      "poll_interval_seconds": 5,
      "stability_delay_seconds": 2,
      "max_file_bytes": 10485760
    }
  }
}
```

The collector runs only when startup configuration enables it. It waits for a
stable size/mtime, then reads and validates the complete file and stages it by
fingerprint. Repeated polls and process restarts reuse the same import run for
unchanged content and preserve its first-seen `created_at`; replay cannot make
old evidence look fresh. Missing, changing, oversized, incorrectly encoded, or
schema-blocked files fail closed while previously staged evidence remains.
`GET /api/account-truth/broker-statement/collector` exposes read-only status.

This is not automatic ledger posting. The collector cannot contact a provider
or modify the production ledger, positions, OMS, risk, kill switch, or capital
authority. Differences still require Account Truth review; manual upload stays
available as a fallback.

## Canonical CSV columns

The CSV contains every required column below. Leave an unused value empty; do
not remove the column.

| Column              | Description                                                              |
| ------------------- | ------------------------------------------------------------------------ |
| `event_id`          | Stable broker/import event id; unique within the file.                   |
| `event_type`        | Event type from the supported enumeration.                               |
| `occurred_at`       | Business timestamp; prefer timezone-aware ISO-8601.                      |
| `settled_at`        | Settlement date or timestamp.                                            |
| `symbol`            | Required for trades, dividends, and position snapshots.                  |
| `instrument_name`   | Display and human-review name.                                           |
| `asset_class`       | Such as `stock`, `fund`, or `cash`.                                      |
| `currency`          | Such as `CNY`.                                                           |
| `quantity`          | Event quantity; use `0` for cash-only events.                            |
| `price`             | Trade/NAV/snapshot price; use `0` when inapplicable.                     |
| `gross_amount`      | Amount before fees and tax.                                              |
| `fee`               | Commission or other fee.                                                 |
| `tax`               | Tax.                                                                     |
| `net_amount`        | Net cash effect; buys are normally negative and sells/deposits positive. |
| `cash_balance`      | Cash balance after the event; may be empty if unknown.                   |
| `position_quantity` | Position after the event; may be empty.                                  |
| `cost_basis`        | Broker cost basis after the event; may be empty.                         |
| `note`              | Publicly explainable note only; no account or credential data.           |

Optional columns are preserved when present:

| Column              | Description                                                                |
| ------------------- | -------------------------------------------------------------------------- |
| `transfer_fee`      | Transfer fee; defaults to `0` when absent.                                 |
| `cost_basis_method` | Broker basis convention such as `broker_remaining_cost`; explanatory only. |
| `broker_order_id`   | Broker-order evidence; only letters, digits, `._:-`, up to 128 characters. |
| `client_order_id`   | Idempotent Karkinos client-order evidence with the same character rules.   |

Order ids are evidence, not write authority. A trade row missing either id
cannot clear a controlled submission as a complete fill. Clearance also needs
both ids to match the persisted submit intent, come from one verified import,
and cover the complete OMS quantity.

Supported `event_type` values:

- `trade_buy`
- `trade_sell`
- `dividend`
- `fee`
- `tax`
- `transfer_in`
- `transfer_out`
- `position_snapshot`
- `cash_snapshot`

## Safe synthetic example

The sample symbols and names are synthetic and do not describe a real account.

```csv
event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,Synthetic Stock A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row,0.00,broker_remaining_cost,BROKER-SYN-001,KARK-SYN-001
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,Synthetic Stock A,stock,CNY,20,10.50,210.00,5.00,0.21,204.79,9176.79,80,10.28,synthetic sell row,0.00,broker_remaining_cost,BROKER-SYN-002,KARK-SYN-002
synthetic-dividend-001,dividend,2026-01-12T15:30:00+08:00,2026-01-12,SYN001,Synthetic Stock A,stock,CNY,80,0,12.50,0.00,0.00,12.50,9189.29,80,10.28,synthetic dividend row,,
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,9188.04,,,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,9187.29,,,,,
synthetic-transfer-in-001,transfer_in,2026-01-15T08:45:00+08:00,2026-01-15,,,,CNY,0,0,500.00,0.00,0.00,500.00,9687.29,,,,,
synthetic-transfer-out-001,transfer_out,2026-01-15T09:45:00+08:00,2026-01-15,,,,CNY,0,0,-300.00,0.00,0.00,-300.00,9387.29,,,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,Synthetic Stock A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,9387.29,80,10.28,synthetic position snapshot,,broker_remaining_cost
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,9387.29,,,,,
```

## Import-preview behavior

Python entry point:

```python
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
```

The result contains:

- `schema_version = "karkinos.broker_statement.v2"`
- `source_type = "canonical_broker_statement_csv"`
- `file_fingerprint`
- row, valid, invalid, and duplicate counts
- `validation_status`: `pass`, `warning`, or `blocked`
- normalized `events[]`
- blocking/validation `errors[]`
- current-boundary `limitations[]`

Deduplication is deterministic: identical normalized rows share a
`row_fingerprint`; a later occurrence has `is_duplicate=true` and records
`duplicate_of_row_number`.

## Staged broker evidence

```python
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
repository = BrokerEvidenceRepository("data/store/app.db")
import_run = repository.save_preview(preview, source_name="local-statement.csv")
```

`save_preview()` writes:

- `broker_import_runs`: run identity, schema/source, sanitized source name,
  file fingerprint, row/validation/duplicate counts, limitations, and time.
- `broker_evidence_events`: each valid event's type, row fingerprint, numeric
  amounts, snapshot fields, broker basis convention, optional order identities,
  and row-duplicate evidence.

If the file fingerprint already exists, the existing `import_run_id` is reused
without inserting the events again or refreshing its evidence age. This stage
never writes `ledger_entries`.

## Reconciliation report

A broker dividend that occurred earlier may cover a ledger entry captured
later on the same Shanghai date only when symbol and net amount match exactly,
the same import contains a cash snapshot at or after the dividend, and that
broker event has not already covered another ledger row. Conflicts, missing
post-event snapshots, and duplicate local capture remain stale and blocked.

```python
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    build_reconciliation_report,
)

report = build_reconciliation_report(
    import_run_id=import_run.import_run_id,
    broker_events=repository.list_events(import_run.import_run_id),
    ledger_facts=[
        KarkinosLedgerFact(
            event_type="trade_buy",
            symbol="SYN001",
            quantity=Decimal("100"),
            price=Decimal("10.23"),
            fee=Decimal("5.00"),
            tax=Decimal("0.00"),
            net_amount=Decimal("-1028.00"),
        )
    ],
    cash_balance=Decimal("8970.00"),
    positions=[
        KarkinosPositionFact(
            symbol="SYN001",
            quantity=Decimal("100"),
            cost_basis=Decimal("10.28"),
        )
    ],
)
```

Schema `karkinos.account_truth.reconciliation.v1` compares:

- broker versus Karkinos cash;
- broker versus Karkinos position quantity;
- broker versus Karkinos trade gross amount and signed net cash effect;
- fees, taxes, and transfer fees;
- broker versus Karkinos cost basis.

Status is `pass`, `warning`, `mismatch`, or `blocked`. Missing snapshots produce
evidence requests; differences produce explicit review actions for cash,
position, gross amount, net cash, fee, tax, transfer fee, and cost basis. The
report is evidence only and creates no ledger entry.

## Manual review decisions

```python
from account_truth.manual_review import ManualReviewRepository

review_repository = ManualReviewRepository("data/store/app.db")
decision = review_repository.record_decision(
    import_run_id=import_run.import_run_id,
    item_key="cash",
    category="cash",
    review_status="needs_investigation",
    note="Review the broker cash-balance snapshot",
    reviewer="local",
)
```

Supported `review_status` values:

- `accepted`
- `ignored`
- `known_difference`
- `ledger_candidate`
- `needs_investigation`

The current decision for one `import_run_id` + `item_key` is updated while
every decision is appended to history. Each decision binds the reconciliation
item fingerprint. A changed broker/local value, difference, status, or context
invalidates the old decision for current use while retaining it for audit.
`ledger_candidate` never creates or changes a ledger entry.

## Reviewed fee schedule for strategy research

The configured `broker_fee_schedule` is only a proposal until it is compared
with the exact current Account Truth import and explicitly reviewed. The human
workflow is:

```text
POST /api/account-truth/fee-schedule/preview
GET  /api/account-truth/fee-schedule/review
POST /api/account-truth/fee-schedule/reviews
POST /api/account-truth/fee-schedule/reviews/revoke
```

Preview requires a ready Account Truth checklist, a clear promotion projection,
the same reviewed account alias, valid source/scope fingerprints, persisted buy
and sell trades, and stock/ETF component agreement for commission plus other
fees, stamp tax, and transfer fee within the reconciliation tolerance. Canonical
`fund`/`fund_etf` values normalize to ETF only inside this fee review; mismatches
are grouped by asset class, side, and component. Stock and ETF transfer-fee
rates are reviewed separately; when the ETF term is omitted it inherits the
legacy stock term. A legacy accepted review remains readable for audit but must
be recomputed and accepted again before downstream use. It returns only aggregate
counts, maximum differences, safe schedule terms, and fingerprints; broker rows,
symbols, account identifiers, file names, and source details are not copied into
the review store.

Approval recomputes the preview and requires its exact fingerprint, reviewer,
and confirmation
`approve_reconciled_account_fee_schedule_for_research_only_without_execution_or_capital_authority`.
The append-only review is revocable with its exact id/fingerprint and
`revoke_reconciled_account_fee_schedule_without_execution_or_capital_authority`.
GET is query-only and never initializes or repairs schema.

The Account Truth Review Center exposes the same sequence as an explicit human
workflow: choose the reviewed evidence window, recompute the preview, inspect
buy/sell coverage and aggregate component matches, then enter a reviewer and
the complete confirmation phrase. Approval is unavailable for a blocked or
stale preview. An accepted record is displayed as `active` only while a
query-only recomputation still matches its exact preview fingerprint; current
Account Truth or fee-evidence drift displays `blocked`, even though the older
accepted record remains visible for audit and can still be explicitly revoked.

An active review becomes a versioned cost-model reference. The same resolved
calculator, including exchange overrides and per-component money rounding, is
used for both the refreshed baseline and every Formula candidate/parameter
variant. Critique, promotion, and each reserved ticket re-resolve the active
review; Account Truth drift, tampering, revocation, a mismatched reference, or
an uncovered backtest/action date returns no-action. The built-in estimate and
an absent review are ineligible. This review cannot submit an order, register a
production strategy, or change capital authority.

## Broker settlement confirmation

Once a trade detail or statement supplies actual commission, stamp tax,
transfer fee, and net cash effect, explicitly confirm an existing trade:

```text
POST /api/ledger/trades/{entry_id}/settlement
```

The endpoint never places an order and is not called automatically by Account
Truth import. It validates that net cash agrees with gross amount and fee
components, then in one transaction:

- preserves the original estimates and fee rule;
- updates effective fees and net cash to broker-confirmed values;
- records source, evidence reference, confirmation time, and note;
- appends `portfolio.trade_settlement.confirmed` with before/after values;
- handles identical `source` + `source_ref` idempotently and rejects conflicts.

Pre-trade modeling remains useful for estimates/backtests; post-trade cash,
cost, and reconciliation use broker-confirmed values. Evidence must be a trade
detail, statement, or equivalent settlement source, not an inferred homepage
summary.

## Account Truth Score

```python
from account_truth.score import build_account_truth_score

score = build_account_truth_score(
    report=report,
    review_decisions=review_repository.list_decisions(report.import_run_id),
    data_freshness_status="fresh",
)
```

`karkinos.account_truth.score.v1` contains:

- deterministic `score` from 0 to 100;
- `gate_status`: `pass`, `degraded`, or `blocked`;
- cash, position, fee, and cost-basis status;
- `data_freshness_status`: `fresh`, `stale`, or `missing`;
- unresolved mismatch and resolved review counts;
- required actions, blocking reasons, and limitations.

Human review records disposition but does not override a live `mismatch` or
`blocked` fact. A material difference clears only through updated broker
evidence, an explicit ledger correction, or a numeric tolerance in
reconciliation. Broker evidence older than the latest ledger fact is `stale`
with `account_truth_evidence_predates_latest_ledger`. The score informs product
surfaces and promotion gates; it never mutates the ledger or submits an order.
