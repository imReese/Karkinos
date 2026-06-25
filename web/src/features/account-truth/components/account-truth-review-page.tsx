import { useEffect, useMemo, useState } from 'react';

import { usePreferences } from '../../../app/preferences';
import {
  formatCurrency,
  formatDateTime,
  formatQuantity,
} from '../../../shared/format';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicReviewActionLabel,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatLedgerEvidenceReference } from '../../../shared/ledger-format';
import {
  useAccountTruthImportRunsQuery,
  useAccountTruthScoreQuery,
  useReconciliationReportDetailQuery,
  useReconciliationReportsQuery,
  useRecordReviewDecisionMutation,
  type ReconciliationItem,
  type ReconciliationStatus,
  type ReviewStatus,
} from '../api';

type ReportFilter = ReconciliationStatus | 'all';

const filters: Array<{ value: ReportFilter; en: string; zh: string }> = [
  { value: 'all', en: 'All', zh: '全部' },
  { value: 'pass', en: 'Pass', zh: '通过' },
  { value: 'warning', en: 'Warning', zh: '警告' },
  { value: 'mismatch', en: 'Mismatch', zh: '不一致' },
  { value: 'blocked', en: 'Blocked', zh: '阻断' },
];

const reviewActions: ReviewStatus[] = [
  'accepted',
  'ignored',
  'known_difference',
  'ledger_candidate',
  'needs_investigation',
];

const labels = {
  en: {
    kicker: 'Account Truth',
    title: 'Account Truth Review Center',
    subtitle:
      'Review broker evidence, reconciliation gaps, and manual decisions before relying on account facts.',
    loading: 'Loading Account Truth evidence.',
    error: 'Failed to load Account Truth evidence.',
    score: 'Score',
    scorePending: 'Not ready',
    gate: 'Gate',
    unresolved: 'Unresolved',
    resolved: 'Resolved reviews',
    freshness: 'Freshness',
    components: 'Component reasons',
    blockingReasons: 'Blocking reasons',
    requiredActions: 'Required actions',
    imports: 'Import runs',
    reports: 'Reconciliation reports',
    detail: 'Report detail',
    rows: 'Rows',
    duplicates: 'duplicates',
    cashDifference: 'Cash difference',
    feeDifference: 'Fee difference',
    taxDifference: 'Tax difference',
    validation: 'Validation',
    source: 'Source',
    created: 'Created',
    limitations: 'Limitations',
    noImports: 'No staged broker evidence yet.',
    noReports: 'No reconciliation reports for this filter.',
    noItems: 'No reconciliation differences in this report.',
    notReadyTitle: 'Account facts are not ready',
    notReadyBody:
      'No broker statement, position snapshot, or cash snapshot has been staged yet.',
    workflowTitle: 'How to use this page',
    workflowSteps: [
      'Import broker evidence',
      'Run reconciliation against Karkinos ledger and positions',
      'Then return here to review differences',
    ],
    broker: 'Broker',
    karkinos: 'Karkinos',
    difference: 'Difference',
    suggestedAction: 'Suggested action',
    evidence: 'Evidence',
    latestReview: 'Latest review',
    reviewSaved: 'Review saved',
    reviewFailed: 'Review failed',
    safety:
      'Ledger candidate is an audit label only. It does not mutate the production ledger or submit broker orders.',
    componentLabels: {
      cash: 'Cash',
      position: 'Position',
      fee: 'Fee',
      costBasis: 'Cost basis',
    },
  },
  zh: {
    kicker: '账户事实',
    title: '账户事实复核中心',
    subtitle: '在依赖账户事实前，复核券商证据、对账差异和人工处理状态。',
    loading: '正在加载账户事实证据。',
    error: '账户事实证据加载失败。',
    score: '分数',
    scorePending: '待导入',
    gate: '闸门',
    unresolved: '未解决差异',
    resolved: '已复核',
    freshness: '新鲜度',
    components: '组件原因',
    blockingReasons: '阻断原因',
    requiredActions: '下一步动作',
    imports: '导入批次',
    reports: '对账报告',
    detail: '报告明细',
    rows: '行数',
    duplicates: '重复',
    cashDifference: '现金差异',
    feeDifference: '费用差异',
    taxDifference: '税费差异',
    validation: '校验',
    source: '来源',
    created: '创建时间',
    limitations: '限制',
    noImports: '还没有暂存的券商证据。',
    noReports: '当前筛选下没有对账报告。',
    noItems: '该报告没有对账差异。',
    notReadyTitle: '账户事实尚未建立',
    notReadyBody:
      '还没有暂存券商交割单、持仓快照或现金快照，暂时无法计算账户事实分。',
    workflowTitle: '这个页面怎么用',
    workflowSteps: [
      '先导入券商证据',
      '把券商证据与 Karkinos 账本和持仓做对账',
      '回到这里逐条复核差异',
    ],
    broker: '券商',
    karkinos: 'Karkinos',
    difference: '差异',
    suggestedAction: '建议动作',
    evidence: '证据',
    latestReview: '最近复核',
    reviewSaved: '复核已保存',
    reviewFailed: '复核保存失败',
    safety: '账本候选只是审计标签，不会修改生产账本，也不会提交券商订单。',
    componentLabels: {
      cash: '现金',
      position: '持仓',
      fee: '费用',
      costBasis: '成本价',
    },
  },
} as const;

