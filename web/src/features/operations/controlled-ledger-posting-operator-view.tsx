import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import type { ControlledLedgerPostingOperatorController } from './controlled-ledger-posting-operator-controller';
import {
  mutationError,
  shortenedIdentity,
} from './controlled-operation-panel-primitives';

interface PostingViewProps {
  controller: ControlledLedgerPostingOperatorController;
}

export function ControlledLedgerPostingOperatorView({
  controller,
}: PostingViewProps) {
  if (!controller.actionable) {
    return null;
  }
  return (
    <div className="mt-3 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-3">
      {!controller.open ? (
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold"
          onClick={controller.openPanel}
        >
          {controller.locale === 'zh'
            ? '复核签名式账本入账'
            : 'Review signed ledger posting'}
        </button>
      ) : (
        <section
          aria-label={
            controller.locale === 'zh'
              ? '签名式账本入账复核'
              : 'Signed ledger posting review'
          }
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] p-3"
        >
          <PostingHeader controller={controller} />
          <PostingPreview controller={controller} />
          <PostingSignature controller={controller} />
          <PostingFinalConfirmation controller={controller} />
        </section>
      )}
    </div>
  );
}

function PostingHeader({ controller }: PostingViewProps) {
  const { locale, journey, clearanceId, preview } = controller;
  return (
    <>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '终态成交 → 生产账本'
              : 'Terminal fills → production ledger'}
          </div>
          <div className="app-muted mt-1 break-words text-xs leading-5">
            {locale === 'zh'
              ? '这是独立的最终人工步骤，会按预览一次性写入已对账成交；不会提交或撤销券商订单。'
              : 'This separate final human step atomically posts the exact reconciled fills once. It cannot submit or cancel a broker order.'}
          </div>
        </div>
        <button
          type="button"
          className="app-button-secondary min-h-8 rounded-xl px-3 py-1.5 text-xs font-semibold"
          onClick={controller.close}
        >
          {locale === 'zh' ? '关闭' : 'Close'}
        </button>
      </div>
      <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2">
        <div className="min-w-0 break-words">
          {locale === 'zh' ? '订单' : 'Order'}: {journey.order_id || '—'}
        </div>
        <div className="min-w-0 break-words font-mono">
          clearance: {shortenedIdentity(clearanceId)}
        </div>
      </div>
      <button
        type="button"
        className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={preview.isPending}
        onClick={controller.loadPreview}
      >
        {preview.isPending
          ? locale === 'zh'
            ? '生成中'
            : 'Loading'
          : locale === 'zh'
            ? '生成只读入账预览'
            : 'Generate read-only posting preview'}
      </button>
      {preview.isError ? (
        <div
          role="alert"
          className="mt-3 break-words text-xs text-[var(--app-danger)]"
        >
          {mutationError(preview.error)}
        </div>
      ) : null}
    </>
  );
}

