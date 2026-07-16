# 操作员批准的离线签名

[English](operator-approval-signing.md) | [受控执行](CONTROLLED_EXECUTION_PLAN.zh.md) | [配置参考](config-reference.zh.md)

Karkinos 使用短时 Ed25519 approval 核验精确的受控执行 artifact。系统只保存公钥；私钥始终留在
操作员指定的本地文件，不进入 `config.json`、数据库、浏览器或 API 请求。

这份 approval 只证明一个可信操作员复核了一个精确 artifact。它不会签发 broker、OMS、risk、
kill switch、AI、strategy 或 capital authority。

## 配置一个本地身份

选择仓库之外的私钥路径：

```bash
uv run python scripts/operator_signer.py init \
  --private-key ~/.config/karkinos/operator-owner.pem \
  --operator-id local-owner \
  --key-id owner-key-1
```

命令拒绝覆盖已有密钥，以 `0600` 权限创建私钥文件，并输出只包含原始公钥的
`trusted_operator_identities` JSON 片段。将该顶层片段合并到本机且被 Git 忽略的
`config.json`，然后执行：

```bash
uv run python -m server --check-config
```

不要提交私钥、本地配置或真实 approval evidence。应使用所有者既有的加密秘密备份流程备份私钥。
禁用或移除对应公钥身份会阻止新的 approval，但不会删除审计历史。

## 完成账本入账复核

只有 canonical 下一步为 `preview_reconciled_ledger_posting` 时，Operations/Decision 的受控订单
证据旅程才显示该操作：

1. 打开“复核签名式账本入账”。
2. 生成只读预览，核对终态、精确账本事件数、Account Truth import、valuation snapshot、
   ledger cutoff 和 fingerprint；任一 blocker 都会停止流程。
3. 为匹配的可信身份创建三分钟 challenge。
4. 复制页面显示的 Base64 signing payload。
5. 运行签名器，只把该 payload 粘贴到 stdin，然后结束 stdin（macOS/Linux 使用 `Ctrl-D`）：

   ```bash
   uv run python scripts/operator_signer.py sign \
     --private-key ~/.config/karkinos/operator-owner.pem \
     --operator-id local-owner \
     --key-id owner-key-1 \
     --expected-action post_controlled_submission_ledger \
     --expected-artifact-type controlled_submission_ledger_posting
   ```

   只有 canonical JSON、domain、operator/key、公钥 fingerprint、allowlisted action/artifact 配对、
   有效期以及“不签发 authority”声明全部匹配时，签名器才会继续。
6. 将返回的 detached Base64 signature 粘贴到 Web 表单并验证；绝不能粘贴私钥。
7. 阅读并勾选最终确认，再将精确的已对账 posting 应用一次。
8. 在新 ledger cutoff 后复核 Account Truth。后续纠正是另一份独立签名的补偿操作，绝不删除原始
   事实。

若 challenge 到期、证据漂移、ledger cutoff 变化、Account Truth import 过期，或服务在 apply 前
重启，应丢弃旧签名，重新生成 preview 和 challenge。写事务会复核所有绑定 identity；重复 apply
只会复用已存在的精确 posting，不会产生第二次账本影响。

## 安全属性

- Preview 只读持久化事实，不联系 provider。
- 签名器不执行网络 I/O，也不修改 Karkinos 配置或数据库。
- 浏览器只接收短时 payload 与 detached signature，永远不接收私钥。
- 最终 apply 不能提交或撤销订单，也不能扩大或恢复执行/资本权限。
- 没有可信公钥身份时，该操作保持禁用。
