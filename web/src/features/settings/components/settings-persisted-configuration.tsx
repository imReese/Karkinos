import type { SettingsPageController } from './settings-page-controller';
import {
  getErrorMessage,
  InlineNotice,
  RegisterRow,
  SettingsDisclosure,
  SettingsSection,
} from './settings-view-primitives';
import { formatPublicStatus } from '../../../shared/public-labels';
import { SettingsMetadataReadiness } from './settings-metadata-readiness';

export function SettingsPersistedConfiguration({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { copy } = controller;
  return (
    <div
      className="min-w-0"
      id="settings-persisted-configuration"
      data-testid="settings-persisted-configuration"
    >
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
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth',
      block: 'start',
    });
  };
  const cards = [
    {
      title: copy.settings.configGuideWebTitle,
      tag: locale === 'zh' ? '页面即时' : 'Instant',
      tagColor: 'text-[var(--app-success-text)]',
      detail: copy.settings.configGuideWebDetail,
      action: locale === 'zh' ? '跳转修改 ›' : 'Go to editor ›',
      target: 'settings-configuration-editor',
    },
    {
      title: copy.settings.configGuideJsonTitle,
      tag: 'config.json',
      tagColor: 'text-[var(--app-accent-text)]',
      detail: copy.settings.configGuideJsonDetail,
      action: locale === 'zh' ? '查看标的 ›' : 'View symbols ›',
      target: 'settings-metadata-disclosure',
    },
    {
      title: copy.settings.configGuideEnvTitle,
      tag: '.env',
      tagColor: 'text-[var(--app-warning-text)]',
      detail: copy.settings.configGuideEnvDetail,
      action: locale === 'zh' ? '安全与通知 ›' : 'Safety & alerts ›',
      target: 'settings-local-preferences-boundaries-disclosure',
    },
  ];

  return (
    <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-3.5 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-[var(--app-text)]">
          💡 {copy.settings.configGuideTitle}
        </span>
        <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2 py-0.5 font-semibold text-[var(--app-accent-text)]">
          {locale === 'zh' ? '配置说明' : 'Guide'}
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {cards.map((card) => (
          <div
            key={card.title}
            className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-3 flex flex-col justify-between gap-2"
          >
            <div>
              <div className="flex items-center justify-between gap-1">
                <span className="font-semibold text-[var(--app-text)]">
                  {card.title}
                </span>
                <span className={`app-type-micro font-mono ${card.tagColor}`}>
                  {card.tag}
                </span>
              </div>
              <p className="app-muted mt-1.5 text-xs leading-5">
                {card.detail}
              </p>
            </div>
            <button
              type="button"
              onClick={() => scrollTo(card.target)}
              className="app-link mt-1 self-start text-xs font-semibold"
            >
              {card.action}
            </button>
          </div>
        ))}
      </div>
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
    assetMetadataStatus,
    latestPersistentQuoteTime,
    metadataConfiguredCount,
    operationsRegisterRows,
    providerActionLabel,
    providerTimedOut,
  } = controller;
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth',
      block: 'start',
    });
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
            onClick={() => scrollTo('settings-configuration-editor')}
            className="app-button-secondary inline-flex min-h-8 items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
          >
            <span>{copy.settings.quickEditCosts}</span>
          </button>
          <button
            type="button"
            onClick={() => scrollTo('settings-metadata-disclosure')}
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
      {assetMetadataStatus.data &&
      !assetMetadataStatus.isError &&
      metadataConfiguredCount === 0 ? (
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

export function SettingsConfigurationEditor({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const { copy, locale } = controller;
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
      <SettingsAccountCostsForm controller={controller} />
      <SettingsProviderMeshForm controller={controller} />
    </SettingsDisclosure>
  );
}

function SettingsAccountCostsForm({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    accountCommissionChanged,
    accountCostsValid,
    accountCostsError,
    accountCommissionRate,
    accountMinCommission,
    copy,
    locale,
    setAccountCommissionRate,
    setAccountMinCommission,
    settings,
    submitAccountCommission,
    updateSettings,
  } = controller;

  const rate = Number(accountCommissionRate);
  const minCommission = Number(accountMinCommission);
  const previewAmounts = [5000, 50000, 100000];

  return (
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
          {locale === 'zh' ? '佣金计算：' : 'Commission calculation: '}
        </span>
        {locale === 'zh'
          ? '佣金取成交金额 × 佣金率与单笔最低佣金的较大值。请以券商实际费率为准；下方仅预览佣金，不包含税费。'
          : 'Commission is the greater of order value × rate and the minimum fee. Use your broker’s actual terms. These examples exclude tax and other fees.'}
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
            required
            step="0.00001"
            value={accountCommissionRate}
            onChange={(event) => setAccountCommissionRate(event.target.value)}
            disabled={
              !settings.data || settings.isError || updateSettings.isPending
            }
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
            required
            step="0.01"
            value={accountMinCommission}
            onChange={(event) => setAccountMinCommission(event.target.value)}
            disabled={
              !settings.data || settings.isError || updateSettings.isPending
            }
          />
        </label>
      </div>
      {accountCostsValid ? (
        <>
          <div className="app-muted text-xs leading-5">
            {copy.settings.accountCostPreview(rate, minCommission)}
          </div>
          <div
            className="grid gap-2 sm:grid-cols-3"
            aria-label={locale === 'zh' ? '佣金预览' : 'Commission preview'}
          >
            {previewAmounts.map((amount) => (
              <div
                key={amount}
                className="border-l-2 border-[var(--app-divider)] pl-3 py-1"
              >
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '成交金额' : 'Order value'} ¥
                  {amount.toLocaleString()}
                </div>
                <div className="mt-1 font-mono text-sm tabular-nums">
                  {locale === 'zh' ? '佣金' : 'Commission'} ¥
                  {Math.max(amount * rate, minCommission).toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}
      {accountCostsError ? (
        <p role="alert" className="text-xs text-[var(--app-danger-text)]">
          {accountCostsError}
        </p>
      ) : null}
      <button
        type="submit"
        className="app-button-primary min-h-10 w-fit justify-self-start rounded-[var(--app-radius-control)] px-3.5 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
        disabled={
          !settings.data ||
          settings.isError ||
          updateSettings.isPending ||
          !accountCostsValid ||
          !accountCommissionChanged
        }
        aria-busy={updateSettings.isPending}
      >
        {updateSettings.isPending
          ? copy.settings.savingAccountCosts
          : copy.settings.saveAccountCosts}
      </button>
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
    </form>
  );
}

function SettingsProviderMeshForm({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    copy,
    locale,
    settings,
    dataSourceStatus,
    marketHealth,
    dataSource,
    setDataSource,
    pollInterval,
    setPollInterval,
    dataSourceChanged,
    dataSettingsValid,
    dataSettingsError,
    updateDataSource,
    submitDataSource,
  } = controller;
  const disabled =
    !settings.data || settings.isError || updateDataSource.isPending;
  const providers = dataSourceStatus.data?.available_providers ?? [
    'akshare',
    'tushare',
  ];
  const configured = !dataSourceStatus.isError
    ? dataSourceStatus.data?.provider_configured
    : undefined;
  const health =
    !marketHealth.isError &&
    marketHealth.data &&
    marketHealth.data?.provider_name === dataSourceStatus.data?.provider_name
      ? marketHealth.data.source_health
      : null;

  return (
    <form
      onSubmit={submitDataSource}
      className="grid gap-4 border-t border-[var(--app-divider)] pt-4"
    >
      <div>
        <h3 className="text-sm font-semibold">
          {copy.settings.providerConfiguration}
        </h3>
        <p className="app-muted mt-1 text-xs leading-5">
          {copy.settings.providerConfigurationDetail}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.settings.selectDataSource}
          </span>
          <select
            name="data_source"
            value={dataSource}
            onChange={(event) => setDataSource(event.target.value)}
            disabled={disabled}
            required
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          >
            {providers.map((provider) => (
              <option key={provider} value={provider}>
                {provider === 'akshare'
                  ? copy.settings.providerAkshare
                  : provider === 'tushare'
                    ? copy.settings.providerTushare
                    : provider}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.settings.pollInterval} ({copy.settings.pollIntervalUnit})
          </span>
          <input
            name="live_poll_interval"
            type="number"
            min={15}
            step={1}
            required
            value={pollInterval}
            onChange={(event) => setPollInterval(event.target.value)}
            disabled={disabled}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
          />
        </label>
      </div>
      <div className="grid gap-x-6 sm:grid-cols-2">
        <RegisterRow
          label={copy.settings.providerConfigured}
          value={
            configured === undefined
              ? copy.shell.statusUnknown
              : configured
                ? copy.settings.yes
                : copy.settings.no
          }
          tone={
            configured === true
              ? 'success'
              : configured === false
                ? 'warning'
                : 'neutral'
          }
        />
        <RegisterRow
          label={
            locale === 'zh'
              ? '已保存行情源的数据状态'
              : 'Saved source data state'
          }
          value={
            health
              ? formatPublicStatus(
                  health === 'live' ? 'healthy' : health,
                  locale,
                )
              : copy.shell.statusUnknown
          }
          tone={health === 'live' ? 'success' : health ? 'warning' : 'neutral'}
        />
      </div>
      <p className="app-muted text-xs leading-5">
        {locale === 'zh'
          ? '上述状态来自已保存配置与最近的行情证据；候选数据通道、凭据配置或备用源不代表数据已核验。来源能力与权限请查看下方接口能力矩阵。'
          : 'These states describe the saved configuration and latest quote evidence. Candidate channels, configured credentials and fallback sources do not establish verified data. Review capabilities and permissions below.'}
      </p>
      {dataSource === 'tushare' && !settings.data?.tushare_token_configured ? (
        <InlineNotice
          tone="warning"
          title={copy.settings.credentialMissing}
          detail={copy.settings.credentialEnvironmentDetail}
        />
      ) : null}
      {dataSettingsError ? (
        <p role="alert" className="text-xs text-[var(--app-danger-text)]">
          {dataSettingsError}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={
          disabled ||
          !dataSourceChanged ||
          !dataSettingsValid ||
          (dataSource === 'tushare' && !settings.data?.tushare_token_configured)
        }
        aria-busy={updateDataSource.isPending}
        className="app-button-primary min-h-10 w-fit rounded-[var(--app-radius-control)] px-3.5 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60 sm:min-h-8"
      >
        {updateDataSource.isPending
          ? copy.settings.savingDataSource
          : copy.settings.saveDataSource}
      </button>
      {updateDataSource.isSuccess ? (
        <InlineNotice
          tone="success"
          title={copy.settings.dataSourceSaved}
          detail={copy.settings.providerConfigurationDetail}
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
    </form>
  );
}
