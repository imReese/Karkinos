import { usePreferences } from '../../../app/preferences';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatPercent } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type { PortfolioConstructionRecommendation } from '../api';

type Labels = {
  title: string;
  subtitle: string;
  empty: string;
  actual: string;
  target: string;
  drift: string;
  accountTruth: string;
  risk: string;
  nextActions: string;
  actionable: string;
  reviewOnly: string;
};

const LABELS: Record<'en' | 'zh', Labels> = {
  en: {
    title: 'Portfolio construction recommendations',
    subtitle:
      'Read-only rebalance evidence. A recommendation becomes a manual-review candidate only after account-truth and risk gates pass.',
    empty: 'No gated construction recommendations are available yet.',
    actual: 'Actual',
    target: 'Target',
    drift: 'Drift',
    accountTruth: 'Account truth',
    risk: 'Risk',
    nextActions: 'Next actions',
    actionable: 'Ready for manual review',
    reviewOnly: 'Review only',
  },
  zh: {
    title: '组合构建建议',
    subtitle:
      '只读再平衡证据。只有账户事实与风控闸门都通过后，建议才会成为人工复核候选。',
    empty: '暂无已门控的组合构建建议。',
    actual: '实际',
    target: '目标',
    drift: '漂移',
    accountTruth: '账户事实',
    risk: '风控',
    nextActions: '下一步',
    actionable: '可进入人工复核',
    reviewOnly: '仅复核',
  },
};

function percent(value: number) {
  return formatPercent(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function toneClass(recommendation: PortfolioConstructionRecommendation) {
  if (recommendation.actionable) {
    return 'border-[color-mix(in_srgb,var(--app-success)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)]';
  }
  if (recommendation.status === 'degraded') {
    return 'border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)]';
  }
  return 'border-[color-mix(in_srgb,var(--app-danger)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_7%,transparent)]';
}

function badgeClass(recommendation: PortfolioConstructionRecommendation) {
  if (recommendation.actionable) {
    return 'border-[color-mix(in_srgb,var(--app-success)_38%,transparent)] text-[var(--app-success)]';
  }
  if (recommendation.status === 'degraded') {
    return 'border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] text-[var(--app-warning)]';
  }
  return 'border-[color-mix(in_srgb,var(--app-danger)_34%,transparent)] text-[var(--app-danger)]';
}

function displayGateStatus(status: string, locale: 'en' | 'zh') {
  return formatPublicStatus(status === 'passed' ? 'pass' : status, locale);
}

export function PortfolioConstructionRecommendationsCard({
  recommendations,
  isLoading = false,
  isError = false,
  onRetry,
}: {
  recommendations: PortfolioConstructionRecommendation[];
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
}) {
  const { locale } = usePreferences();
  const labels = LABELS[locale];

  if (isLoading) {
    return (
      <div className="app-panel rounded-2xl p-4 text-sm app-muted sm:p-5">
        {locale === 'zh'
          ? '正在加载组合构建建议。'
          : 'Loading construction recommendations.'}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="app-panel rounded-2xl p-4 sm:p-5">
        <div className="font-semibold text-[var(--app-danger)]">
          {locale === 'zh'
            ? '组合构建建议加载失败。'
            : 'Failed to load construction recommendations.'}
        </div>
        {onRetry ? (
          <button
            type="button"
            className="mt-3 rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold"
            onClick={onRetry}
          >
            {locale === 'zh' ? '重试' : 'Retry'}
          </button>
        ) : null}
      </div>
    );
  }

  if (recommendations.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-4 text-sm app-muted sm:p-5">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="mb-4 space-y-1">
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {labels.title}
        </div>
        <p className="text-xs leading-relaxed app-muted">{labels.subtitle}</p>
      </div>
      <div className="space-y-3">
        {recommendations.map((recommendation) => (
          <article
            key={`${recommendation.symbol}-${recommendation.source_action_task_id ?? 'none'}`}
            data-testid={`construction-recommendation-${recommendation.symbol}`}
            className={`rounded-2xl border p-3 ${toneClass(recommendation)}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-semibold text-[var(--app-text)]">
                  {recommendation.name}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs app-muted">
                  <span>{recommendation.symbol}</span>
                  <span>
                    {formatAssetClassLabel(
                      recommendation.asset_class,
                      locale === 'zh'
                        ? {
                            assetClassStock: '股票',
                            assetClassEtf: 'ETF',
                            assetClassFund: '基金',
                            assetClassGold: '黄金',
                            assetClassBond: '债券',
                            assetClassCash: '现金',
                          }
                        : {
                            assetClassStock: 'Stock',
                            assetClassEtf: 'ETF',
                            assetClassFund: 'Fund',
                            assetClassGold: 'Gold',
                            assetClassBond: 'Bond',
                            assetClassCash: 'Cash',
                          },
                    )}
                  </span>
                </div>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${badgeClass(
                  recommendation,
                )}`}
              >
                {recommendation.actionable
                  ? labels.actionable
                  : formatPublicStatus(recommendation.status, locale)}
              </span>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <Metric
                label={labels.actual}
                value={percent(recommendation.actual_weight)}
              />
              <Metric
                label={labels.target}
                value={percent(recommendation.target_weight)}
              />
              <Metric
                label={labels.drift}
                value={percent(recommendation.drift)}
              />
            </div>

            <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
                {`${labels.accountTruth}：${displayGateStatus(
                  recommendation.account_truth_gate_status,
                  locale,
                )}`}
              </div>
              <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
                {`${labels.risk}：${displayGateStatus(
                  recommendation.risk_gate_status,
                  locale,
                )}`}
              </div>
            </div>

            <p className="mt-3 text-xs leading-relaxed text-[var(--app-text)]">
              {recommendation.rationale}
            </p>

            {recommendation.required_actions.length > 0 ? (
              <div className="mt-3">
                <div className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] app-muted">
                  {labels.nextActions}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {recommendation.required_actions.map((action) => (
                    <span
                      key={action}
                      className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-xs app-muted"
                    >
                      {formatPublicCode(action, locale)}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
      <div className="app-muted">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
        {label} {value}
      </div>
    </div>
  );
}
