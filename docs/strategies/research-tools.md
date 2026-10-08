# 本地研究工具

这些工具服务于 Python 研究和已有记录复核。它们不采集供应商数据，也不写入账户、授予策略资格或提交交易。

## 财报观察的时点选择

[`FinancialResearchStore`](../../data/financials.py) 是内存研究集合。每条观察必须区分财报期末 `end_date`、披露事件 `event_time`、信息可用时间 `available_at` 和本地获取时间 `captured_at`，并携带 `source`、报表口径 `scope`、版本 `revision_id`。时间必须含时区。只有公告日期的数据不能直接填成盘前可用时间。

下面是合成数据的使用示例：

```python
from datetime import date, datetime, timezone
from core.types import Symbol
from data.financials import FinancialResearchStore, FinancialStatementObservation

disclosed = datetime(2026, 4, 25, 10, tzinfo=timezone.utc)
captured = datetime(2026, 4, 25, 10, 5, tzinfo=timezone.utc)
store = FinancialResearchStore(
    [
        FinancialStatementObservation(
            symbol=Symbol("600000"),
            end_date=date(2025, 12, 31),
            event_time=disclosed,
            available_at=disclosed,
            captured_at=captured,
            source="synthetic_archive",
            scope="consolidated_annual_CNY",
            revision_id="annual-v1",
            roe=12.5,
        )
    ]
)
panel = store.to_cross_sectional_dataframe(
    [Symbol("600000")],
    [disclosed, captured],
    source="synthetic_archive",
    scope="consolidated_annual_CNY",
    field="roe",
)
# 第一行缺失，第二行为 12.5（百分数单位）。
```

选择同时要求 `available_at <= decision_time` 和 `captured_at <= decision_time`。现在回填的财报不会进入过去的决策截面。最新财报期优先，同期再选当时可见的修订；旧财报的晚到重述不会遮蔽较新的报告期。相同来源、口径内的版本冲突被拒绝，缺失因子保留为 NaN。

输入时间、来源和报表口径由调用者提供；这个选择器不能证明其真实性，也不是正式 PIT Dataset 的发布入口。不同币种、合并/母公司、季度/年度及指标定义应分开研究。

## 基准相对评价

[`evaluate_benchmark_relative`](../../analytics/benchmark_relative.py) 接受两条拥有完全相同、唯一且递增 `DatetimeIndex` 的简单期间收益率序列。拒绝自动截短、错位、缺失和非有限值。调用者应先统一币种、估值边界、分红、现金流和成本口径。

```python
import pandas as pd
from analytics.benchmark_relative import evaluate_benchmark_relative

dates = pd.date_range("2026-01-05", periods=4, freq="B")
metrics = evaluate_benchmark_relative(
    pd.Series([0.01, -0.02, 0.005, 0.008], index=dates),
    pd.Series([0.008, -0.01, 0.002, 0.003], index=dates),
    periods_per_year=252,
    risk_free_rate=0.0,
)
print(metrics.to_json_dict())
```

`annualized_excess_return` 是平均期间主动收益乘以年化频率；跟踪误差是主动收益样本标准差乘以频率平方根。信息比率以这两个量相除。相对回撤从初始值 1 开始，使用组合累计财富与基准累计财富的比值。CAPM 输出 OLS beta 和线性年化截距，常数无风险利率按有效年率换算。

`periods_per_year` 是明确的采样假设；模块不验证交易日历，也不自动处理外部现金流。样本不足或指标未定义时返回 `None`，不填入零或默认 beta。四期示例只展示 API，不能说明策略有效。

## 已有人工订单的 CSV 复核

将本地服务 `GET /api/trading/orders` 返回的 JSON 数组保存为私有文件后，在源码目录运行：

```bash
python -m tools.export_basket --input orders.json --output order-review.csv
```

该接口返回最近的有限条记录（当前默认最多 50 条）；导出只涵盖输入快照，不表示账户的全部订单。输入使用当前 API 的 `quantity_decimal`、`price_decimal` 和 `decimal_provenance` 字段，缺失或冲突时拒绝输出。旧 REAL 回填记录保留原有精度限制。

导出保留已有订单 ID、时间、买卖方向、精确数量与价格、币种、意图/风险决策引用和确认状态。市价单缺价格时留空，不补默认价格，不按目标权重计算新委托，不重新取整。CSV 每行标注 `review_only`，危险公式文本会转义。整个输入验证成功后才创建文件，已有文件不会被覆盖。

CSV 用于复核保存的快照；它不证明订单仍然有效，不确认或提交订单，也不提供未经验证的 QMT/PTrade 导入格式。人工订单状态仍由既有交易流程管理。真实订单文件和导出结果应保留在私有目录，不提交到仓库。
