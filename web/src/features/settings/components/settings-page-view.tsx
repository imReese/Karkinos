import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import type { SettingsPageController } from './settings-page-controller';
import { SettingsOperationsWorkspace } from './settings-operations-workspace';
import { SettingsPersistedConfiguration } from './settings-persisted-configuration';
import { SettingsPreferencesWorkspace } from './settings-preferences-workspace';
import {
  getErrorMessage,
  InlineNotice,
  SettingsSection,
} from './settings-view-primitives';

export function SettingsPageView({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    assetMetadataStatus,
    copy,
    dataSourceStatus,
    liveStatus,
    marketHealth,
    overview,
    settings,
    statusLoadFailed,
  } = controller;
  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="settings"
    >
      <WorkspaceHeader
        eyebrow={copy.settings.kicker}
        title={copy.settings.title}
        description={copy.settings.subtitle}
      />
      {statusLoadFailed ? (
        <InlineNotice
          tone="danger"
          title={copy.settings.error}
          detail={[
            settings.error,
            dataSourceStatus.error,
            assetMetadataStatus.error,
            liveStatus.error,
            marketHealth.error,
            overview.error,
          ]
            .filter(Boolean)
            .map((error) => getErrorMessage(error, copy.settings.error))
            .join(' · ')}
        />
      ) : null}
      <SettingsDataStatus controller={controller} />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <div className="contents">
          <SettingsPersistedConfiguration controller={controller} />
          <SettingsOperationsWorkspace controller={controller} />
        </div>
        <SettingsPreferencesWorkspace controller={controller} />
      </div>
    </section>
  );
}

function SettingsDataStatus({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    copy,
    isCacheOnly,
    isStaleQuote,
    marketDataNoticeDetail,
    marketHealth,
    overview,
    quoteNeedsReview,
    quoteStatusLabel,
    refreshPolicyLabel,
    refreshPolicyNeedsReview,
    valuationTime,
  } = controller;
  return (
    <SettingsSection
      title={copy.settings.dataStatus}
      detail={copy.settings.dataStatusDetail}
    >
      <MetricStrip
        ariaLabel={copy.settings.dataStatus}
        items={[
          {
            id: 'market-state',
            label: copy.settings.marketState,
            value: marketHealth.isLoading ? (
              copy.shell.checking
            ) : marketHealth.data?.market_open ? (
              <span
                aria-label={`${copy.settings.marketState}: ${copy.shell.marketOpen}`}
              >
                {copy.shell.marketOpen}
              </span>
            ) : (
              <span
                aria-label={`${copy.settings.marketState}: ${copy.shell.marketClosed}`}
              >
                {copy.shell.marketClosed}
              </span>
            ),
            tone: 'neutral',
          },
          {
            id: 'refresh-policy',
            label: copy.settings.refreshPolicy,
            value: marketHealth.isLoading ? (
              copy.shell.checking
            ) : (
              <span
                aria-label={`${copy.settings.refreshPolicy}: ${refreshPolicyLabel}`}
              >
                {refreshPolicyLabel}
              </span>
            ),
            tone: refreshPolicyNeedsReview ? 'warning' : 'neutral',
          },
          {
            id: 'quote-state',
            label: copy.settings.quoteState,
            value: overview.isLoading ? (
              copy.shell.checking
            ) : isStaleQuote ? (
              <span
                aria-label={`${copy.settings.quoteState}: ${copy.settings.cachedQuotes}`}
              >
                {copy.settings.cachedQuotes}
              </span>
            ) : (
              <span
                aria-label={`${copy.settings.quoteState}: ${quoteStatusLabel}`}
              >
                {quoteStatusLabel}
              </span>
            ),
            tone: quoteNeedsReview ? 'warning' : 'neutral',
          },
          {
            id: 'valuation-time',
            label: copy.settings.valuationTime,
            value: overview.isLoading ? copy.shell.checking : valuationTime,
            tone: quoteNeedsReview ? 'warning' : 'neutral',
          },
        ]}
      />

      {refreshPolicyNeedsReview || quoteNeedsReview ? (
        <div className="grid gap-2">
          <InlineNotice
            tone="warning"
            title={
              isStaleQuote
                ? copy.settings.cachedQuotes
                : isCacheOnly
                  ? copy.settings.cacheOnly
                  : copy.settings.valuationRequiresReview
            }
            detail={
              isStaleQuote
                ? marketDataNoticeDetail(copy.settings.cachedQuotesDetail)
                : isCacheOnly
                  ? marketDataNoticeDetail(copy.settings.cacheOnlyDetail)
                  : marketDataNoticeDetail(
                      copy.settings.valuationRequiresReviewDetail(
                        quoteStatusLabel,
                      ),
                    )
            }
          />
          <a
            aria-controls="settings-data-source-disclosure"
            className="app-button-secondary inline-flex min-h-10 w-max max-w-full items-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="#settings-data-source-disclosure"
            onClick={() => {
              const disclosure = document.getElementById(
                'settings-data-source-disclosure',
              );
              if (disclosure instanceof HTMLDetailsElement) {
                disclosure.open = true;
              }
            }}
          >
            {copy.settings.reviewRefreshControls}
          </a>
        </div>
      ) : null}
    </SettingsSection>
  );
}
