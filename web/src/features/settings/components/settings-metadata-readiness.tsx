import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { useCopy } from '../../../shared/i18n/context';
import { MetricStrip } from '../../../shared/ui/workbench';
import type { SettingsPageController } from './settings-page-controller';
import { InlineNotice, SettingsDisclosure } from './settings-view-primitives';

type TrackedAssetItem = {
  symbol: string;
  display_name?: string | null;
  asset_class?: string | null;
};

function TrackedAssetPool({
  configuredAssets,
  locale,
}: {
  configuredAssets: readonly TrackedAssetItem[];
  locale: string;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [classFilter, setClassFilter] = useState('all');
  const copy = useCopy();
  const [expanded, setExpanded] = useState(false);

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
            <span>
              {expanded
                ? locale === 'zh'
                  ? '收起标的列表'
                  : 'Collapse'
                : locale === 'zh'
                  ? `展开全部 (+${filteredAssets.length - INITIAL_LIMIT} 标的)`
                  : `Show all (+${filteredAssets.length - INITIAL_LIMIT})`}
            </span>
            {expanded ? (
              <ChevronUp
                size={12}
                className="shrink-0 opacity-70"
                aria-hidden="true"
              />
            ) : (
              <ChevronDown
                size={12}
                className="shrink-0 opacity-70"
                aria-hidden="true"
              />
            )}
          </button>
        ) : null}
      </div>

      {configuredAssets.length > 8 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-2">
          <div className="relative min-w-44 max-w-xs flex-1">
            <input
              type="text"
              aria-label={
                locale === 'zh'
                  ? '搜索标的代码或名称'
                  : 'Search asset code or name'
              }
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
                aria-label={locale === 'zh' ? '清空搜索' : 'Clear search'}
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
              ...Array.from(
                new Set(
                  configuredAssets.map(
                    (asset) => asset.asset_class ?? 'unknown',
                  ),
                ),
              ).map((assetClass) => [
                assetClass,
                `${formatAssetClassLabel(assetClass, copy.common)} (${configuredAssets.filter((asset) => (asset.asset_class ?? 'unknown') === assetClass).length})`,
              ]),
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`rounded-[calc(var(--app-radius-control)-2px)] px-2.5 py-0.5 text-xs font-medium transition-all ${
                  classFilter === key
                    ? 'border border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent-text)]'
                    : 'border border-transparent text-[var(--app-soft)] hover:text-[var(--app-text)]'
                }`}
                aria-pressed={classFilter === key}
                onClick={() => setClassFilter(key)}
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
                key={`${asset.symbol}-${asset.asset_class ?? 'unknown'}`}
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
                  {formatAssetClassLabel(asset.asset_class, copy.common)}
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
            className="app-button-secondary inline-flex items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
          >
            <span>
              {locale === 'zh'
                ? `展开更多标的（剩余 ${filteredAssets.length - INITIAL_LIMIT} 个）`
                : `Show ${filteredAssets.length - INITIAL_LIMIT} more`}
            </span>
            <ChevronDown
              size={12}
              className="shrink-0 opacity-70"
              aria-hidden="true"
            />
          </button>
        </div>
      ) : null}

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
    </div>
  );
}

export function SettingsMetadataReadiness({
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
  const [snippetCopyError, setSnippetCopyError] = useState(false);

  const configuredAssets: readonly TrackedAssetItem[] =
    assetMetadataStatus.data?.configured_assets ?? settings.data?.assets ?? [];
  const metadataUnavailable =
    assetMetadataStatus.isError || !assetMetadataStatus.data;

  return (
    <SettingsDisclosure
      testId="settings-metadata-disclosure"
      title={copy.settings.metadataReadiness}
      detail={copy.settings.metadataReadinessDetail}
      badge={
        <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2 py-0.5 font-semibold text-[var(--app-soft)]">
          {assetMetadataStatus.isLoading
            ? copy.shell.checking
            : metadataUnavailable
              ? copy.shell.statusUnknown
              : locale === 'zh'
                ? `${metadataConfiguredCount} 个已登记`
                : `${metadataConfiguredCount} mapped`}
        </span>
      }
    >
      <TrackedAssetPool configuredAssets={configuredAssets} locale={locale} />

      <MetricStrip
        ariaLabel={copy.settings.metadataReadiness}
        className="app-settings-metadata-strip"
        items={[
          {
            id: 'metadata-configured',
            label: copy.settings.metadataConfigured,
            value: assetMetadataStatus.isLoading
              ? copy.shell.checking
              : metadataUnavailable
                ? copy.shell.statusUnknown
                : metadataConfiguredCount,
            tone:
              !metadataUnavailable && metadataConfiguredCount === 0
                ? 'warning'
                : 'neutral',
          },
          {
            id: 'metadata-missing',
            label: copy.settings.assetMetadataMissingCount,
            value: assetMetadataStatus.isLoading
              ? copy.shell.checking
              : metadataUnavailable
                ? copy.shell.statusUnknown
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
      ) : metadataUnavailable ? (
        <InlineNotice
          tone="danger"
          title={copy.shell.statusUnknown}
          detail={
            locale === 'zh'
              ? '元数据状态无法读取，请重试后再核验覆盖范围。'
              : 'Metadata status could not be read. Retry before assessing coverage.'
          }
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
                onClick={async () => {
                  setSnippetCopied(false);
                  setSnippetCopyError(false);
                  try {
                    if (!navigator.clipboard?.writeText)
                      throw new Error('clipboard unavailable');
                    await navigator.clipboard.writeText(metadataSnippet);
                    setSnippetCopied(true);
                    setTimeout(() => setSnippetCopied(false), 2000);
                  } catch {
                    setSnippetCopyError(true);
                  }
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
            {snippetCopyError ? (
              <p role="alert" className="text-xs text-[var(--app-danger-text)]">
                {locale === 'zh'
                  ? '复制失败，请手动选择下方 JSON 复制。'
                  : 'Copy failed. Select and copy the JSON below.'}
              </p>
            ) : null}
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
