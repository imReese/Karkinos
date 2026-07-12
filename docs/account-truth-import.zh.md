# Account Truth 导入预览

Account Truth 用于把本地券商交割单、资金流水或持仓快照先转换成可审计的
broker evidence，再由后续对账流程决定是否需要人工处理。当前实现提供
canonical broker statement CSV 的只读导入预览，以及 staged broker evidence
本地持久化；它不会写入生产 ledger，不会修改持仓，不会提交券商订单，也不会
保存券商登录信息。

## 隐私边界

- 不要提交真实券商导出、账户截图、交易流水、资金流水或运行时数据库。
- 文档和测试只能使用合成数据。真实 CSV 应只保留在本机运行环境。
- 导入预览会计算文件级 SHA-256 指纹和行级 SHA-256 指纹，用于审计和去重。
- 预览和 staged broker evidence 是审计材料，不是投资建议，也不是自动交易授权。

## Canonical CSV 列

CSV 必须包含以下列。未涉及的字段保留为空字符串，不要删除列。

| 列名 | 说明 |
|------|------|
| `event_id` | 券商侧或导入侧稳定事件编号；同一文件内应唯一 |
| `event_type` | 事件类型，见下方枚举 |
| `occurred_at` | 业务发生时间，推荐 ISO-8601，含时区 |
| `settled_at` | 结算日期或时间 |
| `symbol` | 标的代码；交易、分红和持仓快照事件必填 |
| `instrument_name` | 标的名称；展示和人工复核使用 |
| `asset_class` | 资产类别，例如 `stock`、`fund`、`cash` |
| `currency` | 币种，例如 `CNY` |
| `quantity` | 发生数量；现金类事件填 `0` |
| `price` | 成交价、净值或快照价；不适用时填 `0` |
| `gross_amount` | 税费前金额 |
| `fee` | 手续费、佣金或其他费用 |
| `tax` | 税费 |
| `net_amount` | 现金净影响；买入通常为负，卖出或入金通常为正 |
| `cash_balance` | 事件后现金余额；未知可空 |
| `position_quantity` | 事件后持仓数量；未知可空 |
| `cost_basis` | 事件后成本价或成本基准；未知可空 |
| `note` | 仅放可公开解释的备注，不放账号、手机号、券商凭证或私密信息 |

CSV 也可以包含以下可选列。旧文件不需要补列；如果存在，导入预览会保留它们用于
更细的费用和成本价对账。

| 列名 | 说明 |
|------|------|
| `transfer_fee` | 过户费或券商单独列出的转让/过户费用；未知可空，默认 `0` |
| `cost_basis_method` | 券商成本价口径，例如 `broker_remaining_cost`；仅用于人工复核解释 |

支持的 `event_type`：

- `trade_buy`
- `trade_sell`
- `dividend`
- `fee`
- `tax`
- `transfer_in`
- `transfer_out`
- `position_snapshot`
- `cash_snapshot`

## 安全合成样例

下面的样例使用合成符号和合成名称，不对应真实账户或真实交易。

```csv
event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row,0.00,broker_remaining_cost
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,合成样例股票A,stock,CNY,20,10.50,210.00,5.00,0.21,204.79,9176.79,80,10.28,synthetic sell row,0.00,broker_remaining_cost
synthetic-dividend-001,dividend,2026-01-12T15:30:00+08:00,2026-01-12,SYN001,合成样例股票A,stock,CNY,80,0,12.50,0.00,0.00,12.50,9189.29,80,10.28,synthetic dividend row,,
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,9188.04,,,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,9187.29,,,,,
synthetic-transfer-in-001,transfer_in,2026-01-15T08:45:00+08:00,2026-01-15,,,,CNY,0,0,500.00,0.00,0.00,500.00,9687.29,,,,,
synthetic-transfer-out-001,transfer_out,2026-01-15T09:45:00+08:00,2026-01-15,,,,CNY,0,0,-300.00,0.00,0.00,-300.00,9387.29,,,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,9387.29,80,10.28,synthetic position snapshot,,broker_remaining_cost
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,9387.29,,,,,
```

## 导入预览行为

当前 Python 入口：

```python
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
```

预览结果包含：

- `schema_version = "karkinos.broker_statement.v1"`
- `source_type = "canonical_broker_statement_csv"`
- `file_fingerprint`
- `row_count`
- `valid_row_count`
- `invalid_row_count`
- `duplicate_row_count`
- `validation_status`：`pass`、`warning` 或 `blocked`
- `events[]`：标准化后的 broker evidence events
- `errors[]`：阻断或校验错误
- `limitations[]`：当前导入边界说明

重复检测是确定性的：完全相同的标准化行会得到相同 `row_fingerprint`，后出现
的行会标记 `is_duplicate=true` 并记录 `duplicate_of_row_number`。

## Staged broker evidence

当前 Python 入口：

```python
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv

preview = parse_broker_statement_csv(csv_text)
repository = BrokerEvidenceRepository("data/store/app.db")
import_run = repository.save_preview(preview, source_name="local-statement.csv")
```

`save_preview()` 会写入：

