import type { SettingsPageController } from './settings-page-controller';
import {
  getErrorMessage,
  InlineNotice,
  RegisterRow,
  SettingsDisclosure,
  SettingsSection,
} from './settings-view-primitives';
import { MetricStrip } from '../../../shared/ui/workbench';

export function SettingsPersistedConfiguration({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { copy } = controller;
  return (
    <div
      className="order-1 min-w-0 xl:col-start-1 xl:row-span-3 xl:row-start-1"
      data-testid="settings-persisted-configuration"
    >
      <SettingsSection
        title={copy.settings.backendSettings}
        detail={copy.settings.persistedSettingsDetail}
      >
        <SettingsOperationsRegister controller={controller} />
        <SettingsConfigurationEditor controller={controller} />
        <SettingsMetadataReadiness controller={controller} />
      </SettingsSection>
    </div>
  );
}

function SettingsOperationsRegister({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    copy,
    latestPersistentQuoteTime,
    metadataConfiguredCount,
    operationsRegisterRows,
    providerActionLabel,
    providerTimedOut,
  } = controller;
  return (
    <>
      <div
        className="grid gap-3 border-y border-[var(--app-divider)] py-3"
        data-settings-surface="flat"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-semibold">
            {copy.settings.operationsRegister}
          </div>
          <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2.5 py-1 font-semibold text-[var(--app-soft)]">
            {latestPersistentQuoteTime}
          </span>
        </div>
        <div className="grid gap-2">
          {operationsRegisterRows.map((row) => (
            <RegisterRow
              key={row.label}
              label={row.label}
              legacyLabel={row.legacyLabel}
              value={row.value}
              tone={row.tone}
            />
          ))}
        </div>
      </div>

      {providerTimedOut ? (
        <InlineNotice
          tone="warning"
          title={copy.settings.providerNextAction}
          detail={copy.settings.providerTimeoutNotice}
        />
      ) : null}
      {metadataConfiguredCount === 0 ? (
        <InlineNotice
          tone="warning"
          title={copy.settings.assetMetadataMissing}
          detail={copy.settings.assetMetadataMissingDetail}
        />
      ) : null}
      {providerActionLabel ? (
        <InlineNotice
          tone="neutral"
          title={copy.settings.providerNextAction}
          detail={providerActionLabel}
        />
      ) : null}
    </>
  );
}

function SettingsConfigurationEditor({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    accountCommissionChanged,
    accountCommissionRate,
    accountMinCommission,
    copy,
    dataSource,
    dataSourceChanged,
    dataSourceOptions,
    dataSourceStatus,
    pollInterval,
    setAccountCommissionRate,
    setAccountMinCommission,
    setDataSource,
    setPollInterval,
    settings,
    submitAccountCommission,
    submitDataSource,
    updateDataSource,
    updateSettings,
  } = controller;
  return (
    <SettingsDisclosure
      testId="settings-configuration-editor"
      title={copy.settings.configurationEditor}
      detail={copy.settings.configurationEditorDetail}
    >
      <form
        className="grid gap-4 border-y border-[var(--app-divider)] py-4"
        data-settings-surface="flat"
        onSubmit={submitAccountCommission}
      >
        <div>
          <div className="text-sm font-semibold">
            {copy.settings.accountCostProfile}
          </div>
          <div className="app-muted mt-1 text-xs leading-5">
            {copy.settings.accountCostProfileDetail}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-2">
            <span className="text-sm font-medium">
              {copy.settings.stockCommissionRate}
            </span>
            <input
              aria-label={copy.settings.stockCommissionRate}
              className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
              type="number"
              min={0}
              step="0.00001"
              value={accountCommissionRate}
              onChange={(event) => setAccountCommissionRate(event.target.value)}
              disabled={settings.isLoading}
            />
          </label>
          <label className="grid gap-2">
            <span className="text-sm font-medium">
              {copy.settings.minimumCommission}
            </span>
            <input
              aria-label={copy.settings.minimumCommission}
              className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
              type="number"
              min={0}
              step="0.01"
              value={accountMinCommission}
              onChange={(event) => setAccountMinCommission(event.target.value)}
              disabled={settings.isLoading}
            />
          </label>
        </div>
        <div className="app-muted text-xs leading-5">
          {copy.settings.accountCostPreview(
            Number(accountCommissionRate) || 0,
            Number(accountMinCommission) || 0,
          )}
        </div>
        <button
          type="submit"
          className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          disabled={
            settings.isLoading ||
            updateSettings.isPending ||
            !accountCommissionChanged
          }
          aria-busy={updateSettings.isPending}
        >
          {updateSettings.isPending
            ? copy.settings.savingAccountCosts
            : copy.settings.saveAccountCosts}
        </button>
      </form>

      {updateSettings.isSuccess ? (
        <InlineNotice
          tone="success"
          title={copy.settings.accountCostsSaved}
          detail={copy.settings.accountCostsSavedDetail}
        />
      ) : null}
      {updateSettings.isError ? (
        <InlineNotice
          tone="danger"
          title={copy.settings.accountCostsFailed}
          detail={getErrorMessage(
            updateSettings.error,
            copy.settings.accountCostsFailed,
          )}
        />
      ) : null}

      <form
        className="grid gap-4 border-y border-[var(--app-divider)] py-4"
        data-settings-surface="flat"
        onSubmit={submitDataSource}
      >
        <div>
          <div className="text-sm font-semibold">
            {copy.settings.providerConfiguration}
          </div>
          <div className="app-muted mt-1 text-xs leading-5">
            {copy.settings.providerConfigurationDetail}
          </div>
        </div>
        <div className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.settings.selectDataSource}
          </span>
          <div className="grid gap-2 sm:grid-cols-3">
            {dataSourceOptions.map((option) => {
              const selected = dataSource === option;
              const label =
                option === 'akshare'
                  ? copy.settings.providerAkshare
                  : option === 'tushare'
                    ? copy.settings.providerTushare
                    : option;
              return (
                <button
                  key={option}
                  type="button"
                  className={`app-interactive-surface rounded-[var(--app-radius-control)] border px-3 py-2 text-sm font-semibold ${
                    selected
                      ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent-text)]'
                      : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] text-[var(--app-soft)] hover:border-[color-mix(in_srgb,var(--app-border)_48%,transparent)]'
                  }`}
                  aria-pressed={selected}
                  aria-label={`${copy.settings.dataSource}: ${label}`}
                  onClick={() => setDataSource(option)}
                  disabled={settings.isLoading}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
        <label className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.settings.pollInterval}
          </span>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
            <input
              aria-label={copy.settings.pollInterval}
              className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
              type="number"
              min={15}
              value={pollInterval}
              onChange={(event) => setPollInterval(event.target.value)}
              disabled={settings.isLoading}
            />
            <span className="app-muted text-xs">
              {copy.settings.pollIntervalUnit}
            </span>
          </div>
        </label>
        <div className="grid gap-2">
          <span className="text-sm font-medium">{copy.settings.token}</span>
          <div
            className="border-y border-[var(--app-divider)] px-1 py-2 text-sm"
            role="status"
            aria-label={copy.settings.token}
          >
            {dataSource !== 'tushare'
              ? copy.settings.credentialNotRequired
              : settings.data?.tushare_token_configured
                ? copy.settings.credentialConfigured
                : copy.settings.credentialMissing}
          </div>
          <span className="app-muted text-xs leading-5">
            {copy.settings.credentialEnvironmentDetail}
          </span>
        </div>
        <button
          type="submit"
          className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          disabled={
            settings.isLoading ||
            updateDataSource.isPending ||
            !dataSourceChanged ||
            (dataSource === 'tushare' &&
              !settings.data?.tushare_token_configured)
          }
          aria-busy={updateDataSource.isPending}
        >
          {updateDataSource.isPending
            ? copy.settings.savingDataSource
            : copy.settings.saveDataSource}
        </button>
      </form>

      {updateDataSource.isSuccess ? (
        <InlineNotice
          tone="success"
          title={copy.settings.dataSourceSaved}
          detail={
            dataSourceStatus.data?.requires_restart
              ? copy.settings.requiresRestart
              : copy.settings.hotSwitchAvailable
          }
        />
      ) : null}
      {updateDataSource.isError ? (
        <InlineNotice
          tone="danger"
          title={copy.settings.dataSourceFailed}
          detail={getErrorMessage(
            updateDataSource.error,
            copy.settings.dataSourceFailed,
          )}
        />
      ) : null}
    </SettingsDisclosure>
  );
}

function SettingsMetadataReadiness({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    assetMetadataStatus,
    copy,
    metadataConfiguredCount,
    metadataSnippet,
    metadataSourceLabel,
    missingMetadataSymbols,
  } = controller;
  return (
    <SettingsDisclosure
      testId="settings-metadata-disclosure"
      title={copy.settings.metadataReadiness}
      detail={copy.settings.metadataReadinessDetail}
    >
      <MetricStrip
        ariaLabel={copy.settings.metadataReadiness}
        className="app-settings-metadata-strip"
        items={[
          {
            id: 'metadata-configured',
            label: copy.settings.metadataConfigured,
            value: assetMetadataStatus.isLoading
              ? copy.shell.checking
              : metadataConfiguredCount,
            tone: metadataConfiguredCount > 0 ? 'neutral' : 'warning',
          },
          {
            id: 'metadata-missing',
            label: copy.settings.assetMetadataMissingCount,
            value: assetMetadataStatus.isLoading
              ? copy.shell.checking
              : missingMetadataSymbols.length,
            tone: missingMetadataSymbols.length > 0 ? 'warning' : 'neutral',
          },
          {
            id: 'metadata-source',
            label: copy.settings.assetMetadataSource,
            value: metadataSourceLabel,
            tone: 'neutral',
          },
        ]}
      />
      {assetMetadataStatus.isLoading ? (
        <InlineNotice
          tone="neutral"
          title={copy.shell.checking}
          detail={copy.settings.assetMetadataDetail}
        />
      ) : assetMetadataStatus.data?.has_missing_metadata ? (
        <div className="grid gap-3">
          <InlineNotice
            tone="warning"
            title={copy.settings.assetMetadataMissingSymbols}
            detail={missingMetadataSymbols.join(', ')}
          />
          <label className="grid gap-2">
            <span className="text-sm font-semibold">
              {copy.settings.assetMetadataSnippet}
            </span>
            <textarea
              className="app-field min-h-44 resize-y rounded-[var(--app-radius-control)] px-3 py-3 font-mono text-xs leading-5"
              readOnly
              aria-label={copy.settings.assetMetadataSnippet}
              value={metadataSnippet}
            />
            <span className="app-muted text-xs leading-5">
              {copy.settings.assetMetadataSnippetDetail}
            </span>
          </label>
        </div>
      ) : (
        <InlineNotice
          tone="success"
          title={copy.settings.assetMetadataComplete}
          detail={copy.settings.assetMetadataCompleteDetail}
        />
      )}
    </SettingsDisclosure>
  );
}
