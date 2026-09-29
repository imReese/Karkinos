import { useMemo, useState } from 'react';

import type { SettingsPageController } from './settings-page-controller';
import {
  BeaconDot,
  type BeaconTone,
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
  const scrollTo = (id: string) => {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    latestPersistentQuoteTime,
    metadataConfiguredCount,
    operationsRegisterRows,
    providerActionLabel,
    providerTimedOut,
  } = controller;
  const scrollTo = (id: string) => {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

  const costTiers = [
    {
      label: locale === 'zh' ? '小额调仓 (¥10,000)' : 'Small order (¥10,000)',
      amount: 10000,
    },
    {
      label: locale === 'zh' ? '中额建仓 (¥50,000)' : 'Medium order (¥50,000)',
      amount: 50000,
    },
    {
      label:
        locale === 'zh' ? '大额再平衡 (¥100,000)' : 'Large order (¥100,000)',
      amount: 100000,
    },
  ];

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
          {locale === 'zh' ? '💡 费率设置说明：' : '💡 Commission guide: '}
        </span>
        {locale === 'zh'
          ? '常规 A 股佣金通常为万 1 (0.0001) 至万 2.5 (0.00025)；单笔最低佣金通常为 5 元（免五政策可填 0）。修改后点击【保存账户成本】即刻生效。'
          : 'Standard A-share commission is 1 to 2.5 bp (0.0001 to 0.00025); minimum commission is ¥5.'}
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
        {costTiers.map((tier) => {
          const raw = tier.amount * (Number(accountCommissionRate) || 0);
          const min = Number(accountMinCommission) || 0;
          const fee = Math.max(raw, min);
          return (
            <div
              key={tier.amount}
              className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-2.5"
            >
              <div className="app-type-micro text-[var(--app-muted)]">
                {tier.label}
              </div>
              <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-[var(--app-text)]">
                ¥{fee.toFixed(2)}
                {raw < min ? (
                  <span className="ml-1 app-type-micro font-normal text-[var(--app-warning-text)]">
                    {locale === 'zh' ? '(最低佣金)' : '(min fee)'}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <button
        type="submit"
        className="app-button-primary w-fit justify-self-start rounded-[var(--app-radius-control)] px-3.5 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
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
  const { copy, locale, marketHealth, settings } = controller;

  const providers = [
    {
      name: 'Tencent / AKShare',
      badge: locale === 'zh' ? '开源直连 · 就绪' : 'Ready',
      detail:
        locale === 'zh'
          ? 'A 股分时秒级报价与分笔数据。直连腾讯接口与 AKShare 底层通道，免鉴权即用。'
          : 'Realtime quotes and tick snapshots. Open access, no rate limits.',
      role: locale === 'zh' ? '职责：分时秒级 · 盘中实时' : 'upstream: tencent',
      tone: 'success',
    },
    {
      name: 'BaoStock',
      badge: locale === 'zh' ? '核验基准 · 就绪' : 'Benchmark',
      detail:
        locale === 'zh'
          ? '高精度 A 股未复权日线。与腾讯/TuShare 构成双独立上游对账基准，生成核验证据。'
          : 'Unadjusted daily bars benchmark. Forms primary independent upstream for reconciliation.',
      role:
        locale === 'zh' ? '职责：历史日线 · 双源核验' : 'upstream: baostock',
      tone: 'success',
    },
    {
      name: 'TuShare Pro',
      badge: settings.data?.tushare_token_configured
        ? locale === 'zh'
          ? '已接入 · 参与对账'
          : 'Connected'
        : locale === 'zh'
          ? '专业源 · 需 .env'
          : 'Needs Token',
      detail:
        locale === 'zh'
          ? '专业金融数据平台。提供深度财务分红，并参与日线双独立上游交叉核验（与 BaoStock 对账）。'
          : 'Professional financial platform. Fundamental ratios and daily bar reconciliation.',
      role: locale === 'zh' ? '职责：财务分红 · 交叉对账' : 'upstream: tushare',
      tone: settings.data?.tushare_token_configured ? 'success' : 'neutral',
    },
    {
      name: 'Eastmoney',
      badge: locale === 'zh' ? '天天基金 · 兜底' : 'Fallback',
      detail:
        locale === 'zh'
          ? '东方财富天天基金接口。当 TuShare 账号缺少公募基金权限时，系统自动无缝接管盘中估值与净值。'
          : 'Eastmoney fund feed. Seamlessly takes over fund estimates when TuShare lacks fund access.',
      role:
        locale === 'zh' ? '职责：公募估值 · 行业元数据' : 'upstream: eastmoney',
      tone: 'success',
    },
    {
      name: 'TDX 通达信',
      badge: locale === 'zh' ? '直连协议 · 就绪' : 'Builtin',
      detail:
        locale === 'zh'
          ? '直连行情服务器高速通道。支持 tdxaidata 协议的高频日线与分笔回放摄取，作为备用高吞吐通道。'
          : 'Direct feed server connection. Supports tdxaidata for high-throughput bar ingestion.',
      role: locale === 'zh' ? '职责：直连通道 · 备用高频' : 'upstream: tdx',
      tone: 'success',
    },
  ];

  const scenarios = [
    {
      name: locale === 'zh' ? '📈 盘中秒级分时报价' : '📈 Intraday Quotes',
      primary: 'Tencent (qt.gtimg)',
      primaryTone: 'text-[var(--app-success-text)] font-semibold',
      mesh: 'AKShare',
      fallback: locale === 'zh' ? '自动切换备用接口' : 'Auto fallback',
      trait:
        locale === 'zh' ? '免鉴权 · 极速毫秒级' : 'No token · fast response',
    },
    {
      name:
        locale === 'zh'
          ? '📊 未复权历史日线对账'
          : '📊 Daily Bars Reconciliation',
      primary: 'BaoStock (独立源 A)',
      primaryTone: 'text-[var(--app-accent-text)] font-semibold',
      mesh: 'Tencent / TuShare / TDX (独立源 B)',
      fallback:
        locale === 'zh' ? '双源比对不一致时阻断' : 'Fail-closed on mismatch',
      fallbackTone: 'text-[var(--app-warning-text)]',
      trait:
        locale === 'zh' ? '强制双独立上游核验' : 'Dual upstream verification',
    },
    {
      name:
        locale === 'zh' ? '🏦 公募基金净值与估值' : '🏦 Fund NAV & Estimates',
      primary: settings.data?.tushare_token_configured
        ? 'TuShare Pro'
        : '天天基金 Eastmoney',
      primaryTone: 'text-[var(--app-soft)] font-semibold',
      mesh: '天天基金 Eastmoney',
      fallback: locale === 'zh' ? '东财自动无缝接管' : 'Eastmoney takeover',
      fallbackTone: 'text-[var(--app-success-text)]',
      trait: locale === 'zh' ? '零配置无权限门槛' : 'Zero-config fallback',
    },
    {
      name:
        locale === 'zh' ? '📅 证券主数据与交易日历' : '📅 Master & Calendar',
      primary: 'AKShare',
      primaryTone: 'text-[var(--app-soft)] font-semibold',
      mesh: 'TuShare Pro',
      fallback: locale === 'zh' ? '本地落盘快照兜底' : 'Local snapshot',
      trait: locale === 'zh' ? '自动互补同步' : 'Mutual complement',
    },
  ];

  return (
    <div
      className="grid gap-4 border-y border-[var(--app-divider)] py-4"
      data-settings-surface="flat"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">
            {copy.settings.providerConfiguration}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-success-border)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] px-2 py-0.5 text-xs font-semibold text-[var(--app-success-text)]">
            <BeaconDot
              tone={
                marketHealth.data?.source_health === 'live'
                  ? 'success'
                  : 'warning'
              }
              ariaLabel="多源总线实时心跳"
              pulse
            />
            <span>{locale === 'zh' ? '多源协同心跳活跃' : 'Mesh Live'}</span>
          </span>
        </div>
        <div className="app-muted text-xs leading-5">
          {copy.settings.providerConfigurationDetail}
        </div>
      </div>

      <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3 text-xs leading-5 text-[var(--app-soft)]">
        <span className="font-semibold text-[var(--app-text)]">
          {locale === 'zh'
            ? '💡 5 大上游数据源协同网络（MarketSourcePolicy）：'
            : '💡 Upstream Provider Mesh: '}
        </span>
        {locale === 'zh'
          ? 'Karkinos 接入 Tencent、BaoStock、TuShare、Eastmoney 与 TDX 等多个独立上游通道。日线生成时要求双独立上游（如 BaoStock + Tencent/TuShare）交叉核验一致，公募基金由天天基金自动兜底；各数据源分工协同、互为校验。'
          : 'Karkinos routes across Tencent, BaoStock, TuShare, Eastmoney, and TDX upstreams. Daily bars require dual independent verification, and fund NAV automatically falls back to Eastmoney.'}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 text-xs leading-5">
        {providers.map((p) => (
          <div
            key={p.name}
            className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_6%,transparent)] p-2.5 flex flex-col justify-between gap-1.5"
          >
            <div>
              <div className="flex items-center justify-between gap-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  <BeaconDot
                    tone={p.tone as BeaconTone}
                    ariaLabel={`${p.name}: ${p.badge}`}
                    pulse={p.tone === 'success'}
                  />
                  <span className="font-semibold text-[var(--app-text)] truncate">
                    {p.name}
                  </span>
                </div>
                <span
                  className={`app-type-micro shrink-0 rounded border px-1.5 py-0.5 font-semibold ${p.tone === 'success' ? 'border-[var(--app-success-border)] text-[var(--app-success-text)]' : 'border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] text-[var(--app-soft)]'}`}
                >
                  {p.badge}
                </span>
              </div>
              <p className="app-muted mt-1">{p.detail}</p>
            </div>
            <div className="app-type-micro font-mono text-[var(--app-muted)]">
              {p.role}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '分场景多源协同与核验策略'
              : 'Scenario Routing & Verification Mesh'}
          </span>
          <span className="app-type-micro font-mono text-[var(--app-muted)]">
            MarketSourcePolicy: FREE_CN_RESEARCH_V1
          </span>
        </div>
        <div className="overflow-x-auto rounded-[var(--app-radius-control)] border border-[var(--app-divider)]">
          <table className="w-full text-left text-xs">
            <thead className="bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] text-[var(--app-soft)] border-b border-[var(--app-divider)]">
              <tr>
                <th className="px-3 py-2 font-semibold">
                  {locale === 'zh' ? '投研与交易场景' : 'Scenario'}
                </th>
                <th className="px-3 py-2 font-semibold">
                  {locale === 'zh' ? '主发通道' : 'Primary Source'}
                </th>
                <th className="px-3 py-2 font-semibold">
                  {locale === 'zh'
                    ? '协同 / 交叉核验源'
                    : 'Verification / Mesh'}
                </th>
                <th className="px-3 py-2 font-semibold">
                  {locale === 'zh' ? '故障自动兜底' : 'Fallback Policy'}
                </th>
                <th className="px-3 py-2 font-semibold">
                  {locale === 'zh' ? '数据特性' : 'Characteristics'}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--app-divider)] text-[var(--app-text)]">
              {scenarios.map((s) => (
                <tr key={s.name}>
                  <td className="px-3 py-2 font-medium">{s.name}</td>
                  <td className={`px-3 py-2 font-mono ${s.primaryTone}`}>
                    <span className="inline-flex items-center gap-1.5">
                      <BeaconDot
                        tone="success"
                        ariaLabel={`${s.primary} 通道正常`}
                        pulse
                      />
                      <span>{s.primary}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-[var(--app-soft)]">
                    {s.mesh}
                  </td>
                  <td
                    className={`px-3 py-2 ${s.fallbackTone || 'text-[var(--app-muted)]'}`}
                  >
                    {s.fallback}
                  </td>
                  <td className="px-3 py-2 text-[var(--app-muted)]">
                    {s.trait}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
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
    settings,
  } = controller;
  const [snippetCopied, setSnippetCopied] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [classFilter, setClassFilter] = useState<'all' | 'stock' | 'fund'>(
    'all',
  );
  const [expanded, setExpanded] = useState(false);

  type TrackedAssetItem = {
    symbol: string;
    display_name?: string | null;
    asset_class?: string | null;
  };

  const configuredAssets: readonly TrackedAssetItem[] = assetMetadataStatus.data
    ?.configured_assets?.length
    ? assetMetadataStatus.data.configured_assets
    : (settings.data?.assets ?? []);

  const stockCount = useMemo(
    () => configuredAssets.filter((a) => a.asset_class === 'stock').length,
    [configuredAssets],
  );
  const fundCount = useMemo(
    () => configuredAssets.filter((a) => a.asset_class === 'fund').length,
    [configuredAssets],
  );

  const filteredAssets = useMemo(() => {
    let list: readonly TrackedAssetItem[] = configuredAssets;
    if (classFilter !== 'all') {
      list = list.filter((a) => a.asset_class === classFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      list = list.filter(
        (a) =>
          a.symbol.toLowerCase().includes(q) ||
          Boolean(a.display_name && a.display_name.toLowerCase().includes(q)),
      );
    }
    return list;
  }, [configuredAssets, classFilter, searchQuery]);

  const INITIAL_LIMIT = 24;
  const isSearching = searchQuery.trim().length > 0;
  const visibleAssets =
    isSearching || expanded
      ? filteredAssets
      : filteredAssets.slice(0, INITIAL_LIMIT);
  const hasMore = !isSearching && filteredAssets.length > INITIAL_LIMIT;

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
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--app-text)]">
              {locale === 'zh' ? '当前已追踪自选标的池' : 'Tracked Asset Pool'}
            </span>
            <span className="app-type-micro font-mono text-[var(--app-muted)]">
              {configuredAssets.length} {locale === 'zh' ? '标的' : 'symbols'}
            </span>
          </div>
          {hasMore || expanded ? (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="app-link text-xs font-semibold"
            >
              {expanded
                ? locale === 'zh'
                  ? '收起标的列表 ▴'
                  : 'Collapse ▴'
                : locale === 'zh'
                  ? `展开全部 (+${filteredAssets.length - INITIAL_LIMIT} 标的) ▾`
                  : `Show all (+${filteredAssets.length - INITIAL_LIMIT}) ▾`}
            </button>
          ) : null}
        </div>

        {configuredAssets.length > 8 ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-2">
            <div className="relative min-w-44 max-w-xs flex-1">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={
                  locale === 'zh'
                    ? '搜索代码或名称（如 600519、茅台）...'
                    : 'Search code or name...'
                }
                className="app-field w-full rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs"
              />
              {searchQuery ? (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-[var(--app-muted)] hover:text-[var(--app-text)]"
                >
                  ✕
                </button>
              ) : null}
            </div>

            <div className="inline-flex items-center rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-0.5">
              {[
                [
                  'all',
                  locale === 'zh'
                    ? `全部 (${configuredAssets.length})`
                    : `All (${configuredAssets.length})`,
                ],
                [
                  'stock',
                  locale === 'zh'
                    ? `A股 (${stockCount})`
                    : `Stock (${stockCount})`,
                ],
                [
                  'fund',
                  locale === 'zh'
                    ? `基金 (${fundCount})`
                    : `Fund (${fundCount})`,
                ],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`rounded-[calc(var(--app-radius-control)-2px)] px-2.5 py-0.5 text-xs font-medium transition-all ${
                    classFilter === key
                      ? 'border border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent-text)]'
                      : 'border border-transparent text-[var(--app-soft)] hover:text-[var(--app-text)]'
                  }`}
                  onClick={() => setClassFilter(key as typeof classFilter)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {visibleAssets.length > 0 ? (
          <div
            className={`flex flex-wrap gap-2 ${expanded || isSearching ? 'max-h-72 overflow-y-auto overscroll-contain pr-1' : ''}`}
          >
            {visibleAssets.map((asset) => {
              const name =
                asset.display_name && asset.display_name !== asset.symbol
                  ? asset.display_name
                  : null;
              const isStock = asset.asset_class === 'stock';
              return (
                <div
                  key={asset.symbol}
                  className="inline-flex items-center gap-1.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-2.5 py-1 text-xs shadow-xs"
                >
                  <span className="font-mono font-bold text-[var(--app-text)]">
                    {asset.symbol}
                  </span>
                  {name ? (
                    <span className="font-medium text-[var(--app-accent-text)]">
                      {name}
                    </span>
                  ) : null}
                  <span
                    className={`app-type-micro rounded px-1.5 py-0.5 font-semibold ${
                      isStock
                        ? 'border border-[color-mix(in_srgb,var(--app-accent)_24%,transparent)] text-[var(--app-accent-text)]'
                        : 'border border-[color-mix(in_srgb,var(--app-success)_24%,transparent)] text-[var(--app-success-text)]'
                    }`}
                  >
                    {isStock
                      ? locale === 'zh'
                        ? 'A股'
                        : 'STOCK'
                      : locale === 'zh'
                        ? '基金'
                        : 'FUND'}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-[var(--app-radius-control)] border border-dashed border-[var(--app-divider)] p-3 text-xs text-[var(--app-muted)]">
            <span>
              {locale === 'zh'
                ? `未找到与 “${searchQuery}” 匹配的标的`
                : `No assets matching "${searchQuery}"`}
            </span>
            <button
              type="button"
              onClick={() => {
                setSearchQuery('');
                setClassFilter('all');
              }}
              className="app-link text-xs font-semibold"
            >
              {locale === 'zh' ? '重置筛选' : 'Reset filter'}
            </button>
          </div>
        )}

        {hasMore && !expanded ? (
          <div className="flex justify-center pt-1">
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="app-button-secondary inline-flex items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1 text-xs font-semibold"
            >
              <span>
                {locale === 'zh'
                  ? `展开更多标的（剩余 ${filteredAssets.length - INITIAL_LIMIT} 个）▾`
                  : `Show ${filteredAssets.length - INITIAL_LIMIT} more ▾`}
              </span>
            </button>
          </div>
        ) : null}
      </div>

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
