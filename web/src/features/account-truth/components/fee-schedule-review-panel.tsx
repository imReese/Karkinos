import { useState, type FormEvent } from 'react';

import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge,
  type StatusTone,
} from '../../../shared/ui/workbench';
import type { Locale } from '../../../shared/preferences/context';
import { formatDateTime } from '../../../shared/format';
import { formatPublicCode } from '../../../shared/public-labels';
import {
  REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
  useReviewedFeeScheduleApprovalMutation,
  useReviewedFeeSchedulePreviewMutation,
  useReviewedFeeScheduleReviewQuery,
  useReviewedFeeScheduleRevocationMutation,
  type AccountTruthEvidenceReadiness,
  type ReviewedFeeSchedulePreview,
} from '../api';

const copy = {
  en: {
    kicker: 'Account-bound research cost',
    title: 'Reviewed fee schedule',
    detail:
      'Compare stock fees with persisted stock buy and sell settlement components before they can become the only eligible daily-candidate research cost model. ETF and fund trades stay in Account Truth but are excluded from this strategy scope.',
    boundary:
      'This review is append-only and revocable. It cannot place an order, register a production strategy, or change capital authority.',
    current: 'Current review',
    statusMissing: 'Missing',
    statusActive: 'Active for research',
    statusBlocked: 'Blocked',
    statusRevoked: 'Revoked',
    noReview: 'No reviewed fee schedule',
    noReviewDetail:
      'Research, promotion, and manual order-ticket generation remain no-action until a current preview passes and a human accepts its exact fingerprint.',
    currentBlocked: 'Stored acceptance is currently blocked',
    currentBlockedDetail:
      'The accepted record remains auditable, but current Account Truth or fee evidence no longer matches it. Downstream use is denied.',
    currentActive: 'Current review is active for research',
    currentActiveDetail:
      'Downstream consumers still recheck this exact review, evidence binding, covered dates, and source drift before every use.',
    currentRevoked: 'Review revoked',
    currentRevokedDetail:
      'The recorded fee schedule is no longer eligible for research, promotion, or tickets.',
    unavailable: 'Reviewed fee schedule evidence is unavailable',
    unavailableDetail:
      'Preview, acceptance, and revocation remain disabled until the persisted review can be read.',
    effectiveWindow: 'Evidence window',
    startDate: 'Effective start date',
    endDate: 'Effective end date',
    preview: 'Recompute preview',
    previewing: 'Recomputing…',
    invalidWindow: 'Choose a valid start and end date.',
    previewReady: 'Exact fee evidence matches',
    previewBlocked: 'Fee evidence remains blocked',
    previewFailed: 'Fee preview failed closed',
    trades: 'Persisted trades',
    matched: 'Component matches',
    buys: 'Buys',
    sells: 'Sells',
    tolerance: 'Tolerance',
    reviewedScope: 'Daily-candidate fee scope: stocks only',
    excludedTrades: 'Out-of-scope ETF/fund trades excluded',
    stockTerms: 'Stock commission',
    sellTax: 'Sell stamp tax',
    stockTransfer: 'Stock transfer fee',
    mismatchBreakdown: 'Mismatch breakdown by asset and side',
    feeMismatch: 'fee',
    taxMismatch: 'tax',
    transferMismatch: 'transfer',
    min: 'minimum',
    reviewer: 'Reviewer',
    approval: 'Accept exact preview for research only',
    approvalDetail:
      'Type the exact confirmation phrase and reviewer identity. The server recomputes the preview and rejects stale fingerprints.',
    confirmation: 'Exact approval confirmation',
    approve: 'Accept reviewed fee schedule',
    approving: 'Accepting…',
    approved: 'Review recorded. Current evidence is rechecked before use.',
    approvalFailed: 'Acceptance failed closed. Recompute and review again.',
    revoke: 'Revoke this exact review',
    revokeDetail:
      'Revocation immediately makes the review ineligible. It does not alter Account Truth, ledger facts, orders, or capital authority.',
    revocationConfirmation: 'Exact revocation confirmation',
    revokeAction: 'Revoke reviewed fee schedule',
    revoking: 'Revoking…',
    revoked: 'Review revoked. Downstream use is denied.',
    revocationFailed: 'Revocation failed closed. Refresh the current review.',
    reviewIdentity: 'Review identity',
    previewIdentity: 'Preview fingerprint',
    scheduleIdentity: 'Schedule fingerprint',
    recordedAt: 'Recorded',
    issues: 'Blocking evidence',
  },
  zh: {
    kicker: '账户绑定的研究成本',
    title: '经审查费率表',
    detail:
      '仅将股票费率与已持久化的股票买卖结算分项逐项比较，通过后才可成为每日候选策略唯一合格的研究成本模型。ETF/基金仍保留在 Account Truth，但排除在策略范围外。',
    boundary: '该审查仅追加、可撤销；不能下单、注册生产策略或改变资金额度。',
    current: '当前审查',
    statusMissing: '缺失',
    statusActive: '仅研究可用',
    statusBlocked: '已阻断',
    statusRevoked: '已撤销',
    noReview: '尚无经审查费率表',
    noReviewDetail:
      '在当前预览通过且人工接受其精确指纹前，研究、晋级和人工订单票据均保持 no-action。',
    currentBlocked: '已接受记录当前被阻断',
    currentBlockedDetail:
      '原记录仍可审计，但当前 Account Truth 或费率证据已不再匹配，下游使用被拒绝。',
    currentActive: '当前审查可用于研究',
    currentActiveDetail:
      '每次使用前，下游仍会复核该精确审查、证据绑定、覆盖日期和来源漂移。',
    currentRevoked: '审查已撤销',
    currentRevokedDetail: '该费率表不再可用于研究、晋级或订单票据。',
    unavailable: '经审查费率证据不可用',
    unavailableDetail: '恢复读取已持久化审查前，预览、接受和撤销均保持禁用。',
    effectiveWindow: '证据窗口',
    startDate: '生效开始日期',
    endDate: '生效结束日期',
    preview: '重新计算预览',
    previewing: '正在重算…',
    invalidWindow: '请选择有效的开始和结束日期。',
    previewReady: '精确费率证据匹配',
    previewBlocked: '费率证据仍被阻断',
    previewFailed: '费率预览已 fail-closed',
    trades: '已持久化成交',
    matched: '分项匹配',
    buys: '买入',
    sells: '卖出',
    tolerance: '容差',
    reviewedScope: '每日候选费用范围：仅股票',
    excludedTrades: '已排除范围外 ETF/基金成交',
    stockTerms: '股票佣金',
    sellTax: '卖出印花税',
    stockTransfer: '股票过户费',
    mismatchBreakdown: '按资产与方向拆分的差异',
    feeMismatch: '佣金',
    taxMismatch: '税费',
    transferMismatch: '过户费',
    min: '最低',
    reviewer: '复核人',
    approval: '仅为研究接受该精确预览',
    approvalDetail:
      '输入完整确认短语和复核人身份；服务端会重新计算预览，并拒绝过期指纹。',
    confirmation: '完整接受确认短语',
    approve: '接受经审查费率表',
    approving: '正在接受…',
    approved: '审查已记录；每次使用前仍会复核当前证据。',
    approvalFailed: '接受已 fail-closed，请重新计算并复核。',
    revoke: '撤销该精确审查',
    revokeDetail:
      '撤销会立即使审查失去资格，但不会改动 Account Truth、账本事实、订单或资金额度。',
    revocationConfirmation: '完整撤销确认短语',
    revokeAction: '撤销经审查费率表',
    revoking: '正在撤销…',
    revoked: '审查已撤销，下游使用被拒绝。',
    revocationFailed: '撤销已 fail-closed，请刷新当前审查。',
    reviewIdentity: '审查身份',
    previewIdentity: '预览指纹',
    scheduleIdentity: '费率表指纹',
    recordedAt: '记录时间',
    issues: '阻断证据',
  },
};