- `broker_import_runs`：`import_run_id`、schema version、source type、source name、
  file fingerprint、row counts、validation status、row duplicate count、
  file duplicate count、limitations、created timestamp。
- `broker_evidence_events`：每一条合法 broker evidence event 的 event type、
  row fingerprint、数量、价格、税费前金额、佣金/费用、税费、过户费、现金净影响、
  快照字段、券商成本价口径和行级重复信息。

如果同一 `file_fingerprint` 已经导入过，新 import run 会记录
`file_duplicate_count=1` 与 `duplicate_of_import_run_id`，并且不会再次写入
broker evidence events。这个阶段仍然不会写入或修改 `ledger_entries`；后续对账
和人工确认流程会决定哪些差异需要处理。

## Reconciliation report

当前 reconciliation 核心入口：

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

报告 schema version 为 `karkinos.account_truth.reconciliation.v1`，当前会比较：

- broker cash snapshot vs Karkinos cash balance；
- broker position snapshot vs Karkinos position quantity；
- broker trade gross amount vs Karkinos trade gross amount；
- broker signed net cash impact vs Karkinos ledger cash impact；
- broker fees vs Karkinos ledger fees；
- broker taxes vs Karkinos ledger taxes；
- broker transfer fees vs Karkinos ledger transfer fees；
- broker cost basis vs Karkinos position cost basis。

报告状态为 `pass`、`warning`、`mismatch` 或 `blocked`。快照证据不足时会输出
`provide_cash_snapshot`、`provide_position_snapshot` 等补证建议；有差异时会输出
`review_cash_difference`、`review_position_difference`、
`review_trade_gross_amount_difference`、`review_net_cash_impact_difference`、
`review_fee_difference`、`review_tax_difference`、
`review_transfer_fee_difference`、`review_cost_basis_difference` 等建议复核动作。
当前报告只是差异证据，不会自动生成 ledger entry，也不会修改现金、持仓或成本基础。

## Manual review decisions

当前 manual review 入口：

```python
from account_truth.manual_review import ManualReviewRepository

review_repository = ManualReviewRepository("data/store/app.db")
decision = review_repository.record_decision(
    import_run_id=import_run.import_run_id,
    item_key="cash",
    category="cash",
    review_status="needs_investigation",
    note="需要核对券商资金余额快照",
    reviewer="local",
)
```

支持的 `review_status`：

- `accepted`
- `ignored`
- `known_difference`
- `ledger_candidate`
- `needs_investigation`

同一个 `import_run_id` + `item_key` 会更新当前复核状态，同时把每次决定追加到复核
历史表。每条复核决定绑定当时 reconciliation item 的事实指纹；券商值、本地值、差额、
状态或口径上下文发生变化后，旧复核保留用于审计，但会标记为失效。`ledger_candidate`
只是人工复核标记，不会自动创建或修改 `ledger_entries`；真正写入生产账本仍需要后续
显式确认流程。

## 券商结算确认

当交易明细或交割单已经给出实际佣金、印花税、过户费和净现金影响时，可以通过显式
接口确认一条已有交易流水：

```text
POST /api/ledger/trades/{entry_id}/settlement
```

该接口不会下单，也不会从 Account Truth 导入时自动调用。它会先校验净现金影响与
成交总额、费用分项是否一致，然后在同一事务中：

- 首次保存原始估算佣金、费用分项、净现金影响和费用规则；
- 将交易流水的有效费用和净现金影响更新为券商实际结算值；
- 记录结算来源、证据引用、确认时间和备注；
- 追加 `portfolio.trade_settlement.confirmed` 审计事件，保留调整前后值和现金差额；
- 对同一个 `source` + `source_ref` 幂等处理，冲突值会被拒绝。

因此，交易前费用模型仍可用于预估和回测；成交后的现金、成本和 Account Truth 对账
则使用券商确认值。来源必须是交易明细、交割单或等价的结算证据，不能仅凭首页汇总
展示反推每笔费用。

## Account Truth Score

当前 score 入口：

```python
from account_truth.score import build_account_truth_score

score = build_account_truth_score(
    report=report,
    review_decisions=review_repository.list_decisions(report.import_run_id),
    data_freshness_status="fresh",
)
```

`AccountTruthScore` schema version 为 `karkinos.account_truth.score.v1`，包含：

- `score`：0-100 的确定性账户事实分；
- `gate_status`：`pass`、`degraded` 或 `blocked`；
- `cash_status`、`position_status`、`fee_status`、`cost_basis_status`；
- `data_freshness_status`：`fresh`、`stale` 或 `missing`；
- `unresolved_mismatch_count` 与 `resolved_review_count`；
- `required_actions`、`blocking_reasons` 和 `limitations`。

人工复核状态只记录审计处置，不覆盖仍然存在的 `mismatch` 或 `blocked`。物质性差异
必须通过更新券商证据、显式纠正账本，或由 reconciliation 的明确数值容差重新归类后
才能解除门禁。最新券商导入若早于最新本地账本事实，score 会标为 `stale` 并附加
`account_truth_evidence_predates_latest_ledger` 阻断。Score 只是 cockpit、promotion
gate 和报告可消费的账户事实信号，不会自动修改账本或提交订单。
