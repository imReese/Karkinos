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
unchanged content. Missing, changing, oversized, incorrectly encoded, or
schema-blocked files fail closed while previously staged evidence remains.
`GET /api/account-truth/broker-statement/collector` exposes read-only status.

This is not automatic ledger posting. The collector cannot contact a provider
or modify the production ledger, positions, OMS, risk, kill switch, or capital
authority. Differences still require Account Truth review; manual upload stays
available as a fallback.

## Canonical CSV columns

The CSV contains every required column below. Leave an unused value empty; do
not remove the column.

| Column | Description |
| --- | --- |
| `event_id` | Stable broker/import event id; unique within the file. |
| `event_type` | Event type from the supported enumeration. |
| `occurred_at` | Business timestamp; prefer timezone-aware ISO-8601. |
| `settled_at` | Settlement date or timestamp. |
| `symbol` | Required for trades, dividends, and position snapshots. |
| `instrument_name` | Display and human-review name. |
| `asset_class` | Such as `stock`, `fund`, or `cash`. |
| `currency` | Such as `CNY`. |
| `quantity` | Event quantity; use `0` for cash-only events. |
| `price` | Trade/NAV/snapshot price; use `0` when inapplicable. |
| `gross_amount` | Amount before fees and tax. |
| `fee` | Commission or other fee. |
| `tax` | Tax. |
| `net_amount` | Net cash effect; buys are normally negative and sells/deposits positive. |
| `cash_balance` | Cash balance after the event; may be empty if unknown. |
| `position_quantity` | Position after the event; may be empty. |
| `cost_basis` | Broker cost basis after the event; may be empty. |
| `note` | Publicly explainable note only; no account or credential data. |

Optional columns are preserved when present:

| Column | Description |
| --- | --- |
| `transfer_fee` | Transfer fee; defaults to `0` when absent. |
| `cost_basis_method` | Broker basis convention such as `broker_remaining_cost`; explanatory only. |
| `broker_order_id` | Broker-order evidence; only letters, digits, `._:-`, up to 128 characters. |
| `client_order_id` | Idempotent Karkinos client-order evidence with the same character rules. |

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
without inserting the events again. This stage never writes `ledger_entries`.

## Reconciliation report

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