const inputClass =
  'min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]';

const DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES: ['stock'] = ['stock'];

const feeScheduleIssueLabels: Record<string, { en: string; zh: string }> = {
  reviewed_fee_schedule_account_truth_not_ready: {
    en: 'Account Truth is not ready',
    zh: 'Account Truth 尚未就绪',
  },
  reviewed_fee_schedule_account_truth_promotion_blocked: {
    en: 'Account Truth promotion evidence is blocked',
    zh: 'Account Truth 晋级证据被阻断',
  },
  reviewed_fee_schedule_component_mismatch: {
    en: 'Reviewed fee schedule component mismatch',
    zh: '经审查费率分项不匹配',
  },
  reviewed_fee_schedule_buy_coverage_missing: {
    en: 'Persisted buy coverage is missing',
    zh: '缺少已持久化买入覆盖',
  },
  reviewed_fee_schedule_sell_coverage_missing: {
    en: 'Persisted sell coverage is missing',
    zh: '缺少已持久化卖出覆盖',
  },
  reviewed_fee_schedule_source_drift: {
    en: 'Reviewed Account Truth source has drifted',
    zh: '已审查 Account Truth 来源发生漂移',
  },
};

function formatFeeScheduleIssue(issue: string, locale: Locale) {
  return (
    feeScheduleIssueLabels[issue]?.[locale] ?? formatPublicCode(issue, locale)
  );
}

