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
import type { QuoteFetchRun } from '../api';
import { MarketRefreshButton } from '../components/market-refresh-button';
import type { MarketPageController } from './market-page-controller';
import { formatAge } from './market-page-format';

export function MarketDataEvidenceWorkspace({
  controller,
}: {
  controller: MarketPageController;
}) {
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
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
            <span>{copy.market.providerStatus}</span>
            <span aria-hidden="true" className="group-open:rotate-180">
              ▾
            </span>
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
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
          <span>{copy.market.promptsTitle}</span>
          <span aria-hidden="true" className="group-open:rotate-180">
            ▾
          </span>
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
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
          <span>{copy.market.dataOperations}</span>
          <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
            {quoteFetchRuns.data?.length ?? 0}
            <span aria-hidden="true" className="group-open:rotate-180">
              ▾
            </span>
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
    </div>
  );
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