const currencyReconciliationCategories = new Set([
  'cash',
  'fee',
  'tax',
  'trade_gross_amount',
  'net_cash_impact',
  'transfer_fee',
]);

function parseReconciliationNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '--') {
    return null;
  }
  const parsed = Number(trimmed.replace(/,/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatReconciliationValue(
  category: string,
  value: string,
  locale: 'en' | 'zh',
) {
  const parsed = parseReconciliationNumber(value);
  if (parsed === null) {
    return value || '--';
  }

  if (category === 'position') {
    return `${formatQuantity(parsed)} ${locale === 'zh' ? '股' : 'shares'}`;
  }

  if (category === 'cost_basis') {
    return formatCurrency(parsed, {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });
  }

  if (currencyReconciliationCategories.has(category)) {
    return formatCurrency(parsed);
  }

  return value;
}

export function AccountTruthReviewPage() {
  const { locale } = usePreferences();
  const text = labels[locale];
  const [filter, setFilter] = useState<ReportFilter>('all');
  const [selectedImportRunId, setSelectedImportRunId] = useState<string | null>(
    null,
  );
  const [savedReviewStatus, setSavedReviewStatus] =
    useState<ReviewStatus | null>(null);

  const score = useAccountTruthScoreQuery();
  const importRuns = useAccountTruthImportRunsQuery();
  const reports = useReconciliationReportsQuery(filter);
  const selectedReport = useMemo(
    () =>
      reports.data?.find(
        (report) => report.import_run_id === selectedImportRunId,
      ) ??
      reports.data?.[0] ??
      null,
    [reports.data, selectedImportRunId],
  );
  const detail = useReconciliationReportDetailQuery(
    selectedReport?.import_run_id ?? null,
  );
  const reviewMutation = useRecordReviewDecisionMutation();

  useEffect(() => {
    if (!reports.data?.length) {
      setSelectedImportRunId(null);
      return;
    }
    if (
      !selectedImportRunId ||
      !reports.data.some(
        (report) => report.import_run_id === selectedImportRunId,
      )
    ) {
      setSelectedImportRunId(reports.data[0].import_run_id);
    }
  }, [reports.data, selectedImportRunId]);

  const loading =
    score.isLoading ||
    importRuns.isLoading ||
    reports.isLoading ||
    detail.isLoading;
  const hasError =
    score.isError || importRuns.isError || reports.isError || detail.isError;
  const scoreData = score.data;
  const scoreIsMissing = scoreData?.status === 'missing';
  const componentEntries = [
    [text.componentLabels.cash, scoreData?.cash_status],
    [text.componentLabels.position, scoreData?.position_status],
    [text.componentLabels.fee, scoreData?.fee_status],
    [text.componentLabels.costBasis, scoreData?.cost_basis_status],
  ];

  return (
    <section className="mx-auto grid w-full max-w-[1440px] gap-5">
      <header className="grid gap-2">
        <div className="app-product-mark">{text.kicker}</div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <h1 className="text-3xl font-black tracking-normal text-[var(--app-text)]">
              {text.title}
            </h1>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {text.subtitle}
            </p>
          </div>
          <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_12%,transparent)] px-4 py-3 text-xs font-semibold text-[var(--app-warning)]">
            {text.safety}
          </div>
        </div>
      </header>

      {hasError ? (
        <div className="app-card p-5 text-sm font-semibold text-[var(--app-danger)]">
          {text.error}
        </div>
      ) : null}
      {loading ? (
        <div className="app-card p-5 text-sm font-semibold text-[var(--app-muted)]">
          {text.loading}
        </div>
      ) : null}

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(320px,0.82fr)_minmax(0,1.6fr)]">
        <div className="grid min-w-0 content-start gap-5">
          <section
            className="app-card min-w-0 p-5"
            data-testid="account-truth-score"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="app-product-mark">{text.score}</div>
                <div className="mt-2 text-4xl font-black tracking-normal text-[var(--app-text)]">
                  {scoreData?.score ?? text.scorePending}
                </div>
              </div>
              <StatusBadge
                status={scoreData?.gate_status ?? 'blocked'}
                locale={locale}
              />
            </div>
            {scoreIsMissing ? <MissingEvidenceCallout locale={locale} /> : null}
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Metric
                label={text.gate}
                value={formatCode(
                  scoreData?.gate_status ?? '--',
                  locale,
                  'status',
                )}
              />
              <Metric
                label={text.unresolved}
                value={String(scoreData?.unresolved_mismatch_count ?? '--')}
              />
              <Metric
                label={text.resolved}
                value={String(scoreData?.resolved_review_count ?? '--')}
              />
              <Metric
                label={text.freshness}
                value={formatCode(
                  scoreData?.data_freshness_status ?? '--',
                  locale,
                  'status',
                )}
              />
            </div>
            <div className="mt-5">
              <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
                {text.components}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {componentEntries.map(([label, value]) => (
                  <span
                    key={label}
                    className="rounded-full border border-[var(--app-border)] px-3 py-1 text-xs font-semibold text-[var(--app-muted)]"
                  >
                    {label}: {formatCode(value ?? '--', locale, 'status')}
                  </span>
                ))}
              </div>
            </div>
            <ReasonList
              title={text.blockingReasons}
              values={scoreData?.blocking_reasons ?? []}
              locale={locale}
            />
            <ReasonList
              title={text.requiredActions}
              values={scoreData?.required_actions ?? []}
              locale={locale}
            />
          </section>

          <section className="app-card min-w-0 p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="app-product-mark">{text.imports}</div>
                <h2 className="mt-1 text-lg font-black tracking-normal text-[var(--app-text)]">
                  {text.imports}
                </h2>
              </div>
            </div>
            <div className="grid gap-3">
              {(importRuns.data ?? []).length > 0 ? (
                importRuns.data?.map((run) => (
                  <button
                    key={run.import_run_id}
                    type="button"
                    className={`rounded-2xl border p-4 text-left transition ${
                      selectedReport?.import_run_id === run.import_run_id
                        ? 'border-[var(--app-accent)] bg-[var(--app-accent-ghost)]'
                        : 'border-[var(--app-border)] bg-[var(--app-surface-0)]'
                    }`}
                    onClick={() => setSelectedImportRunId(run.import_run_id)}
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <span className="truncate text-sm font-black text-[var(--app-text)]">
                        {run.source_name}
                      </span>
                      <StatusBadge
                        status={run.validation_status}
                        locale={locale}
                      />
                    </div>
                    <div className="mt-2 text-xs font-semibold text-[var(--app-muted)]">
                      {text.rows} {run.row_count} · {text.duplicates}{' '}
                      {run.row_duplicate_count + run.file_duplicate_count}
                    </div>
                    <div className="mt-2 text-xs text-[var(--app-muted)]">
                      {text.created} {formatDateTime(run.created_at)}
                    </div>
                  </button>
                ))
              ) : (
                <EmptyState
                  title={text.notReadyTitle}
                  body={text.noImports}
                  locale={locale}
                />
              )}
            </div>
          </section>
        </div>

        <section className="app-card min-w-0 p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="app-product-mark">{text.reports}</div>
              <h2 className="mt-1 text-xl font-black tracking-normal text-[var(--app-text)]">
                {text.reports}
              </h2>
            </div>
            <div className="flex max-w-full gap-2 overflow-x-auto pb-1">
              {filters.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`shrink-0 rounded-full border px-3 py-2 text-xs font-black ${
                    filter === option.value
                      ? 'border-[var(--app-accent)] bg-[var(--app-accent)] text-[var(--app-base)]'
                      : 'border-[var(--app-border)] text-[var(--app-muted)]'
                  }`}
                  onClick={() => setFilter(option.value)}
                >
                  {option[locale]}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-5 grid min-w-0 gap-4 lg:grid-cols-[minmax(220px,0.72fr)_minmax(0,1.3fr)]">
            <div className="grid content-start gap-3">
              {(reports.data ?? []).length > 0 ? (
                reports.data?.map((report) => (
                  <button
                    key={report.import_run_id}
                    type="button"
                    className={`rounded-2xl border p-4 text-left transition ${
                      selectedReport?.import_run_id === report.import_run_id
                        ? 'border-[var(--app-accent-secondary)] bg-[var(--app-accent-ghost)]'
                        : 'border-[var(--app-border)] bg-[var(--app-surface-0)]'
                    }`}
                    onClick={() => setSelectedImportRunId(report.import_run_id)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <StatusBadge status={report.status} locale={locale} />
                      <span className="text-xs font-semibold text-[var(--app-muted)]">
                        {report.unresolved_count} {text.unresolved}
                      </span>
                    </div>
                    <div className="mt-3 truncate text-sm font-black text-[var(--app-text)]">
                      {report.source_name}
                    </div>
                    <div className="mt-2 text-xs text-[var(--app-muted)]">
                      {text.cashDifference}{' '}
                      {formatReconciliationValue(
                        'cash',
                        report.cash_difference,
                        locale,
                      )}{' '}
                      · {text.feeDifference}{' '}
                      {formatReconciliationValue(
                        'fee',
                        report.fee_difference,
                        locale,
                      )}{' '}
                      · {text.taxDifference}{' '}
                      {formatReconciliationValue(
                        'tax',
                        report.tax_difference,
                        locale,
                      )}
                    </div>
                  </button>
                ))
              ) : (
                <p className="app-muted text-sm">{text.noReports}</p>
              )}
            </div>

            <div className="min-w-0 rounded-3xl border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_62%,transparent)] p-4">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <div className="app-product-mark">{text.detail}</div>
                  <h3 className="mt-1 text-lg font-black text-[var(--app-text)]">
                    {selectedReport?.source_name ?? text.detail}
                  </h3>
                </div>
                {selectedReport ? (
                  <StatusBadge status={selectedReport.status} locale={locale} />
                ) : null}
              </div>

              <div className="grid gap-3">
                {(detail.data?.items ?? []).length > 0 ? (
                  detail.data?.items.map((item) => (
                    <ReviewItemCard
                      key={item.item_key}
                      item={item}
                      importRunId={detail.data.import_run_id}
                      locale={locale}
                      onReview={(reviewStatus) => {
                        setSavedReviewStatus(null);
                        reviewMutation.mutate(
                          {
                            importRunId: detail.data.import_run_id,
                            itemKey: item.item_key,
                            category: item.category,
                            symbol: item.symbol,
                            review_status: reviewStatus,
                          },
                          {
                            onSuccess: (decision) => {
                              setSavedReviewStatus(decision.review_status);
                            },
                          },
                        );
                      }}
                    />
                  ))
                ) : (
                  <p className="app-muted text-sm">{text.noItems}</p>
                )}
              </div>

              {savedReviewStatus ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_12%,transparent)] px-4 py-3 text-sm font-bold text-[var(--app-success)]">
                  {text.reviewSaved}:{' '}
                  {formatPublicStatus(savedReviewStatus, locale)}
                </div>
              ) : null}
              {reviewMutation.isError ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_12%,transparent)] px-4 py-3 text-sm font-bold text-[var(--app-danger)]">
                  {text.reviewFailed}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[var(--app-border)] bg-[var(--app-surface-0)] p-3">
      <div className="text-xs font-semibold text-[var(--app-muted)]">
        {label}
      </div>
      <div className="mt-1 text-lg font-black text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

