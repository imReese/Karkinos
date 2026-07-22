import { usePreferences } from '../../../app/preferences';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
  type StatusTone,
} from '../../../app/components/workbench';
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
    return 'border-l-[var(--app-success-indicator)]';
  }
  if (recommendation.status === 'degraded') {
    return 'border-l-[var(--app-warning-indicator)]';
  }
  return 'border-l-[var(--app-danger-indicator)]';
}

function badgeClass(
  recommendation: PortfolioConstructionRecommendation,
): StatusTone {
  if (recommendation.actionable) {
    return 'success';
  }
  if (recommendation.status === 'degraded') {
    return 'warning';
  }
  return 'danger';
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
      <EvidenceState
        kind="loading"
        title={
          locale === 'zh'
            ? '正在加载组合构建建议。'
            : 'Loading construction recommendations.'
        }
      />
    );
  }

  if (isError) {
    return (
      <EvidenceState
        kind="error"
        title={
          locale === 'zh'
            ? '组合构建建议加载失败。'
            : 'Failed to load construction recommendations.'
        }
        action={
          onRetry ? (
            <button
              type="button"
              className="app-button-secondary min-h-8 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
              onClick={onRetry}
            >
              {locale === 'zh' ? '重试' : 'Retry'}
            </button>
          ) : undefined
        }
      />
    );
  }

  if (recommendations.length === 0) {
    return <EvidenceState kind="empty" title={labels.empty} />;
  }

  return (
    <section className="min-w-0">
      <div className="mb-3 space-y-1">
        <h2 className="text-sm font-semibold text-[var(--app-text)]">
          {labels.title}
        </h2>
        <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
          {labels.subtitle}
        </p>
      </div>
      <div className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
        {recommendations.map((recommendation) => (
          <article
            key={`${recommendation.symbol}-${recommendation.source_action_task_id ?? 'none'}`}
            data-testid={`construction-recommendation-${recommendation.symbol}`}
            className={`border-l-2 px-3 py-3 ${toneClass(recommendation)}`}
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
              <StatusBadge tone={badgeClass(recommendation)}>
                {recommendation.actionable
                  ? labels.actionable
                  : formatPublicStatus(recommendation.status, locale)}
              </StatusBadge>
            </div>

            <MetricStrip
              ariaLabel={`${recommendation.name} ${labels.title}`}
              className="mt-3"
              items={[
                {
                  id: 'actual',
                  label: labels.actual,
                  value: percent(recommendation.actual_weight),
                },
                {
                  id: 'target',
                  label: labels.target,
                  value: percent(recommendation.target_weight),
                },
                {
                  id: 'drift',
                  label: labels.drift,
                  value: percent(recommendation.drift),
                },
              ]}
            />

            <dl className="mt-3 grid gap-2 border-t border-[var(--app-divider)] pt-2 text-xs sm:grid-cols-2">
              <div className="flex min-w-0 items-center justify-between gap-2">
                <dt className="text-[var(--app-text-secondary)]">
                  {labels.accountTruth}
                </dt>
                <dd>
                  <StatusBadge
                    tone={
                      recommendation.account_truth_gate_status === 'passed'
                        ? 'success'
                        : recommendation.account_truth_gate_status ===
                            'degraded'
                          ? 'warning'
                          : 'danger'
                    }
                  >
                    {displayGateStatus(
                      recommendation.account_truth_gate_status,
                      locale,
                    )}
                  </StatusBadge>
                </dd>
              </div>
              <div className="flex min-w-0 items-center justify-between gap-2">
                <dt className="text-[var(--app-text-secondary)]">
                  {labels.risk}
                </dt>
                <dd>
                  <StatusBadge
                    tone={
                      recommendation.risk_gate_status === 'passed'
                        ? 'success'
                        : recommendation.risk_gate_status === 'degraded'
                          ? 'warning'
                          : 'danger'
                    }
                  >
                    {displayGateStatus(recommendation.risk_gate_status, locale)}
                  </StatusBadge>
                </dd>
              </div>
            </dl>

            <p className="mt-3 text-xs leading-relaxed text-[var(--app-text)]">
              {recommendation.rationale}
            </p>

            {recommendation.required_actions.length > 0 ? (
              <div className="mt-3 border-t border-[var(--app-divider)] pt-2">
                <div className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] app-muted">
                  {labels.nextActions}
                </div>
                <ul className="mt-1.5 grid gap-1 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {recommendation.required_actions.map((action) => (
                    <li key={action} className="flex gap-2">
                      <span aria-hidden="true">·</span>
                      {formatPublicCode(action, locale)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