function PostingPreview({ controller }: PostingViewProps) {
  const { locale, preview } = controller;
  if (!preview.data) {
    return null;
  }
  return (
    <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {locale === 'zh' ? '确定性变更预览' : 'Deterministic delta preview'}
        </div>
        <span className="app-chip">
          {formatPublicStatus(preview.data.review_status, locale)}
        </span>
      </div>
      <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
        <div>
          {locale === 'zh' ? '终态' : 'Terminal'}:{' '}
          {formatPublicStatus(preview.data.terminal_status, locale)}
        </div>
        <div className="font-mono tabular-nums">
          {locale === 'zh' ? '账本事件' : 'Ledger events'}:{' '}
          {preview.data.ledger_entry_count}
        </div>
        <div className="font-mono tabular-nums">
          ledger cutoff #{preview.data.pre_ledger_cutoff_id}
        </div>
        <div
          className="min-w-0 truncate"
          title={preview.data.pre_valuation_snapshot_id}
        >
          valuation: {shortenedIdentity(preview.data.pre_valuation_snapshot_id)}
        </div>
        <div
          className="min-w-0 truncate"
          title={preview.data.account_truth_import_run_id}
        >
          Account Truth:{' '}
          {shortenedIdentity(preview.data.account_truth_import_run_id)}
        </div>
        <div
          className="min-w-0 truncate"
          title={preview.data.posting_fingerprint}
        >
          fingerprint: {shortenedIdentity(preview.data.posting_fingerprint)}
        </div>
      </div>
      {preview.data.ledger_entries.length ? (
        <div className="mt-3 grid min-w-0 gap-2">
          {preview.data.ledger_entries.map((entry) => (
            <div
              className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2"
              key={`${entry.fill_id}:${entry.broker_event_id}`}
            >
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="font-semibold text-[var(--app-text)]">
                  {entry.symbol} · {formatPublicStatus(entry.direction, locale)}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(entry.settlement_status, locale)}
                </span>
              </div>
              <div className="app-type-micro mt-2 grid min-w-0 gap-1 font-mono tabular-nums sm:grid-cols-2 xl:grid-cols-4">
                <div>
                  {locale === 'zh' ? '数量' : 'Quantity'} {entry.quantity}
                </div>
                <div>
                  {locale === 'zh' ? '成交价' : 'Price'} {entry.price}
                </div>
                <div>
                  {locale === 'zh' ? '成交额' : 'Gross'} {entry.gross_amount}
                </div>
                <div>
                  {locale === 'zh' ? '总费用' : 'Total fees'}{' '}
                  {entry.fee_breakdown.total_fee}
                </div>
                <div>
                  {locale === 'zh' ? '净现金影响' : 'Net cash impact'}{' '}
                  {entry.net_cash_impact}
                </div>
                <div className="min-w-0 truncate" title={entry.fill_id}>
                  fill: {shortenedIdentity(entry.fill_id)}
                </div>
                <div className="min-w-0 truncate" title={entry.broker_event_id}>
                  event: {shortenedIdentity(entry.broker_event_id)}
                </div>
                <div>{entry.timestamp || '—'}</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="app-muted mt-3 text-xs">
          {locale === 'zh'
            ? '零成交撤单：本次 posting 为显式零账本事件。'
            : 'Zero-fill cancellation: this posting has an explicit zero ledger-event delta.'}
        </div>
      )}
      {preview.data.blockers.length ? (
        <div
          role="alert"
          className="mt-3 break-words text-xs text-[var(--app-danger)]"
        >
          {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
          {preview.data.blockers
            .map((item) => formatPublicCode(item, locale))
            .join(' · ')}
        </div>
      ) : null}
    </div>
  );
}

function PostingSignature({ controller }: PostingViewProps) {
  const {
    locale,
    preview,
    approvalStatus,
    eligibleIdentities,
    effectiveKeyId,
    selectedIdentity,
    challenge,
    signature,
    verification,
  } = controller;
  if (!preview.data?.review_ready) {
    return null;
  }
  return (
    <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {locale === 'zh' ? '短时离线签名' : 'Short-lived offline signature'}
      </div>
      <div className="app-muted mt-1 text-xs leading-5">
        {locale === 'zh'
          ? 'Karkinos 只保存公钥。私钥不得粘贴或上传；请在独立本地签名器中签署下方 Base64 payload，然后只粘贴 detached signature。'
          : 'Karkinos stores public keys only. Never paste or upload a private key; sign the Base64 payload in a separate local signer and paste only the detached signature.'}
      </div>
      {approvalStatus.isLoading ? (
        <div className="app-muted mt-3 text-xs">
          {locale === 'zh' ? '读取可信身份…' : 'Loading trusted identities…'}
        </div>
      ) : null}
      {approvalStatus.isError ? (
        <div
          role="alert"
          className="mt-3 break-words text-xs text-[var(--app-danger)]"
        >
          {mutationError(approvalStatus.error)}
        </div>
      ) : null}
      {!approvalStatus.isLoading && eligibleIdentities.length === 0 ? (
        <div
          role="status"
          className="mt-3 break-words text-xs text-[var(--app-warning)]"
        >
          {locale === 'zh'
            ? '没有与该 clearance 操作员匹配的已启用 Ed25519 公钥；入账保持禁用。'
            : 'No enabled Ed25519 public key matches the clearance operator; posting remains disabled.'}
        </div>
      ) : null}
      {eligibleIdentities.length ? (
        <label className="mt-3 block min-w-0 text-xs font-semibold text-[var(--app-text)]">
          {locale === 'zh' ? '可信操作员身份' : 'Trusted operator identity'}
          <select
            className="app-input mt-1 min-h-10 w-full rounded-xl px-3 py-2 text-sm"
            aria-label={
              locale === 'zh' ? '可信操作员身份' : 'Trusted operator identity'
            }
            value={effectiveKeyId}
            onChange={(event) => controller.selectKey(event.target.value)}
          >
            {eligibleIdentities.map((identity) => (
              <option
                key={`${identity.operator_id}:${identity.key_id}`}
                value={identity.key_id}
              >
                {identity.operator_id} · {identity.key_id}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <button
        type="button"
        className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!selectedIdentity || challenge.isPending}
        onClick={controller.createChallenge}
      >
        {challenge.isPending
          ? locale === 'zh'
            ? '创建中'
            : 'Creating'
          : locale === 'zh'
            ? '创建 3 分钟签名挑战'
            : 'Create 3-minute signing challenge'}
      </button>
      {challenge.isError ? (
        <div
          role="alert"
          className="mt-3 break-words text-xs text-[var(--app-danger)]"
        >
          {mutationError(challenge.error)}
        </div>
      ) : null}
      {challenge.data ? (
        <div className="mt-3 min-w-0">
          <label className="block text-xs font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '待签 payload（Base64）'
              : 'Payload to sign (Base64)'}
            <textarea
              className="app-input mt-1 min-h-24 w-full resize-y rounded-xl px-3 py-2 font-mono text-xs"
              aria-label={
                locale === 'zh'
                  ? '待签 payload Base64'
                  : 'Payload to sign Base64'
              }
              readOnly
              value={challenge.data.signing_payload_base64}
            />
          </label>
          <div className="app-muted mt-1 text-xs">
            {locale === 'zh' ? '到期' : 'Expires'}: {challenge.data.expires_at}
          </div>
          <label className="mt-3 block text-xs font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? 'Detached signature（Base64）'
              : 'Detached signature (Base64)'}
            <input
              className="app-input mt-1 min-h-10 w-full rounded-xl px-3 py-2 font-mono text-sm"
              aria-label={
                locale === 'zh'
                  ? 'Detached signature Base64'
                  : 'Detached signature Base64'
              }
              autoComplete="off"
              spellCheck={false}
              type="password"
              value={signature}
              onChange={(event) =>
                controller.updateSignature(event.target.value)
              }
            />
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={signature.trim().length < 80 || verification.isPending}
            onClick={controller.verifySignature}
          >
            {verification.isPending
              ? locale === 'zh'
                ? '验证中'
                : 'Verifying'
              : locale === 'zh'
                ? '验证签名'
                : 'Verify signature'}
          </button>
          {verification.isError ? (
            <div
              role="alert"
              className="mt-3 break-words text-xs text-[var(--app-danger)]"
            >
              {mutationError(verification.error)}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PostingFinalConfirmation({ controller }: PostingViewProps) {
  const { locale, verification, acknowledged, preview, applyPosting } =
    controller;
  if (!verification.data) {
    return null;
  }
  return (
    <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_6%,transparent)] p-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {locale === 'zh' ? '最终应用确认' : 'Final apply confirmation'}
      </div>
      <div className="app-muted mt-1 text-xs leading-5">
        {locale === 'zh'
          ? '应用时会在同一数据库事务内重新核验 clearance、Account Truth、valuation snapshot、ledger cutoff/fingerprint 和签名。重复点击不会重复入账。'
          : 'Apply rechecks the clearance, Account Truth, valuation snapshot, ledger cutoff/fingerprint, and signature inside one database transaction. Duplicate clicks cannot post twice.'}
      </div>
      <label className="mt-3 flex min-w-0 items-start gap-2 text-xs font-semibold text-[var(--app-text)]">
        <input
          checked={acknowledged}
          className="mt-0.5"
          type="checkbox"
          onChange={(event) => controller.setAcknowledged(event.target.checked)}
        />
        <span>
          {locale === 'zh'
            ? `我确认仅将预览中的 ${preview.data?.ledger_entry_count ?? 0} 条已对账账本事件应用一次。`
            : `I confirm applying only the ${preview.data?.ledger_entry_count ?? 0} previewed reconciled ledger event(s), once.`}
        </span>
      </label>
      <button
        type="button"
        className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl border-[var(--app-danger)] px-3 py-2 text-xs font-semibold text-[var(--app-danger)] disabled:cursor-not-allowed disabled:opacity-50"
        disabled={
          !acknowledged || applyPosting.isPending || applyPosting.isSuccess
        }
        onClick={controller.apply}
      >
        {applyPosting.isPending
          ? locale === 'zh'
            ? '事务核验并应用中'
            : 'Rechecking and applying'
          : locale === 'zh'
            ? '应用精确已对账入账'
            : 'Apply exact reconciled posting'}
      </button>
      {applyPosting.isError ? (
        <div
          role="alert"
          className="mt-3 break-words text-xs text-[var(--app-danger)]"
        >
          {mutationError(applyPosting.error)}
        </div>
      ) : null}
      {applyPosting.data ? (
        <div
          role="status"
          className="mt-3 break-words text-xs font-semibold text-[var(--app-success)]"
        >
          {locale === 'zh'
            ? `入账已记录：ledger cutoff #${applyPosting.data.post_ledger_cutoff_id}；下一步复核 Account Truth。`
            : `Posting recorded at ledger cutoff #${applyPosting.data.post_ledger_cutoff_id}; review Account Truth next.`}
        </div>
      ) : null}
    </div>
  );
}