function MissingEvidenceCallout({ locale }: { locale: 'en' | 'zh' }) {
  const text = labels[locale];
  return (
    <div className="mt-5 rounded-3xl border border-[color-mix(in_srgb,var(--app-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] p-4">
      <div className="text-base font-black text-[var(--app-text)]">
        {text.notReadyTitle}
      </div>
      <p className="mt-2 text-sm font-semibold leading-6 text-[var(--app-muted)]">
        {text.notReadyBody}
      </p>
      <div className="mt-4 rounded-2xl border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_62%,transparent)] p-3">
        <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
          {text.workflowTitle}
        </div>
        <ol className="mt-3 grid gap-2 text-sm font-semibold text-[var(--app-text)]">
          {text.workflowSteps.map((step, index) => (
            <li
              key={step}
              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2"
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[var(--app-accent-ghost)] text-xs font-black text-[var(--app-accent)]">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function EmptyState({
  title,
  body,
  locale,
}: {
  title: string;
  body: string;
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  return (
    <div className="rounded-2xl border border-dashed border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_48%,transparent)] p-4">
      <div className="text-sm font-black text-[var(--app-text)]">{title}</div>
      <p className="mt-2 text-sm font-semibold leading-6 text-[var(--app-muted)]">
        {body}
      </p>
      <div className="mt-3 text-xs font-bold text-[var(--app-muted)]">
        {text.workflowSteps[0]} → {text.workflowSteps[1]}
      </div>
    </div>
  );
}

function ReasonList({
  title,
  values,
  locale,
}: {
  title: string;
  values: string[];
  locale: 'en' | 'zh';
}) {
  if (values.length === 0) {
    return null;
  }
  return (
    <div className="mt-4">
      <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
        {title}
      </div>
      <div className="mt-2 grid gap-2">
        {values.map((value) => (
          <div
            key={value}
            className="rounded-xl bg-[var(--app-surface-0)] px-3 py-2 text-xs font-semibold text-[var(--app-muted)]"
          >
            {formatCode(value, locale, 'code')}
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewItemCard({
  item,
  importRunId,
  locale,
  onReview,
}: {
  item: ReconciliationItem;
  importRunId: string;
  locale: 'en' | 'zh';
  onReview: (status: ReviewStatus) => void;
}) {
  const text = labels[locale];
  const itemTitle = item.symbol
    ? formatInstrumentDisplayLabel({
        symbol: item.symbol,
        display_name: item.display_name ?? null,
      })
    : formatCode(item.category, locale, 'code');
  const latestReviewNote = formatPublicOperationalNote(
    item.latest_review?.note,
    locale,
  );
  const evidenceInstrumentNames =
    item.symbol && item.display_name
      ? new Map([[item.symbol.toLowerCase(), item.display_name]])
      : undefined;
  const detailContextEntries = Object.entries(item.detail_context ?? {}).filter(
    ([, value]) => value.trim().length > 0,
  );
  return (
    <article
      className="min-w-0 rounded-2xl border border-[var(--app-border)] bg-[var(--app-panel)] p-4"
      data-testid={`account-truth-item-${item.item_key}`}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge status={item.status} locale={locale} />
            <span className="text-lg font-black text-[var(--app-text)]">
              {itemTitle}
            </span>
            <span className="rounded-full bg-[var(--app-surface-0)] px-2 py-1 text-xs font-semibold text-[var(--app-muted)]">
              {formatCode(item.category, locale, 'code')}
            </span>
          </div>
          <p className="app-muted mt-2 text-sm leading-6">
            {formatPublicNote(item.detail_code ?? item.detail, locale)}
          </p>
          {detailContextEntries.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {detailContextEntries.map(([key, value]) => (
                <span
                  key={key}
                  className="inline-flex min-w-0 items-center gap-2 rounded-full border border-[var(--app-border)] bg-[var(--app-surface-0)] px-3 py-1 text-xs font-bold text-[var(--app-muted)]"
                >
                  <span className="shrink-0">
                    {formatCode(key, locale, 'code')}
                  </span>
                  <span className="min-w-0 truncate text-[var(--app-text)]">
                    {formatCode(value, locale, 'code')}
                  </span>
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="text-xs font-semibold text-[var(--app-muted)]">
          {importRunId}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Metric
          label={text.broker}
          value={`${text.broker} ${formatReconciliationValue(
            item.category,
            item.broker_value,
            locale,
          )}`}
        />
        <Metric
          label={text.karkinos}
          value={`${text.karkinos} ${formatReconciliationValue(
            item.category,
            item.karkinos_value,
            locale,
          )}`}
        />
        <Metric
          label={text.difference}
          value={`${text.difference} ${formatReconciliationValue(
            item.category,
            item.difference,
            locale,
          )}`}
        />
      </div>

      <div className="mt-4 grid gap-3">
        <div className="rounded-2xl bg-[var(--app-surface-0)] p-3">
          <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
            {text.suggestedAction}
          </div>
          <div className="mt-1 text-sm font-bold text-[var(--app-text)]">
            {formatCode(item.suggested_review_action || '--', locale, 'code')}
          </div>
        </div>
        <div className="rounded-2xl bg-[var(--app-surface-0)] p-3">
          <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
            {text.evidence}
          </div>
          <div className="mt-2 grid gap-1">
            {item.evidence_references.map((reference) => (
              <span
                key={reference}
                className="break-words rounded-lg bg-[var(--app-mantle)] px-2 py-1 text-xs font-semibold text-[var(--app-muted)]"
              >
                {formatLedgerEvidenceReference(
                  reference,
                  locale,
                  evidenceInstrumentNames,
                )}
              </span>
            ))}
          </div>
        </div>
      </div>

      {item.latest_review ? (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] p-3 text-sm font-bold text-[var(--app-success)]">
          <div>
            {text.latestReview}:{' '}
            {formatPublicStatus(item.latest_review.review_status, locale)}
          </div>
          {latestReviewNote ? (
            <div className="mt-1 text-xs font-semibold leading-5 text-[var(--app-soft)]">
              {latestReviewNote}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex max-w-full gap-2 overflow-x-auto pb-1">
        {reviewActions.map((action) => (
          <button
            key={action}
            type="button"
            className="shrink-0 rounded-full border border-[var(--app-border)] px-3 py-2 text-xs font-black text-[var(--app-muted)] transition hover:border-[var(--app-accent)] hover:text-[var(--app-text)]"
            onClick={() => onReview(action)}
          >
            {formatPublicReviewActionLabel(action, locale)}
          </button>
        ))}
      </div>
    </article>
  );
}

function StatusBadge({
  status,
  locale,
}: {
  status: string;
  locale: 'en' | 'zh';
}) {
  const tone =
    status === 'pass'
      ? 'var(--app-success)'
      : status === 'warning' || status === 'degraded'
        ? 'var(--app-warning)'
        : 'var(--app-danger)';
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-xs font-black"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 44%, transparent)`,
        color: tone,
        background: `color-mix(in srgb, ${tone} 10%, transparent)`,
      }}
    >
      {formatCode(status, locale, 'status')}
    </span>
  );
}

function formatCode(
  value: string,
  locale: 'en' | 'zh',
  kind: 'status' | 'code',
) {
  return kind === 'status'
    ? formatPublicStatus(value, locale)
    : formatPublicCode(value, locale);
}
