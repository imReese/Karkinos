import { useState } from 'react';

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
    <div className="min-w-0" data-testid="settings-persisted-configuration">
      <SettingsSection
        title={copy.settings.backendSettings}
        detail={copy.settings.persistedSettingsDetail}
      >
        <SettingsConfigurationGuide controller={controller} />
        <SettingsOperationsRegister controller={controller} />
        <SettingsConfigurationEditor controller={controller} />
        <SettingsMetadataReadiness controller={controller} />
      </SettingsSection>
    </div>
  );
}

function SettingsConfigurationGuide({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { copy, locale } = controller;
  const [guideExpanded, setGuideExpanded] = useState(false);

  const openDisclosure = (id: string) => {
    const el = document.getElementById(id);
    if (el instanceof HTMLDetailsElement) {
      el.open = true;
    }
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-3.5 sm:p-4 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--app-text)]">
            💡 {copy.settings.configGuideTitle}
          </span>
          <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2 py-0.5 font-semibold text-[var(--app-accent-text)]">
            {locale === 'zh' ? '配置说明' : 'Guide'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setGuideExpanded((prev) => !prev)}
          className="app-type-micro font-medium text-[var(--app-soft)] hover:text-[var(--app-accent)] transition-colors"
        >
          {guideExpanded
            ? locale === 'zh'
              ? '收起说明 ▴'
              : 'Hide details ▴'
            : locale === 'zh'
              ? '展开详细配置指南 ▾'
              : 'Show details ▾'}
        </button>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-3 flex flex-col justify-between gap-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="font-semibold text-[var(--app-text)]">
                {copy.settings.configGuideWebTitle}
              </span>
              <span className="app-type-micro font-mono text-[var(--app-success-text)]">
                {locale === 'zh' ? '页面即时' : 'Instant'}
              </span>
            </div>
            <p className="app-muted mt-1.5 text-xs leading-5">
              {copy.settings.configGuideWebDetail}
            </p>
          </div>
          <button
            type="button"
            onClick={() => openDisclosure('settings-configuration-editor')}
            className="app-link mt-1 self-start text-xs font-semibold"
          >
            {locale === 'zh' ? '跳转修改 ›' : 'Go to editor ›'}
          </button>
        </div>

        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-3 flex flex-col justify-between gap-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="font-semibold text-[var(--app-text)]">
                {copy.settings.configGuideJsonTitle}
              </span>
              <span className="app-type-micro font-mono text-[var(--app-accent-text)]">
                config.json
              </span>
            </div>
            <p className="app-muted mt-1.5 text-xs leading-5">
              {copy.settings.configGuideJsonDetail}
            </p>
          </div>
          <button
            type="button"
            onClick={() => openDisclosure('settings-metadata-disclosure')}
            className="app-link mt-1 self-start text-xs font-semibold"
          >
            {locale === 'zh' ? '查看标的 JSON ›' : 'View symbols ›'}
          </button>
        </div>

        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-3 flex flex-col justify-between gap-2">
          <div>
            <div className="flex items-center justify-between gap-1">
              <span className="font-semibold text-[var(--app-text)]">
                {copy.settings.configGuideEnvTitle}
              </span>
              <span className="app-type-micro font-mono text-[var(--app-warning-text)]">
                .env
              </span>
            </div>
            <p className="app-muted mt-1.5 text-xs leading-5">
              {copy.settings.configGuideEnvDetail}
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              openDisclosure('settings-local-preferences-boundaries-disclosure')
            }
            className="app-link mt-1 self-start text-xs font-semibold"
          >
            {locale === 'zh' ? '安全与通知 ›' : 'Safety & alerts ›'}
          </button>
        </div>
      </div>

      {guideExpanded ? (
        <div className="mt-3.5 pt-3 border-t border-[var(--app-divider)] space-y-2 text-xs leading-5 text-[var(--app-soft)]">
          <div className="font-semibold text-[var(--app-text)]">
            {locale === 'zh' ? '💡 常见配置问题速查' : '💡 Common Questions'}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-2.5">
              <span className="font-medium text-[var(--app-text)]">
                {locale === 'zh'
                  ? 'Q: 我该选哪个行情源？'
                  : 'Q: Which quote source should I choose?'}
              </span>
              <p className="app-muted mt-1">
                {locale === 'zh'
                  ? '推荐默认使用 AKShare。无需申请 Token 或付费，直接支持国内 A 股日线与实时分时行情。若需要精细的财务分红或专业量化数据，可选用 TuShare（需在 .env 配置凭据）。'
                  : 'AKShare is recommended by default. It requires no API token and provides free Chinese A-share data. TuShare is suited for advanced financial datasets and requires a token in .env.'}
              </p>
            </div>
            <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-2.5">
              <span className="font-medium text-[var(--app-text)]">
                {locale === 'zh'
                  ? 'Q: 佣金率和最低佣金有什么用？'
                  : 'Q: What are commission rates used for?'}
              </span>
              <p className="app-muted mt-1">
                {locale === 'zh'
                  ? '用于在交易记账时自动预填券商手续费，并用于策略回测与绩效分析中扣除真实交易摩擦。A 股券商常规佣金通常为万分之 1 至万分之 2.5，单笔最低通常为 5 元。'
                  : 'Commission rates prefill manual trade costs and account for transaction friction in portfolio backtesting. Standard A-share commissions range from 1 to 2.5 bp with a ¥5 minimum.'}
              </p>
            </div>
          </div>
        </div>
      ) : null}
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

  const openDisclosure = (id: string) => {
    const el = document.getElementById(id);
    if (el instanceof HTMLDetailsElement) {
      el.open = true;
    }
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

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
        <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
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
        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[var(--app-divider)]">
          <button
            type="button"
            onClick={() => openDisclosure('settings-configuration-editor')}
            className="app-button-secondary inline-flex min-h-8 items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
          >
            <span>{copy.settings.quickEditCosts}</span>
          </button>
          <button
            type="button"
            onClick={() => openDisclosure('settings-metadata-disclosure')}
            className="app-button-secondary inline-flex min-h-8 items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
          >
            <span>{copy.settings.quickMetadata}</span>
          </button>
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
    locale,
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
      badge={
        <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-accent)_36%,transparent)] bg-[var(--app-accent-ghost)] px-2 py-0.5 font-semibold text-[var(--app-accent-text)]">
          {locale === 'zh' ? '在线可编辑' : 'Editable'}
        </span>
      }
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
        <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3 text-xs leading-5 text-[var(--app-soft)]">
          <span className="font-semibold text-[var(--app-text)]">
            {locale === 'zh' ? '💡 费率设置说明：' : '💡 Commission guide: '}
          </span>
          {locale === 'zh'
            ? '常规 A 股佣金通常为万 1 (0.0001) 至万 2.5 (0.00025)；单笔最低佣金通常为 5 元（免五政策可填 0）。修改后点击【保存账户成本】即刻生效。'
            : 'Standard A-share commission is 1 to 2.5 bp (0.0001 to 0.00025); minimum commission is ¥5. Prefills manual trades and accounts for backtest friction.'}
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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1 text-xs">
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-2.5">
            <div className="app-type-micro text-[var(--app-muted)]">
              {controller.locale === 'zh'
                ? '小额调仓 (¥10,000)'
                : 'Small order (¥10,000)'}
            </div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-[var(--app-text)]">
              ¥
              {Math.max(
                10000 * (Number(accountCommissionRate) || 0),
                Number(accountMinCommission) || 0,
              ).toFixed(2)}
              {10000 * (Number(accountCommissionRate) || 0) <
              (Number(accountMinCommission) || 0) ? (
                <span className="ml-1 app-type-micro font-normal text-[var(--app-warning-text)]">
                  {controller.locale === 'zh' ? '(最低佣金)' : '(min fee)'}
                </span>
              ) : null}
            </div>
          </div>
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-2.5">
            <div className="app-type-micro text-[var(--app-muted)]">
              {controller.locale === 'zh'
                ? '中额建仓 (¥50,000)'
                : 'Medium order (¥50,000)'}
            </div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-[var(--app-text)]">
              ¥
              {Math.max(
                50000 * (Number(accountCommissionRate) || 0),
                Number(accountMinCommission) || 0,
              ).toFixed(2)}
            </div>
          </div>
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-2.5">
            <div className="app-type-micro text-[var(--app-muted)]">
              {controller.locale === 'zh'
                ? '大额再平衡 (¥100,000)'
                : 'Large order (¥100,000)'}
            </div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-[var(--app-text)]">
              ¥
              {Math.max(
                100000 * (Number(accountCommissionRate) || 0),
                Number(accountMinCommission) || 0,
              ).toFixed(2)}
            </div>
          </div>
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
        <div className="grid gap-2 sm:grid-cols-2 text-xs leading-5">
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_6%,transparent)] p-2.5">
            <div className="flex items-center gap-1.5 font-semibold text-[var(--app-text)]">
              <span>AKShare</span>
              <span className="app-type-micro rounded border border-[var(--app-success-border)] px-1.5 py-0.5 font-semibold text-[var(--app-success-text)]">
                {locale === 'zh' ? '推荐默认 · 免配置' : 'Recommended · Free'}
              </span>
            </div>
            <p className="app-muted mt-1">
              {locale === 'zh'
                ? '国内开源量化数据接口，无需 API Token，开箱即用。支持 A 股实时行情与历史日线。'
                : 'Free open-source market data, no API token required. Supports A-share realtime quotes and historical bars.'}
            </p>
          </div>
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_6%,transparent)] p-2.5">
            <div className="flex items-center gap-1.5 font-semibold text-[var(--app-text)]">
              <span>TuShare</span>
              <span className="app-type-micro rounded border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] px-1.5 py-0.5 font-semibold text-[var(--app-soft)]">
                {locale === 'zh' ? '专业源 · 需凭据' : 'Pro · Needs Token'}
              </span>
            </div>
            <p className="app-muted mt-1">
              {locale === 'zh'
                ? '专业金融数据平台，需在本地 .env 文件中配置 Token。支持更深度的财务、分红与分钟级数据。'
                : 'Professional financial dataset platform. Requires an API token configured in your local .env file.'}
            </p>
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
          <span className="app-muted text-xs leading-5">
            {locale === 'zh'
              ? '建议设置 30 ~ 60 秒，避免对公开数据接口发起过高频请求被封禁 IP。'
              : 'Recommended 30-60 seconds to avoid provider rate limits.'}
          </span>
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
    locale,
    metadataConfiguredCount,
    metadataSnippet,
    metadataSourceLabel,
    missingMetadataSymbols,
  } = controller;
  const [snippetCopied, setSnippetCopied] = useState(false);
  return (
    <SettingsDisclosure
      testId="settings-metadata-disclosure"
      title={copy.settings.metadataReadiness}
      detail={copy.settings.metadataReadinessDetail}
      badge={
        <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2 py-0.5 font-semibold text-[var(--app-soft)]">
          {locale === 'zh'
            ? `${metadataConfiguredCount} 个已登记`
            : `${metadataConfiguredCount} mapped`}
        </span>
      }
    >
      <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3 text-xs leading-5 text-[var(--app-soft)]">
        <span className="font-semibold text-[var(--app-text)]">
          {locale === 'zh'
            ? '💡 如何配置自选或监控标的？'
            : '💡 How to configure tracked assets?'}
        </span>
        <ol className="mt-1.5 list-decimal list-inside space-y-1 app-muted">
          <li>
            {locale === 'zh'
              ? '打开项目根目录下的 config.json 文件；'
              : 'Open config.json located at the project root;'}
          </li>
          <li>
            {locale === 'zh'
              ? '在 "assets" 数组中配置标的代码 (symbol)、分类 (stock/fund) 与中文名称 (display_name)；'
              : 'Add symbols, asset classes (stock/fund), and display names to the "assets" array;'}
          </li>
          <li>
            {locale === 'zh'
              ? '若页面检测到持仓中存在未命名的标的代码，可直接复制下方生成的建议 JSON 片段合并到 config.json 中。'
              : 'If unmapped holdings are detected, copy the generated JSON snippet below and merge it.'}
          </li>
        </ol>
      </div>
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
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">
                {copy.settings.assetMetadataSnippet}
              </span>
              <button
                type="button"
                className="app-button-secondary inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-mono font-medium"
                onClick={() => {
                  void navigator.clipboard?.writeText(metadataSnippet);
                  setSnippetCopied(true);
                  setTimeout(() => setSnippetCopied(false), 2000);
                }}
              >
                {snippetCopied
                  ? controller.locale === 'zh'
                    ? '✓ 已复制'
                    : '✓ Copied'
                  : controller.locale === 'zh'
                    ? '复制 JSON'
                    : 'Copy JSON'}
              </button>
            </div>
            <textarea
              className="app-field min-h-44 resize-y rounded-[var(--app-radius-control)] px-3 py-3 font-mono text-xs leading-5"
              readOnly
              aria-label={copy.settings.assetMetadataSnippet}
              value={metadataSnippet}
            />
            <span className="app-muted text-xs leading-5">
              {copy.settings.assetMetadataSnippetDetail}
            </span>
          </div>
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
