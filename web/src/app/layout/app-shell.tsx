import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type SVGProps,
} from 'react';

import { Link, useRouterState } from '@tanstack/react-router';

import { useAccountOverviewQuery } from '../../features/account/api';
import { useMarketDataHealthQuery } from '../../features/market/api';
import { useCopy } from '../copy';
import {
  usePreferences,
  type Locale,
  type ThemePreference,
} from '../preferences';
import { isUnconfirmedMarketDataStatus } from '../../shared/market-data-status';
import { formatPublicStatus } from '../../shared/public-labels';

const navGroups = [
  {
    key: 'portfolio',
    label: { en: 'Portfolio', zh: '组合管理' },
    items: [
      { to: '/', key: 'overview', icon: OverviewNavIcon },
      { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
      { to: '/activity', key: 'activity', icon: ActivityNavIcon },
      { to: '/market', key: 'market', icon: MarketNavIcon },
    ],
  },
  {
    key: 'research',
    label: { en: 'Research', zh: '研究' },
    items: [{ to: '/backtest', key: 'backtest', icon: BacktestNavIcon }],
  },
  {
    key: 'decision-risk',
    label: { en: 'Decision & Risk', zh: '决策与风控' },
    items: [
      { to: '/decision', key: 'decision', icon: DecisionNavIcon },
      { to: '/risk', key: 'risk', icon: RiskNavIcon },
    ],
  },
  {
    key: 'execution-operations',
    label: { en: 'Execution & Operations', zh: '执行与运营' },
    items: [
      { to: '/operations', key: 'operations', icon: OperationsNavIcon },
      { to: '/trading', key: 'trading', icon: TradingNavIcon },
    ],
  },
  {
    key: 'system',
    label: { en: 'System', zh: '系统' },
    items: [{ to: '/settings', key: 'settings', icon: SettingsNavIcon }],
  },
] as const;

const mobilePrimaryItems = [
  navGroups[0].items[0],
  navGroups[0].items[1],
  navGroups[2].items[0],
] as const;

type ToolbarStatusTone = 'success' | 'warning' | 'danger';
type ToolbarPopoverKey = 'valuation' | 'market' | null;
type ToolbarStatusIndicator = 'dot' | 'syncing';
const STATUS_COLORS: Record<ToolbarStatusTone, string> = {
  success: 'var(--app-success-indicator)',
  warning: 'var(--app-warning-indicator)',
  danger: 'var(--app-danger-indicator)',
};

function formatToolbarTimestamp(
  value: Date | string | null | undefined,
  locale: Locale,
) {
  if (!value) {
    return null;
  }
  if (typeof value === 'string') {
    const localClockTime = value.match(/T(\d{2}:\d{2})(?::\d{2})?/);
    if (localClockTime?.[1]) {
      return localClockTime[1];
    }
  }
  const timestamp = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const copy = useCopy();
  const accountOverview = useAccountOverviewQuery();
  const marketHealth = useMarketDataHealthQuery();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavExpanded, setDesktopNavExpanded] = useState(true);
  const [openStatusPanel, setOpenStatusPanel] =
    useState<ToolbarPopoverKey>(null);
  const statusRailRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!openStatusPanel) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!statusRailRef.current?.contains(event.target as Node)) {
        setOpenStatusPanel(null);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenStatusPanel(null);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);

    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [openStatusPanel]);

  const overview = accountOverview.data;
  const valuationTimestamp = formatToolbarTimestamp(
    overview?.valuation_timestamp,
    locale,
  );
  const isQuoteStale = overview?.quote_status === 'stale';
  const quoteStatus = overview?.quote_status
    ? formatPublicStatus(overview.quote_status, locale)
    : copy.shell.statusUnknown;
  const refreshPolicy = marketHealth.data?.refresh_policy
    ? formatPublicStatus(marketHealth.data.refresh_policy, locale)
    : copy.shell.statusUnknown;
  const marketOpenText =
    marketHealth.data?.market_open === undefined
      ? copy.shell.statusUnknown
      : marketHealth.data.market_open
        ? copy.shell.marketOpen
        : copy.shell.marketClosed;
  const marketQuotesHealthy =
    marketHealth.data?.source_health === 'live' ||
    marketHealth.data?.source_health === 'healthy';
  const marketQuotesUnconfirmed = isUnconfirmedMarketDataStatus(
    marketHealth.data?.source_health,
  );

  const valuationStatus = accountOverview.isLoading
    ? {
        value: copy.shell.checking,
        tone: 'warning' as ToolbarStatusTone,
        indicator: 'syncing' as ToolbarStatusIndicator,
      }
    : accountOverview.isError
      ? {
          value: copy.shell.valuationError,
          tone: 'danger' as ToolbarStatusTone,
          indicator: 'dot' as ToolbarStatusIndicator,
        }
      : isQuoteStale
        ? {
            value: copy.shell.valuationStale,
            tone: 'warning' as ToolbarStatusTone,
            indicator: 'dot' as ToolbarStatusIndicator,
          }
        : overview
          ? {
              value: copy.shell.valuationMode,
              tone: 'success' as ToolbarStatusTone,
              indicator: 'dot' as ToolbarStatusIndicator,
            }
          : {
              value: copy.shell.statusUnknown,
              tone: 'warning' as ToolbarStatusTone,
              indicator: 'dot' as ToolbarStatusIndicator,
            };

  const marketStatus = marketHealth.isLoading
    ? {
        value: copy.shell.checking,
        tone: 'warning' as ToolbarStatusTone,
        indicator: 'syncing' as ToolbarStatusIndicator,
      }
    : marketHealth.isError
      ? {
          value: copy.shell.marketError,
          tone: 'danger' as ToolbarStatusTone,
          indicator: 'dot' as ToolbarStatusIndicator,
        }
      : isQuoteStale || marketQuotesUnconfirmed
        ? {
            value: copy.shell.cachedQuotes,
            tone: 'warning' as ToolbarStatusTone,
            indicator: 'dot' as ToolbarStatusIndicator,
          }
        : marketHealth.data?.refresh_policy === 'cache_only'
          ? {
              value: marketHealth.data.market_open
                ? copy.shell.marketCacheOnly
                : copy.shell.marketClosed,
              tone:
                !marketHealth.data.market_open && marketQuotesHealthy
                  ? ('success' as ToolbarStatusTone)
                  : ('warning' as ToolbarStatusTone),
              indicator: 'dot' as ToolbarStatusIndicator,
            }
          : marketHealth.data
            ? {
                value: copy.shell.marketLive,
                tone: 'success' as ToolbarStatusTone,
                indicator: 'dot' as ToolbarStatusIndicator,
              }
            : {
                value: copy.shell.statusUnknown,
                tone: 'warning' as ToolbarStatusTone,
                indicator: 'dot' as ToolbarStatusIndicator,
              };

  const valuationMeta = valuationTimestamp
    ? copy.shell.valuationAt(valuationTimestamp)
    : undefined;
  const marketTimestamp = formatToolbarTimestamp(
    marketHealth.data?.latest_quote_timestamp ??
      marketHealth.data?.last_refresh_attempt,
    locale,
  );
  const activeNavigation = navGroups
    .flatMap((group) => group.items.map((item) => ({ group, item })))
    .find(({ item }) =>
      item.to === '/' ? pathname === '/' : pathname.startsWith(item.to),
    );

  return (
    <div className="app-root min-h-[100dvh] w-full">
      <div className="app-shell-frame flex h-[100dvh] min-h-[100dvh] w-full min-w-0">
        <div
          className={`fixed inset-0 z-[90] bg-[color-mix(in_srgb,var(--app-bg)_72%,transparent)] transition-opacity lg:hidden ${
            mobileNavOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
          }`}
          data-testid="mobile-navigation-backdrop"
          aria-hidden={!mobileNavOpen}
          onClick={() => setMobileNavOpen(false)}
        />

        <aside
          id="app-shell-navigation"
          className={`app-shell-sidebar fixed inset-y-0 left-0 z-[100] flex w-[min(84vw,280px)] flex-col border-r border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-3 transition-[width,transform] duration-200 lg:relative lg:h-full ${desktopNavExpanded ? 'lg:w-52' : 'lg:w-14'} lg:translate-x-0 ${
            mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <div
            className={`app-brand-lockup mb-4 flex min-h-10 items-center gap-2.5 px-1.5 ${desktopNavExpanded ? 'justify-between' : 'lg:justify-center'}`}
          >
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <span className="app-brand-glyph" aria-hidden="true">
                K
              </span>
              <div
                className={`min-w-0 ${desktopNavExpanded ? '' : 'lg:hidden'}`}
              >
                <div className="app-product-mark truncate whitespace-nowrap">
                  Karkinos
                </div>
                <div className="mt-1 truncate text-[10px] font-medium text-[var(--app-text-tertiary)]">
                  {copy.shell.workspaceLabel}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="app-button-secondary h-8 w-8 rounded-[var(--app-radius-control)] p-0 text-sm lg:hidden"
              aria-label={copy.shell.closeNavigation}
              onClick={() => setMobileNavOpen(false)}
            >
              ✕
            </button>
          </div>

          <nav
            className="min-h-0 flex-1 space-y-3 overflow-y-auto"
            aria-label={copy.shell.navigation}
          >
            {navGroups.map((group) => (
              <div key={group.key} className="grid gap-1">
                <div
                  className={`app-nav-group-label px-2 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)] ${desktopNavExpanded ? '' : 'lg:hidden'}`}
                >
                  {group.label[locale]}
                </div>
                {group.items.map((item) => {
                  const active =
                    item.to === '/'
                      ? pathname === '/'
                      : pathname.startsWith(item.to);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      onClick={() => setMobileNavOpen(false)}
                      data-testid={`sidebar-nav-${item.key}`}
                      title={
                        desktopNavExpanded
                          ? undefined
                          : copy.shell.nav[item.key]
                      }
                      className={`app-nav-item min-h-9 rounded-[var(--app-radius-control)] px-2 py-2 text-sm font-medium ${!desktopNavExpanded ? 'lg:justify-center lg:px-0' : ''} ${
                        active ? 'app-nav-item-active' : ''
                      }`}
                    >
                      <span
                        className="app-nav-active-rail"
                        aria-hidden="true"
                      />
                      <Icon
                        data-testid={`sidebar-nav-${item.key}-icon`}
                        className="app-nav-icon h-4 w-4 shrink-0"
                        aria-hidden="true"
                      />
                      <span
                        className={`truncate ${desktopNavExpanded ? '' : 'lg:hidden'}`}
                      >
                        {copy.shell.nav[item.key]}
                      </span>
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="mt-3 hidden border-t border-[var(--app-divider)] pt-2 lg:grid">
            <button
              type="button"
              className={`app-nav-item min-h-9 rounded-[var(--app-radius-control)] px-2 py-2 text-sm font-medium text-[var(--app-text-secondary)] ${!desktopNavExpanded ? 'lg:justify-center lg:px-0' : ''}`}
              onClick={() => setDesktopNavExpanded(!desktopNavExpanded)}
              aria-label={
                desktopNavExpanded
                  ? copy.shell.closeNavigation
                  : copy.shell.openNavigation
              }
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`app-nav-icon h-4 w-4 shrink-0 transition-transform duration-200 ${desktopNavExpanded ? '' : 'rotate-180'}`}
              >
                <path d="M15 18l-6-6 6-6" />
              </svg>
              <span
                className={`truncate ${desktopNavExpanded ? '' : 'lg:hidden'}`}
              >
                {copy.shell.closeNavigation}
              </span>
            </button>
          </div>
        </aside>

        <main className="app-shell-main relative flex min-w-0 flex-1 flex-col">
          <header className="app-toolbar-shell relative z-[80] shrink-0 overflow-visible border-b border-[var(--app-divider)] bg-[var(--app-surface-raised)]">
            <div className="flex h-12 items-center gap-3 px-3 sm:px-4">
              <button
                type="button"
                className="app-button-secondary inline-flex h-8 w-8 items-center justify-center rounded-[var(--app-radius-control)] p-0 text-sm lg:hidden"
                data-testid="mobile-navigation-toggle"
                aria-label={
                  mobileNavOpen
                    ? copy.shell.closeNavigation
                    : copy.shell.openNavigation
                }
                aria-controls="app-shell-navigation"
                aria-expanded={mobileNavOpen}
                onClick={() => setMobileNavOpen((open) => !open)}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden="true"
                  className="h-4 w-4"
                  data-testid="mobile-navigation-icon"
                >
                  <path d="M4 7h16" />
                  <path d="M4 12h16" />
                  <path d="M4 17h16" />
                </svg>
              </button>

              <div className="app-toolbar-brand min-w-0 shrink-0 items-center gap-2 lg:hidden">
                <span
                  className="app-brand-glyph app-brand-glyph-compact"
                  aria-hidden="true"
                >
                  K
                </span>
                <span className="app-product-mark truncate">Karkinos</span>
              </div>

              <div
                className="app-toolbar-context hidden min-w-0 flex-1 items-center gap-2 lg:flex"
                role="group"
                aria-label={copy.shell.currentWorkspace}
              >
                <span className="truncate text-[11px] font-semibold text-[var(--app-text-tertiary)]">
                  {activeNavigation?.group.label[locale] ?? copy.shell.title}
                </span>
                <span className="text-[var(--app-divider)]" aria-hidden="true">
                  /
                </span>
                <span className="truncate text-[13px] font-semibold text-[var(--app-text)]">
                  {activeNavigation
                    ? copy.shell.nav[activeNavigation.item.key]
                    : copy.shell.title}
                </span>
              </div>

              <div className="ml-auto flex min-w-0 shrink-0 flex-row items-center justify-end whitespace-nowrap">
                <div className="flex min-w-0 flex-row items-center gap-2">
                  <ThemeSwitcher
                    label={copy.shell.theme}
                    value={theme}
                    onChange={(value) => setTheme(value as ThemePreference)}
                    options={[
                      {
                        value: 'system',
                        label: copy.shell.systemThemeLabel,
                        icon: SystemThemeIcon,
                      },
                      {
                        value: 'light',
                        label: copy.shell.lightThemeLabel,
                        icon: LightThemeIcon,
                      },
                      {
                        value: 'dark',
                        label: copy.shell.darkThemeLabel,
                        icon: DarkThemeIcon,
                      },
                    ]}
                  />
                  <LanguageMenu
                    label={copy.shell.language}
                    value={locale}
                    onChange={(value) => setLocale(value as Locale)}
                  />
                </div>
              </div>
            </div>
          </header>

          <div className="app-shell-content min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto [contain:layout_paint]">
            <div className="w-full min-w-0 px-3 py-3 sm:px-4 sm:py-4 lg:px-5 lg:py-5 xl:px-6">
              {children}
            </div>
          </div>

          <div
            ref={statusRailRef}
            className="app-status-footer relative z-[80] hidden h-10 shrink-0 items-center gap-2 overflow-visible border-t border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-3 lg:flex"
            aria-label={copy.shell.accountStatus}
          >
            <div className="app-status-rail flex min-w-0 flex-1 flex-row flex-nowrap items-center gap-2 overflow-visible">
              <StatusChip
                testId="status-pill-valuation"
                label={copy.shell.navStatus}
                value={valuationStatus.value}
                meta={valuationTimestamp ?? undefined}
                tone={valuationStatus.tone}
                indicator={valuationStatus.indicator}
                hoverHint={copy.shell.viewValuationDetails}
                expanded={openStatusPanel === 'valuation'}
                popupPlacement="top"
                title={`${copy.shell.navStatus}: ${valuationStatus.value}${
                  valuationMeta ? ` · ${valuationMeta}` : ''
                }`}
                popup={
                  <StatusPopover
                    title={copy.shell.navStatus}
                    rows={[
                      {
                        label: copy.shell.valuationUpdated,
                        value: valuationMeta ?? copy.shell.statusUnknown,
                      },
                      {
                        label: copy.shell.quoteStatus,
                        value: quoteStatus,
                      },
                    ]}
                  />
                }
                onClick={() =>
                  setOpenStatusPanel((current) =>
                    current === 'valuation' ? null : 'valuation',
                  )
                }
              />
              <StatusChip
                testId="status-pill-market"
                label={copy.shell.marketStatus}
                value={marketStatus.value}
                meta={marketTimestamp ?? undefined}
                tone={marketStatus.tone}
                indicator={marketStatus.indicator}
                hoverHint={copy.shell.viewStatusDetails}
                expanded={openStatusPanel === 'market'}
                popupPlacement="top"
                title={`${copy.shell.marketStatus}: ${marketStatus.value}${
                  marketTimestamp ? ` · ${marketTimestamp}` : ''
                }`}
                popup={
                  <StatusPopover
                    title={copy.shell.marketStatus}
                    rows={[
                      {
                        label: copy.shell.marketSession,
                        value: marketOpenText,
                      },
                      {
                        label: copy.shell.refreshPolicy,
                        value: refreshPolicy,
                      },
                      {
                        label: copy.shell.quoteStatus,
                        value: quoteStatus,
                      },
                    ]}
                  />
                }
                onClick={() =>
                  setOpenStatusPanel((current) =>
                    current === 'market' ? null : 'market',
                  )
                }
              />
            </div>
            <div className="flex shrink-0 items-center gap-2 text-[11px] font-medium text-[var(--app-text-tertiary)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-info-indicator)]" />
              {copy.shell.persistedEvidence}
            </div>
          </div>

          <nav
            className="app-mobile-primary-nav relative z-[80] grid shrink-0 grid-cols-4 border-t border-[var(--app-divider)] bg-[var(--app-surface-raised)] lg:hidden"
            aria-label={copy.shell.primaryNavigation}
          >
            {mobilePrimaryItems.map((item) => {
              const active =
                item.to === '/'
                  ? pathname === '/'
                  : pathname.startsWith(item.to);
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`app-mobile-primary-item ${
                    active ? 'app-mobile-primary-item-active' : ''
                  }`}
                  onClick={() => setMobileNavOpen(false)}
                >
                  <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                  <span>{copy.shell.nav[item.key]}</span>
                </Link>
              );
            })}
            <button
              type="button"
              className={`app-mobile-primary-item ${mobileNavOpen ? 'app-mobile-primary-item-active' : ''}`}
              aria-label={copy.shell.moreNavigation}
              aria-controls="app-shell-navigation"
              aria-expanded={mobileNavOpen}
              onClick={() => setMobileNavOpen((open) => !open)}
            >
              <MenuIcon className="h-[18px] w-[18px]" aria-hidden="true" />
              <span>{copy.shell.moreNavigation}</span>
            </button>
          </nav>
        </main>
      </div>
    </div>
  );
}

function LanguageMenu({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Locale;
  onChange: (value: Locale) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const currentLabel = value === 'zh' ? '中文' : 'English';

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);

    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative w-auto">
      <button
        type="button"
        className={`app-language-control inline-flex h-8 w-auto items-center gap-2 whitespace-nowrap rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-transparent px-2.5 text-xs font-semibold text-[var(--app-text-secondary)] transition-colors hover:border-[var(--app-accent-border)] hover:text-[var(--app-text)] ${
          open ? 'border-[var(--app-accent-border)] text-[var(--app-text)]' : ''
        }`}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <GlobeIcon className="h-3.5 w-3.5" />
        <span className="hidden min-w-max whitespace-nowrap sm:block">
          {currentLabel}
        </span>
      </button>
      {open ? (
        <div
          className="absolute right-0 top-[calc(100%+6px)] z-[60] min-w-max rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-1 shadow-[var(--app-shadow-overlay)]"
          role="menu"
          aria-label={label}
        >
          {(
            [
              ['en', 'English'],
              ['zh', '中文'],
            ] as const
          ).map(([nextValue, menuLabel]) => {
            const active = nextValue === value;
            return (
              <button
                key={nextValue}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className={`flex w-full min-w-max items-center justify-between gap-3 rounded-[var(--app-radius-control)] bg-transparent px-3 py-2 text-left text-xs font-medium text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-accent-bg)] hover:text-[var(--app-text)] ${
                  active ? 'text-[var(--app-text)]' : ''
                }`}
                onClick={() => {
                  onChange(nextValue as Locale);
                  setOpen(false);
                }}
              >
                <span>{menuLabel}</span>
                {active ? <CheckIcon className="h-3 w-3" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ThemeSwitcher({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: ThemePreference;
  onChange: (value: ThemePreference) => void;
  options: ReadonlyArray<{
    value: ThemePreference;
    label: string;
    icon: ComponentType<SVGProps<SVGSVGElement>>;
  }>;
}) {
  return (
    <div
      className="app-theme-switcher inline-flex h-8 flex-row items-center gap-0.5 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-transparent p-0.5"
      role="group"
      aria-label={label}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-label={option.label}
            aria-pressed={active}
            className={`app-theme-switcher-option inline-flex h-6 items-center justify-center rounded-[var(--app-radius-control)] px-1.5 text-[var(--app-text-secondary)] transition-colors hover:text-[var(--app-text)] sm:px-2 [&>svg]:h-3.5 [&>svg]:w-3.5 ${
              active ? 'bg-[var(--app-accent-bg)] text-[var(--app-accent)]' : ''
            }`}
            onClick={() => onChange(option.value)}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}

function SystemThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function LightThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function DarkThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3A7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function StatusChip({
  label,
  value,
  tone,
  indicator,
  onClick,
  actionLabel,
  hoverHint,
  title,
  meta,
  popup,
  popupPlacement = 'bottom',
  expanded = false,
  testId,
}: {
  label: string;
  value: string;
  tone: ToolbarStatusTone;
  indicator: ToolbarStatusIndicator;
  onClick: () => void;
  actionLabel?: string;
  hoverHint?: string;
  title?: string;
  meta?: string;
  popup?: ReactNode;
  popupPlacement?: 'top' | 'bottom';
  expanded?: boolean;
  testId?: string;
}) {
  return (
    <div className="app-status-chip group relative inline-flex h-8 w-[11.5rem] shrink-0">
      <button
        type="button"
        data-testid={testId}
        aria-label={
          actionLabel ? `${actionLabel}: ${value}` : `${label}: ${value}`
        }
        aria-expanded={popup ? expanded : undefined}
        aria-haspopup={popup ? 'dialog' : undefined}
        title={title ?? hoverHint}
        onClick={onClick}
        className={`inline-flex h-full w-full items-center overflow-hidden whitespace-nowrap rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-transparent text-xs text-[var(--app-text-secondary)] transition-colors hover:border-[var(--app-accent-border)] hover:text-[var(--app-text)] ${
          expanded
            ? 'border-[var(--app-accent-border)] text-[var(--app-text)]'
            : ''
        }`}
      >
        <span className="inline-flex h-full w-12 shrink-0 items-center justify-center border-r border-[var(--app-divider)] px-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--app-text-tertiary)]">
          {label}
        </span>
        <span className="inline-flex h-full min-w-0 flex-1 items-center gap-2 px-2.5 pr-7 tabular-nums">
          <span className="relative flex h-3.5 w-3.5 items-center justify-center">
            {indicator === 'syncing' ? (
              <RotateCwIcon
                className="h-3.5 w-3.5 animate-spin"
                color={STATUS_COLORS.warning}
                data-testid={testId ? `${testId}-indicator` : undefined}
              />
            ) : (
              <>
                <span
                  className="absolute inset-[2px] rounded-full"
                  style={{ backgroundColor: STATUS_COLORS[tone] }}
                  aria-hidden="true"
                  data-testid={testId ? `${testId}-indicator` : undefined}
                />
              </>
            )}
          </span>
          <span className="min-w-[4rem] max-w-[7rem] truncate text-[12px] font-semibold text-[var(--app-text)]">
            {value}
          </span>
          {meta ? (
            <span className="shrink-0 text-[11px] font-medium text-[var(--app-text-secondary)]">
              {meta}
            </span>
          ) : null}
          <ChevronDownIcon
            className="absolute right-2 h-3.5 w-3.5 shrink-0 text-[var(--app-text-tertiary)]"
            aria-hidden="true"
          />
        </span>
      </button>
      {hoverHint && !expanded ? (
        <div
          className={`pointer-events-none absolute left-1/2 z-[75] -translate-x-1/2 rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] px-2.5 py-1.5 text-xs text-[var(--app-text)] opacity-0 shadow-[var(--app-shadow-overlay)] transition-opacity duration-75 group-hover:opacity-100 group-focus-within:opacity-100 ${
            popupPlacement === 'top'
              ? 'bottom-[calc(100%+6px)]'
              : 'top-[calc(100%+6px)]'
          }`}
        >
          {hoverHint}
        </div>
      ) : null}
      {popup ? (
        <div
          className={`absolute right-0 z-[70] ${
            popupPlacement === 'top'
              ? 'bottom-[calc(100%+8px)]'
              : 'top-[calc(100%+8px)]'
          }`}
        >
          {expanded ? popup : null}
        </div>
      ) : null}
    </div>
  );
}

function StatusPopover({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string }>;
}) {
  return (
    <div
      className="min-w-[200px] rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3 shadow-[var(--app-shadow-overlay)]"
      role="dialog"
      aria-label={title}
    >
      <div className="mb-2 text-xs font-semibold tracking-[-0.01em] text-[var(--app-text)]">
        {title}
      </div>
      <div className="grid gap-2">
        {rows.map((row) => (
          <div
            key={`${row.label}-${row.value}`}
            className="flex items-center justify-between gap-4 text-xs"
          >
            <span className="text-[11px] font-medium text-[var(--app-text-tertiary)]">
              {row.label}
            </span>
            <span className="tabular-nums font-medium text-[var(--app-text)]">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function GlobeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a15.3 15.3 0 0 1 0 18" />
      <path d="M12 3a15.3 15.3 0 0 0 0 18" />
    </svg>
  );
}

function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function RotateCwIcon(props: SVGProps<SVGSVGElement> & { color?: string }) {
  const { color, ...rest } = props;

  return (
    <svg
      fill="none"
      stroke={color ?? 'currentColor'}
      strokeWidth="1.9"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    >
      <path d="M21 2v6h-6" />
      <path d="M3 22v-6h6" />
      <path d="M21 8a9 9 0 0 0-15.5-3.5L3 7" />
      <path d="M3 16a9 9 0 0 0 15.5 3.5L21 17" />
    </svg>
  );
}

function ChevronDownIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function MenuIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      {...props}
    >
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </svg>
  );
}

function OverviewNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6.5 10.5V20h11v-9.5" />
      <path d="M10 20v-5h4v5" />
    </svg>
  );
}

function PortfolioNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <rect x="4" y="6" width="16" height="13" rx="2" />
      <path d="M8 6V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v1" />
      <path d="M8 13h8" />
    </svg>
  );
}

function ActivityNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4 7h11" />
      <path d="M4 12h16" />
      <path d="M4 17h9" />
      <path d="m17 16 3 3 3-3" />
      <path d="M20 9v10" />
    </svg>
  );
}

function RiskNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M12 3 4.5 6v5.5c0 4.2 2.8 7.9 7.5 9.5 4.7-1.6 7.5-5.3 7.5-9.5V6L12 3Z" />
      <path d="M12 8v5" />
      <path d="M12 17h.01" />
    </svg>
  );
}

function DecisionNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M5 5h14v14H5z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
      <path d="m15 15 1.5 1.5L20 13" />
    </svg>
  );
}

function OperationsNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M8 9h8" />
      <path d="M8 13h3" />
      <path d="m14 15 1.5 1.5L19 13" />
    </svg>
  );
}

function MarketNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4 19h16" />
      <path d="M7 16v-5" />
      <path d="M12 16V6" />
      <path d="M17 16v-8" />
      <path d="m6 10 4-4 4 3 4-5" />
    </svg>
  );
}

function TradingNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M5 7h14" />
      <path d="M5 12h9" />
      <path d="M5 17h6" />
      <path d="m15.5 16.5 2 2 3.5-4" />
    </svg>
  );
}

function BacktestNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M4 19h16" />
      <path d="M6 15.5 10 12l3 2.4 5-6.4" />
      <path d="M7 6.5h10" />
      <path d="M7 9.5h5" />
    </svg>
  );
}

function SettingsNavIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.05.05a2 2 0 1 1-2.83 2.83l-.05-.05A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.6 19a1.7 1.7 0 0 0-1.88.34l-.05.05a2 2 0 1 1-2.83-2.83l.05-.05A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.6a1.7 1.7 0 0 0-.34-1.88l-.05-.05a2 2 0 1 1 2.83-2.83l.05.05A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 15.4 5a1.7 1.7 0 0 0 1.88-.34l.05-.05a2 2 0 1 1 2.83 2.83l-.05.05A1.7 1.7 0 0 0 19.4 9c.2.38.52.7.9.9.33.18.7.27 1.1.27h.1a2 2 0 1 1 0 4h-.1c-.4 0-.77.09-1.1.27-.38.2-.7.52-.9.9Z" />
    </svg>
  );
}
