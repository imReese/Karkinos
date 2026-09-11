# Account Truth 本地导入

> Status: maintenance-only.

## 边界

- Preview/import 不直接写生产账本、修改持仓或创建订单。
- 外部来源先标准化、验证、识别，再进入 staged evidence。
- 不完整、冲突或范围不明确的来源保持 blocked。
- Account Truth evidence 不授予 Execution 或 capital authority。
- 金融状态变化必须经过 Accounting / Reconciliation 边界。
- 不通过差额、猜测或读时修复补造金融事实。

## 输入

### Broker statement CSV

通过 `config.json` 显式启用本地 collector。配置见 [configuration.md](configuration.md)。

拒绝：

```text
missing file
file still changing
unsupported schema
size limit exceeded
invalid or incomplete statement
```

### 中信历史 XLS

Legacy `.xls` 支持隐私最小化 preview。历史成交记录不能单独证明完整现金、持仓、费用或查询范围。

### Legacy QMT lifecycle

保留旧 lifecycle compatibility。重新扩展 broker integration 前按 [ARCHITECTURE.md](../ARCHITECTURE.md) 的 Execution / Accounting 边界重新审查。

## 流程

```text
local source
-> preview / validate
-> staged evidence
-> human review
-> reconciliation
-> explicit canonical apply (if supported)
```

## 隐私

- 真实来源文件仅放本地运行目录。
- 测试和文档使用脱敏或合成数据。
- 不提交券商账号、密码、截图或真实导出。
- API/UI 优先暴露状态、计数、脱敏 identity 和 blocker。

## Scope

只维护现有兼容与安全修复。当前范围见 [PLAN.md](../PLAN.md)。
