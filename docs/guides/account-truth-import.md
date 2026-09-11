# Account Truth 本地导入

> Status: maintenance-only compatibility guide.

Account Truth 现有导入能力用于把本地券商来源作为外部账户证据进行预览、验证和对账。它不属于当前开发主线。

## 边界

- 导入或预览本身不写生产账本、不修改持仓、不创建订单。
- 原始券商账号、密码、截图和真实导出不得进入源码仓库。
- 外部来源先标准化、验证和识别，再进入 staged evidence。
- 不完整、冲突或范围不明确的来源保持 blocked。
- Account Truth evidence 不授予 execution 或 capital authority。
- 任何实际金融状态变化必须经过 Accounting / Reconciliation 的明确边界。

## 当前输入

### Broker statement CSV

本地 CSV collector 可通过 `config.json` 显式启用。配置方式见
[configuration.md](configuration.md)。

Collector 只读取本地文件，并按现有校验和幂等规则处理。文件缺失、写入中、schema 不兼容或超限时保持失败状态，不应产生不完整账户事实。

### 中信历史 XLS

现有兼容路径支持对 legacy `.xls` 历史成交进行隐私最小化 preview。历史成交记录通常不能单独证明完整现金、持仓、费用和查询范围，因此不得通过差额或猜测补齐缺失金融事实。

### Legacy QMT lifecycle

仓库仍保留旧 QMT lifecycle 的兼容代码。重新启用或扩展真实 broker integration 前，需要重新按照
[ARCHITECTURE.md](../ARCHITECTURE.md) 的 Execution / Accounting 边界进行审查。

## 操作路径

```text
local source
-> preview / validate
-> staged evidence
-> human review
-> reconciliation
-> explicit canonical apply (if supported)
```

不要通过手工修改 SQLite 来完成导入或修复未知金融事实。

## 隐私

真实来源文件只应存在于本地运行目录。测试和文档使用脱敏或合成数据。

API 和 UI 应优先暴露状态、计数、脱敏 identity 和 blocker，而不是不必要的真实账号、文件路径或原始私有内容。

## 当前状态

现有安全和兼容行为可以维护和修复，但除非
[PLAN.md](../PLAN.md) 明确重新纳入范围，否则不扩展 Account Truth、broker 或资本权限功能。