function reviewTone(status: string): StatusTone {
  if (status === 'active' || status === 'ready' || status === 'pass') {
    return 'success';
  }
  if (status === 'missing' || status === 'blocked') return 'warning';
  if (status === 'revoked') return 'danger';
  return 'neutral';
}

function reviewStatusLabel(
  status: 'missing' | 'active' | 'blocked' | 'revoked',
  locale: Locale,
) {
  const text = copy[locale];
  return {
    missing: text.statusMissing,
    active: text.statusActive,
    blocked: text.statusBlocked,
    revoked: text.statusRevoked,
  }[status];
}

function PreviewSummary({
  locale,
  preview,
}: {
  locale: Locale;
  preview: ReviewedFeeSchedulePreview;
}) {
  const text = copy[locale];
  const components = preview.component_reconciliation;
  const schedule = preview.schedule;
  return (
    <div
      className="mt-4 border-y border-[var(--app-divider)] py-3"
      data-testid="fee-schedule-preview-summary"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="app-type-subsection-title text-[var(--app-text)]">
          {preview.status === 'ready' ? text.previewReady : text.previewBlocked}
        </h3>
        <StatusBadge tone={reviewTone(preview.status)}>
          {formatPublicCode(preview.status, locale)}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs font-semibold text-[var(--app-text-secondary)]">
        {text.reviewedScope} · {text.excludedTrades}:{' '}
        {components.excluded_trade_count ?? 0}
      </p>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-5">
        {[
          [text.trades, String(components.trade_count)],
          [text.matched, String(components.matched_trade_count)],
          [text.buys, String(components.side_counts.buy)],
          [text.sells, String(components.side_counts.sell)],
          [text.tolerance, components.tolerance],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-[var(--app-text-tertiary)]">{label}</dt>
            <dd className="mt-0.5 font-mono font-semibold text-[var(--app-text)]">
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <dl className="mt-3 grid gap-2 border-t border-[var(--app-divider)] pt-3 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-[var(--app-text-tertiary)]">{text.stockTerms}</dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.stock_a_commission_rate} · {text.min}{' '}
            {schedule.stock_a_min_commission}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--app-text-tertiary)]">{text.sellTax}</dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.stamp_tax_rate}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--app-text-tertiary)]">
            {text.stockTransfer}
          </dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.transfer_fee_rate}
          </dd>
        </div>
      </dl>
      {components.mismatch_counts_by_asset_and_side.length > 0 ? (
        <div
          className="mt-3 border-t border-[var(--app-divider)] pt-3"
          data-testid="fee-schedule-mismatch-breakdown"
        >
          <div className="text-xs font-semibold text-[var(--app-text)]">
            {text.mismatchBreakdown}
          </div>
          <ul className="mt-1 space-y-1 text-xs text-[var(--app-text-secondary)]">
            {components.mismatch_counts_by_asset_and_side.map((item) => (
              <li key={`${item.asset_class}:${item.side}`}>
                <span className="font-mono font-semibold text-[var(--app-text)]">
                  {formatPublicCode(item.asset_class, locale)} ·{' '}
                  {formatPublicCode(item.side, locale)}
                </span>{' '}
                — {text.feeMismatch} {item.fee} · {text.taxMismatch} {item.tax}{' '}
                · {text.transferMismatch} {item.transfer_fee}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="app-type-micro mt-3 font-mono leading-5 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
        {text.previewIdentity}: {preview.preview_fingerprint}
      </p>
      {preview.issues.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold text-[var(--app-danger)]">
            {text.issues}
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-[var(--app-text-secondary)]">
            {preview.issues.map((issue) => (
              <li key={issue}>{formatFeeScheduleIssue(issue, locale)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function FeeScheduleReviewPanel({
  locale,
  readiness,
}: {
  locale: Locale;
  readiness: AccountTruthEvidenceReadiness;
}) {
  const text = copy[locale];
  const reviewedWindow = readiness.evidence_scope.declared_coverage_window;
  const [startDate, setStartDate] = useState(reviewedWindow.start_date ?? '');
  const [endDate, setEndDate] = useState(reviewedWindow.end_date ?? '');
  const [reviewer, setReviewer] = useState('');
  const [approvalConfirmation, setApprovalConfirmation] = useState('');
  const [revocationConfirmation, setRevocationConfirmation] = useState('');
  const reviewQuery = useReviewedFeeScheduleReviewQuery();
  const previewMutation = useReviewedFeeSchedulePreviewMutation();
  const approvalMutation = useReviewedFeeScheduleApprovalMutation();
  const revocationMutation = useReviewedFeeScheduleRevocationMutation();
  const current = reviewQuery.data;
  const currentReview = current?.review ?? null;
  const windowValid = Boolean(startDate && endDate && startDate <= endDate);
  const previewIsCurrent = Boolean(
    previewMutation.data &&
    previewMutation.data.effective_start_date === startDate &&
    previewMutation.data.effective_end_date === endDate,
  );
  const previewCanBeAccepted = Boolean(
    previewMutation.data?.status === 'ready' &&
    previewIsCurrent &&
    reviewer.trim() &&
    approvalConfirmation === REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION &&
    !reviewQuery.isError &&
    !reviewQuery.isLoading &&
    !approvalMutation.isPending,
  );
  const reviewIsRevocable = currentReview?.decision === 'accepted';
  const canRevoke = Boolean(
    reviewIsRevocable &&
    reviewer.trim() &&
    revocationConfirmation === REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION &&
    !reviewQuery.isError &&
    !revocationMutation.isPending,
  );

  const handlePreview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    approvalMutation.reset();
    if (!windowValid || reviewQuery.isError) return;
    previewMutation.mutate({
      effective_start_date: startDate,
      effective_end_date: endDate,
      reviewed_asset_classes: DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES,
    });
  };

  return (
    <section
      className="app-workbench-section min-w-0 px-1 py-4 sm:px-4"
      data-testid="account-truth-fee-schedule-review"
      id="account-truth-fee-schedule-review"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="app-product-mark">{text.kicker}</div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {text.title}
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {text.detail}
          </p>
        </div>
        <StatusBadge tone={reviewTone(current?.status ?? 'missing')}>
          {reviewStatusLabel(current?.status ?? 'missing', locale)}
        </StatusBadge>
      </div>

      {reviewQuery.isError ? (
        <EvidenceState
          className="mt-4"
          kind="error"
          title={text.unavailable}
          description={text.unavailableDetail}
        />
      ) : reviewQuery.isLoading ? (
        <EvidenceState className="mt-4" kind="loading" title={text.current} />
      ) : current?.status === 'active' ? (
        <EvidenceState
          className="mt-4"
          kind="ready"
          title={text.currentActive}
          description={text.currentActiveDetail}
        />
      ) : current?.status === 'blocked' ? (
        <EvidenceState
          className="mt-4"
          kind="partial"
          title={text.currentBlocked}
          description={text.currentBlockedDetail}
        />
      ) : current?.status === 'revoked' ? (
        <EvidenceState
          className="mt-4"
          kind="partial"
          title={text.currentRevoked}
          description={text.currentRevokedDetail}
        />
      ) : (
        <EvidenceState
          className="mt-4"
          kind="partial"
          title={text.noReview}
          description={text.noReviewDetail}
        />
      )}

      {currentReview ? (
        <dl className="mt-3 grid gap-2 border-y border-[var(--app-divider)] py-3 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-[var(--app-text-tertiary)]">
              {text.reviewIdentity}
            </dt>
            <dd className="mt-0.5 font-mono text-[var(--app-text)] [overflow-wrap:anywhere]">
              {currentReview.review_id} · {currentReview.review_fingerprint}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--app-text-tertiary)]">
              {text.recordedAt}
            </dt>
            <dd className="mt-0.5 text-[var(--app-text)]">
              {formatDateTime(currentReview.created_at)} ·{' '}
              {currentReview.reviewer}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--app-text-tertiary)]">
              {text.effectiveWindow}
            </dt>
            <dd className="mt-0.5 font-mono text-[var(--app-text)]">
              {currentReview.effective_start_date} –{' '}
              {currentReview.effective_end_date}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--app-text-tertiary)]">
              {text.scheduleIdentity}
            </dt>
            <dd className="mt-0.5 font-mono text-[var(--app-text)] [overflow-wrap:anywhere]">
              {currentReview.schedule_fingerprint}
            </dd>
          </div>
        </dl>
      ) : null}

      {(current?.blockers ?? []).length > 0 && current?.status === 'blocked' ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-[var(--app-danger)]">
          {current?.blockers.map((blocker) => (
            <li key={blocker}>{formatFeeScheduleIssue(blocker, locale)}</li>
          ))}
        </ul>
      ) : null}

      {revocationMutation.isSuccess ? (
        <EvidenceState className="mt-3" kind="ready" title={text.revoked} />
      ) : null}

      <form className="mt-4" onSubmit={handlePreview}>
        <fieldset
          className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
          disabled={reviewQuery.isError}
        >
          <legend className="sr-only">{text.effectiveWindow}</legend>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.startDate}
            <input
              className={inputClass}
              data-testid="fee-schedule-start-date"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.currentTarget.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.endDate}
            <input
              className={inputClass}
              data-testid="fee-schedule-end-date"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.currentTarget.value)}
            />
          </label>
          <button
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!windowValid || previewMutation.isPending}
            type="submit"
          >
            {previewMutation.isPending ? text.previewing : text.preview}
          </button>
        </fieldset>
      </form>
      {!windowValid ? (
        <p className="mt-2 text-xs text-[var(--app-danger)]">
          {text.invalidWindow}
        </p>
      ) : null}
      {previewMutation.data ? (
        <PreviewSummary locale={locale} preview={previewMutation.data} />
      ) : null}
      {previewMutation.isError ? (
        <EvidenceState
          className="mt-3"
          kind="error"
          title={text.previewFailed}
        />
      ) : null}

      {previewMutation.data?.status === 'ready' && previewIsCurrent ? (
        <ControlledActionZone
          className="mt-4"
          description={text.approvalDetail}
          evidence={REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION}
          layout="stack"
          title={text.approval}
          tone="info"
        >
          <div className="grid w-full gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.reviewer}
              <input
                autoComplete="off"
                className={inputClass}
                maxLength={128}
                value={reviewer}
                onChange={(event) => setReviewer(event.currentTarget.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.confirmation}
              <input
                autoComplete="off"
                className={inputClass}
                value={approvalConfirmation}
                onChange={(event) =>
                  setApprovalConfirmation(event.currentTarget.value)
                }
              />
            </label>
          </div>
          <button
            className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!previewCanBeAccepted}
            type="button"
            onClick={() => {
              const preview = previewMutation.data;
              if (!preview || !previewCanBeAccepted) return;
              approvalMutation.mutate(
                {
                  effective_start_date: startDate,
                  effective_end_date: endDate,
                  reviewed_asset_classes:
                    DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES,
                  expected_preview_fingerprint: preview.preview_fingerprint,
                  reviewer: reviewer.trim(),
                  confirmation: approvalConfirmation,
                },
                {
                  onSuccess: () => {
                    setApprovalConfirmation('');
                    previewMutation.reset();
                    revocationMutation.reset();
                  },
                },
              );
            }}
          >
            {approvalMutation.isPending ? text.approving : text.approve}
          </button>
          {approvalMutation.isSuccess ? (
            <p className="text-xs font-semibold text-[var(--app-success)]">
              {text.approved}
            </p>
          ) : null}
          {approvalMutation.isError ? (
            <p className="text-xs font-semibold text-[var(--app-danger)]">
              {text.approvalFailed}
            </p>
          ) : null}
        </ControlledActionZone>
      ) : null}

      {reviewIsRevocable && currentReview ? (
        <ControlledActionZone
          className="mt-4"
          description={text.revokeDetail}
          evidence={`${currentReview.review_id} · ${currentReview.review_fingerprint}`}
          layout="stack"
          title={text.revoke}
        >
          <div className="grid w-full gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.reviewer}
              <input
                autoComplete="off"
                className={inputClass}
                maxLength={128}
                value={reviewer}
                onChange={(event) => setReviewer(event.currentTarget.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.revocationConfirmation}
              <input
                autoComplete="off"
                className={inputClass}
                value={revocationConfirmation}
                onChange={(event) =>
                  setRevocationConfirmation(event.currentTarget.value)
                }
              />
            </label>
          </div>
          <button
            className="min-h-10 rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] px-4 text-xs font-semibold text-[var(--app-danger)] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canRevoke}
            type="button"
            onClick={() => {
              if (!canRevoke) return;
              revocationMutation.mutate(
                {
                  expected_review_id: currentReview.review_id,
                  expected_review_fingerprint: currentReview.review_fingerprint,
                  reviewer: reviewer.trim(),
                  confirmation: revocationConfirmation,
                },
                {
                  onSuccess: () => {
                    setApprovalConfirmation('');
                    setRevocationConfirmation('');
                    approvalMutation.reset();
                    previewMutation.reset();
                  },
                },
              );
            }}
          >
            {revocationMutation.isPending ? text.revoking : text.revokeAction}
          </button>
          {revocationMutation.isError ? (
            <p className="text-xs font-semibold text-[var(--app-danger)]">
              {text.revocationFailed}
            </p>
          ) : null}
        </ControlledActionZone>
      ) : null}

      <p className="mt-4 border-t border-[var(--app-divider)] pt-3 text-xs leading-5 text-[var(--app-text-tertiary)]">
        {text.boundary}
      </p>
    </section>
  );
}
