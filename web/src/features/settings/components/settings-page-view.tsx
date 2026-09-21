import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import type { SettingsPageController } from './settings-page-controller';
import { SettingsOperationsWorkspace } from './settings-operations-workspace';
import { SettingsPersistedConfiguration } from './settings-persisted-configuration';
import { SettingsPreferencesWorkspace } from './settings-preferences-workspace';
import {
  getErrorMessage,
  InlineNotice,
  SettingsDisclosure,
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
      className="app-workbench-route space-y-4 sm:space-y-5"
      data-workbench-route="settings"
    >
      <WorkspaceHeader
        eyebrow={copy.settings.kicker}
        title={copy.settings.title}
        description={copy.settings.subtitle}
      />
      <SettingsCategoryBar controller={controller} />
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
      <SettingsPersistedConfiguration controller={controller} />
      <SettingsDataStatus controller={controller} />

      <SettingsDisclosure
        testId="settings-operational-controls-disclosure"
        title={copy.settings.operationalControls}
        detail={copy.settings.operationalControlsDetail}
      >
        <SettingsOperationsWorkspace controller={controller} />
      </SettingsDisclosure>

      <SettingsDisclosure
        testId="settings-local-preferences-boundaries-disclosure"
        title={copy.settings.localPreferencesBoundaries}
        detail={copy.settings.localPreferencesBoundariesDetail}
      >
        <SettingsPreferencesWorkspace controller={controller} />
      </SettingsDisclosure>
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
            aria-controls="settings-operational-controls-disclosure settings-data-source-disclosure"
            className="app-button-secondary inline-flex min-h-10 w-max max-w-full items-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="#settings-operational-controls-disclosure"
            onClick={() => {
              const workspace = document.getElementById(
                'settings-operational-controls-disclosure',
              );
              const disclosure = document.getElementById(
                'settings-data-source-disclosure',
              );
              if (workspace instanceof HTMLDetailsElement) {
                workspace.open = true;
              }
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

function SettingsCategoryBar({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    accountCommissionRate,
    locale,
    pollInterval,
    providerName,
    trackedAssets,
  } = controller;

  const jumpTo = (targetId: string, parentDisclosureId?: string) => {
    if (parentDisclosureId) {
      const parent = document.getElementById(parentDisclosureId);
      if (parent instanceof HTMLDetailsElement) {
        parent.open = true;
      }
    }
    const target = document.getElementById(targetId);
    if (target instanceof HTMLDetailsElement) {
      target.open = true;
    }
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const commissionBp = (Number(accountCommissionRate) * 10000).toFixed(1);

  const categories = [
    {
      id: 'settings-persisted-configuration',
      label: locale === 'zh' ? '基础参数' : 'Core Defaults',
      meta: `${providerName} · ${pollInterval}s`,
    },
    {
      id: 'settings-configuration-editor',
      label: locale === 'zh' ? '费率与数据源' : 'Costs & Source',
      meta: locale === 'zh' ? `万 ${commissionBp}` : `${commissionBp} bp`,
    },
    {
      id: 'settings-metadata-disclosure',
      label: locale === 'zh' ? '标的元数据' : 'Metadata',
      meta:
        locale === 'zh' ? `${trackedAssets} 标的` : `${trackedAssets} symbols`,
    },
    {
      id: 'settings-operational-controls-disclosure',
      label: locale === 'zh' ? '接口能力' : 'Capabilities',
      meta: locale === 'zh' ? '服务就绪' : 'Services',
    },
    {
      id: 'settings-local-preferences-boundaries-disclosure',
      label: locale === 'zh' ? '安全与偏好' : 'Safety & UI',
      meta: locale === 'zh' ? '主题与语言' : locale.toUpperCase(),
    },
  ];

  return (
    <nav
      aria-label="Settings Categories"
      className="flex flex-wrap items-center gap-2 py-1"
    >
      {categories.map((cat) => (
        <button
          key={cat.id}
          type="button"
          onClick={() => jumpTo(cat.id)}
          className="app-interactive-surface inline-flex items-center gap-2 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-soft)] hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent-text)] transition-colors"
        >
          <span>{cat.label}</span>
          <span className="app-type-micro font-mono text-[var(--app-muted)]">
            {cat.meta}
          </span>
        </button>
      ))}
    </nav>
  );
}
