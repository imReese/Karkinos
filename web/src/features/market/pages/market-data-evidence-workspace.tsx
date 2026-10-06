import { ChevronDown } from 'lucide-react';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { getErrorMessage } from '../../../shared/error-message';
import { formatTimestamp } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
  Timeline,
} from '../../../shared/ui/workbench';
import {
  useDailyCollectionQualityQuery,
  useMarketDailyProviderBudgetQuery,
  type DailyCollectionQualityRun,
  type QuoteFetchRun,
} from '../api';
import { MarketRefreshButton } from '../components/market-refresh-button';
import type { MarketPageController } from './market-page-controller';
import { formatAge } from './market-page-format';

export function MarketDataEvidenceWorkspace({
  controller,
  active,
}: {
  controller: MarketPageController;
  active: boolean;
}) {
  const dailyCollection = useDailyCollectionQualityQuery(active);
  const dailyBudget = useMarketDailyProviderBudgetQuery(active);
  const {
    barsBackfill,
    cacheBound,
    copy,
    health,
    latestQuoteLabel,
    metadataBackfill,
    providerAction,
    providerActionIsFundCoverage,
    providerConfiguredLabel,
    providerFundsLabel,
    providerStatusLabel,
    pushToast,
    quoteFetchRuns,
    refreshPolicyLabel,
    sourceHealthLabel,
    staleCount,
  } = controller;
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-3">
      <section
        className="min-w-0 border-y border-[var(--app-divider)] py-4 lg:col-span-2"
        data-testid="market-data-health-summary"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="app-kicker app-type-overline">
              {copy.market.health}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-[var(--app-text)]">
                {copy.market.sourceHealth}
              </h2>
              <StatusBadge
                tone={
                  cacheBound || staleCount > 0
                    ? 'warning'
                    : health
                      ? 'success'
                      : 'neutral'
                }
              >
                {sourceHealthLabel}
              </StatusBadge>
            </div>
          </div>
          <MarketRefreshButton
            onComplete={(response) => {
              const title =
                response.quote_status === 'live'
                  ? copy.market.quoteRefreshComplete
                  : response.quote_status === 'partial'
                    ? copy.market.quoteRefreshPartial
                    : response.quote_status === 'stale'
                      ? copy.market.quoteRefreshStale
                      : copy.market.quoteRefreshFailed;
              pushToast(
                response.quote_status === 'error' ? 'error' : 'success',
                title,
                response.message,
              );
            }}
            onError={(error) => {
              pushToast('error', copy.market.quoteRefreshFailed, error.message);
            }}
          />
        </div>

        <MetricStrip
          className="mt-3"
          ariaLabel={copy.market.health}
          items={[
            {
              id: 'provider',
              label: copy.market.provider,
              value: health?.provider_name ?? copy.market.unknown,
              detail: providerStatusLabel,
            },
            {
              id: 'refresh-policy',
              label: copy.market.refreshPolicy,
              value: refreshPolicyLabel,
              detail: providerConfiguredLabel,
              tone: cacheBound ? 'warning' : 'neutral',
            },
            {
              id: 'cache-age',
              label: copy.market.cacheAge,
              value: formatAge(health?.cache_age_seconds),
              detail: latestQuoteLabel,
            },
            {
              id: 'review-count',
              label: copy.market.health,
              value: staleCount,
              detail: copy.market.staleSymbols,
              tone: staleCount > 0 ? 'warning' : 'neutral',
            },
          ]}
        />

        {providerAction ? (
          <div
            className="mt-3 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-text-secondary)]"
            data-action-scope={
              providerActionIsFundCoverage ? 'fund-coverage' : 'provider'
            }
          >
            {providerActionIsFundCoverage ? (
              <span className="app-type-overline mb-0.5 block text-[var(--app-warning-text)]">
                {copy.market.providerFundCoverageScope}
              </span>
            ) : null}
            <span className="font-semibold text-[var(--app-text)]">
              {copy.market.providerNextAction}:
            </span>{' '}
            {providerAction}
          </div>
        ) : null}

        <details
          className="group mt-3 border-t border-[var(--app-divider)] pt-2"
          data-testid="market-provider-details"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span>{copy.market.providerStatus}</span>
            <ChevronDown
              aria-hidden="true"
              className="size-3.5 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
            />
          </summary>
          <dl className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs">
            {[
              [copy.market.providerConfigured, providerConfiguredLabel],
              [copy.market.providerSupportsFunds, providerFundsLabel],
              [
                copy.market.metadataConfiguredCount,
                health == null
                  ? '--'
                  : String(health.metadata_configured_count),
              ],
              [
                copy.market.providerTimeout,
                health?.provider_timeout_seconds == null
                  ? '--'
                  : `${health.provider_timeout_seconds}s`,
              ],
              [
                copy.market.lastRefreshAttempt,
                formatTimestamp(health?.last_refresh_attempt),
              ],
              [
                copy.market.lastRefreshError,
                formatStaleReason(
                  health?.provider_last_error ?? health?.last_refresh_error,
                  copy.common.staleReasons,
                ),
              ],
            ].map(([label, value]) => (
              <div
                key={label}
                className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-3 px-2 py-2"
              >
                <dt className="text-[var(--app-text-tertiary)]">{label}</dt>
                <dd className="min-w-0 break-words text-right text-[var(--app-text-secondary)]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      </section>
      <details className="group border-y border-[var(--app-divider)] py-2">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
          <span>{copy.market.promptsTitle}</span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180 text-[var(--app-text-tertiary)]"
          />
        </summary>
        <div className="mt-2 divide-y divide-[var(--app-divider)]">
          {copy.market.prompts.map((prompt) => (
            <div
              key={prompt}
              className="py-2 text-xs leading-5 text-[var(--app-text-secondary)]"
            >
              {prompt}
            </div>
          ))}
        </div>
      </details>
      <details
        className="group border-y border-[var(--app-divider)] py-2"
        data-testid="market-data-operations-disclosure"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
          <span>{copy.market.dataOperations}</span>
          <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
            {quoteFetchRuns.data?.length ?? 0}
            <ChevronDown
              aria-hidden="true"
              className="size-4 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180 text-[var(--app-text-tertiary)]"
            />
          </span>
        </summary>
        <div className="mt-3">
          <MarketDataOperationsPanel
            runs={quoteFetchRuns.data ?? []}
            loading={quoteFetchRuns.isLoading}
            error={quoteFetchRuns.isError}
            metadataPending={metadataBackfill.isPending}
            barsPending={barsBackfill.isPending}
            onMetadataBackfill={async () => {
              try {
                const result = await metadataBackfill.mutateAsync();
                pushToast(
                  'success',
                  copy.market.metadataBackfillComplete,
                  copy.market.backfillResult(
                    result.updated_count,
                    result.failed_count,
                  ),
                );
              } catch (error) {
                pushToast(
                  'error',
                  copy.market.metadataBackfillFailed,
                  getErrorMessage(error),
                );
              }
            }}
            onBarsBackfill={async () => {
              try {
                const result = await barsBackfill.mutateAsync();
                pushToast(
                  'success',
                  copy.market.barsBackfillComplete,
                  copy.market.backfillResult(
                    result.updated_count,
                    result.failed_count,
                  ),
                );
              } catch (error) {
                pushToast(
                  'error',
                  copy.market.barsBackfillFailed,
                  getErrorMessage(error),
                );
              }
            }}
          />
        </div>
      </details>
      <DailyResearchCollectionPanel
        runs={dailyCollection.data}
        runsLoading={dailyCollection.isLoading}
        runsError={dailyCollection.isError}
        budget={dailyBudget.data}
        budgetLoading={dailyBudget.isLoading}
        budgetError={dailyBudget.isError}
      />
    </div>
  );
}

function DailyResearchCollectionPanel({
  runs,
  runsLoading,
  runsError,
  budget,
  budgetLoading,
  budgetError,
}: {
  runs: DailyCollectionQualityRun[] | undefined;
  runsLoading: boolean;
  runsError: boolean;
  budget: ReturnType<typeof useMarketDailyProviderBudgetQuery>['data'];
  budgetLoading: boolean;
  budgetError: boolean;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const budgetKnown =
    budget?.scope === 'managed_daily_market_jobs' &&
    Object.keys(budget.groups).length > 0;

  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4 lg:col-span-2"
      data-testid="market-daily-research-collection"
    >
      <div className="app-kicker app-type-overline">
        {zh ? '研究数据维护' : 'Research data maintenance'}
      </div>
      <h2 className="mt-1 text-lg font-semibold text-[var(--app-text)]">
        {zh ? '自动日线采集' : 'Automatic daily-bar collection'}
      </h2>
      <p className="app-muted mt-2 text-xs leading-5">
        {zh
          ? '这里仅显示受管单源采集与质量证据；成功不代表跨源核验、历史 PIT 可用或 Dataset 已发布。'
          : 'This shows managed single-source capture and quality evidence only. Success does not establish cross-source agreement, historical PIT availability, or Dataset publication.'}
      </p>

      <div className="mt-4 border-t border-[var(--app-divider)] pt-3">
        <h3 className="text-sm font-semibold">
          {zh ? '今日上游调用预算' : "Today's upstream attempt budget"}
        </h3>
        <p className="app-muted mt-1 text-xs leading-5">
          {zh
            ? '自动单源与显式双源受管日线任务共用，按上海自然日统计每次 fetch_daily_bars 前的预留尝试；不是供应商配额或 SDK 内部远端请求数，也不包含旧 TDX 直接准备。'
            : 'Automatic single-source and explicit two-source managed daily-bar jobs share this budget. It counts reservations before each fetch_daily_bars attempt by Shanghai day, not provider quota or SDK internal requests; legacy direct TDX preparation is outside this scope.'}
        </p>
        {budgetLoading ? (
          <p className="app-muted mt-2 text-xs">
            {zh ? '正在读取预算…' : 'Loading budget…'}
          </p>
        ) : budgetError || !budgetKnown ? (
          <p className="mt-2 text-xs text-[var(--app-warning-text)]">
            {zh
              ? '预算用量未知，不能据此判断还可采集多少。'
              : 'Budget usage is unknown; remaining collection capacity cannot be inferred.'}
          </p>
        ) : (
          <>
            <p className="app-muted mt-2 text-xs tabular-nums">
              {zh ? '上海日期：' : 'Shanghai date: '}
              {budget.shanghai_date}
            </p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {Object.entries(budget.groups).map(([group, usage]) => (
                <div
                  key={group}
                  className="border-l-2 border-[var(--app-divider)] py-1 pl-3 text-xs"
                >
                  <div className="font-semibold">{group}</div>
                  <div className="mt-1 tabular-nums text-[var(--app-text-secondary)]">
                    {zh ? '已用' : 'Used'} {usage.used}/{usage.limit} ·{' '}
                    {zh ? '剩余' : 'Remaining'} {usage.remaining}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="mt-4 border-t border-[var(--app-divider)] pt-3">
        <h3 className="text-sm font-semibold">
          {zh
            ? '最近单源质量与修订'
            : 'Recent single-source quality and revisions'}
        </h3>
        {runsLoading ? (
          <p className="app-muted mt-2 text-xs">
            {zh ? '正在读取采集记录…' : 'Loading collection records…'}
          </p>
        ) : runsError || !runs ? (
          <p className="mt-2 text-xs text-[var(--app-warning-text)]">
            {zh
              ? '采集记录读取失败，质量与修订状态未知。'
              : 'Collection records could not be read; quality and revision status are unknown.'}
          </p>
        ) : runs.length === 0 ? (
          <p className="app-muted mt-2 text-xs">
            {zh
              ? '暂无受管日线采集记录；不能据此推断历史数据覆盖。'
              : 'No managed daily-bar collection records yet; historical coverage is unknown.'}
          </p>
        ) : (
          <ol
            className="mt-2 divide-y divide-[var(--app-divider)]"
            aria-label={zh ? '最近单源采集' : 'Recent single-source collection'}
          >
            {runs.slice(0, 8).map((run) => (
              <li key={run.job_id} className="py-2 text-xs leading-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-semibold tabular-nums">
                    {run.trade_date ?? (zh ? '日期未知' : 'Unknown date')} ·{' '}
                    {run.instrument?.symbol ??
                      (zh ? '标的未知' : 'Unknown symbol')}
                  </span>
                  <span className="text-[var(--app-text-secondary)]">
                    {collectionRoundLabel(run.observation_round, zh)}
                  </span>
                </div>
                <div className="mt-1 text-[var(--app-text-secondary)]">
                  {zh ? '任务：' : 'Job: '}
                  {formatPublicStatus(run.job_status, locale)} ·{' '}
                  {zh ? '质量：' : 'Quality: '}
                  {collectionQualityLabel(run, zh)}
                  {run.quality_attribution_status === 'verified' &&
                  run.quality?.provider
                    ? ` · ${zh ? '来源：' : 'Source: '}${run.quality.provider}`
                    : ''}
                </div>
                {run.quality_attribution_status === 'verified' &&
                run.quality?.checked_at ? (
                  <div className="mt-1 tabular-nums text-[var(--app-text-tertiary)]">
                    {zh ? '检查时间：' : 'Checked at: '}
                    {formatTimestamp(run.quality.checked_at)}
                  </div>
                ) : null}
                {run.error ? (
                  <div className="mt-1 break-words text-[var(--app-warning-text)]">
                    {zh ? '错误：' : 'Error: '}
                    {formatPublicCode(run.error, locale)}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function collectionRoundLabel(round: string | null, zh: boolean) {
  if (round === null) {
    return zh ? '基线采集' : 'Baseline capture';
  }
  const nextSession = /^post_close\.next_session\.(\d{4}-\d{2}-\d{2})$/.exec(
    round,
  );
  return nextSession
    ? `${zh ? '次交易日复查' : 'Next-session recheck'} · ${nextSession[1]}`
    : zh
      ? '未知修订轮次'
      : 'Unknown revision round';
}

function collectionQualityLabel(run: DailyCollectionQualityRun, zh: boolean) {
  if (run.job_status !== 'succeeded') {
    return zh ? '尚无结论' : 'Not established';
  }
  if (run.quality_read_status === 'not_recorded') {
    return zh ? '尚无质量证据' : 'No quality evidence';
  }
  if (run.quality_read_status !== 'available') {
    return zh ? '证据不可读取' : 'Evidence unreadable';
  }
  if (run.quality_attribution_status === 'mismatch') {
    return zh ? '证据归属不匹配' : 'Evidence attribution mismatch';
  }
  if (run.quality_attribution_status === 'unreadable') {
    return zh ? '证据链不可读取' : 'Evidence lineage unreadable';
  }
  if (run.quality_attribution_status !== 'verified') {
    return zh ? '证据归属未核实' : 'Evidence attribution unverified';
  }
  if (!run.quality) {
    return zh ? '质量未知' : 'Quality unknown';
  }
  if (run.quality.status === 'pass') {
    return zh ? '单源检查通过' : 'Single-source checks passed';
  }
  if (run.quality.status === 'degraded') {
    return zh ? '单源检查降级' : 'Single-source checks degraded';
  }
  if (run.quality.status === 'blocked') {
    return zh ? '单源检查阻断' : 'Single-source checks blocked';
  }
  return zh ? '质量未知' : 'Quality unknown';
}

function MarketDataOperationsPanel({
  runs,
  loading,
  error,
  metadataPending,
  barsPending,
  onMetadataBackfill,
  onBarsBackfill,
}: {
  runs: QuoteFetchRun[];
  loading: boolean;
  error: boolean;
  metadataPending: boolean;
  barsPending: boolean;
  onMetadataBackfill: () => Promise<void>;
  onBarsBackfill: () => Promise<void>;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {copy.market.dataOperations}
          </div>
          <p className="app-muted mt-2 break-words text-sm leading-6">
            {copy.market.dataOperationsDetail}
          </p>
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2">
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={metadataPending}
            onClick={() => void onMetadataBackfill()}
          >
            {metadataPending
              ? copy.market.backfilling
              : copy.market.metadataBackfill}
          </button>
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={barsPending}
            onClick={() => void onBarsBackfill()}
          >
            {barsPending ? copy.market.backfilling : copy.market.barsBackfill}
          </button>
        </div>
      </div>
      {loading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : error ? (
        <EvidenceState kind="error" title={copy.market.quoteFetchRunsFailed} />
      ) : (
        <Timeline
          ariaLabel={copy.market.dataOperations}
          emptyState={copy.market.noQuoteFetchRuns}
          items={runs.slice(0, 4).map((run) => ({
            id: run.run_id,
            timestamp: formatTimestamp(run.started_at),
            title: `${formatPublicCode(run.trigger, locale)} · ${formatPublicStatus(run.status, locale)}`,
            description: `${copy.market.provider}: ${run.provider ?? copy.market.unknown} · ${copy.market.successCount}: ${run.success_count} · ${copy.market.failedCount}: ${run.failure_count} · ${copy.market.cacheHitCount}: ${run.cache_hit_count}`,
            evidence: run.error_message,
            tone:
              run.failure_count > 0 || run.error_message
                ? ('danger' as const)
                : run.status === 'completed'
                  ? ('success' as const)
                  : ('info' as const),
          }))}
        />
      )}
    </div>
  );
}
