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
import {
  useMarketDataHealthQuery,
  useRefreshMarketQuotesMutation,
} from '../../features/market/api';
import { useCopy } from '../copy';
import {
  usePreferences,
  type Locale,
  type ThemePreference,
} from '../preferences';
import { isUnconfirmedMarketDataStatus } from '../../shared/market-data-status';
import { formatPublicStatus } from '../../shared/public-labels';

const navItems = [
  { to: '/', key: 'overview', icon: OverviewNavIcon },
  { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
  { to: '/activity', key: 'activity', icon: ActivityNavIcon },
  { to: '/market', key: 'market', icon: MarketNavIcon },
  { to: '/backtest', key: 'backtest', icon: BacktestNavIcon },
  { to: '/risk', key: 'risk', icon: RiskNavIcon },
  { to: '/decision', key: 'decision', icon: DecisionNavIcon },
  { to: '/operations', key: 'operations', icon: OperationsNavIcon },
  { to: '/trading', key: 'trading', icon: TradingNavIcon },
  { to: '/settings', key: 'settings', icon: SettingsNavIcon },
] as const;

type ToolbarStatusTone = 'success' | 'warning' | 'error';
type ToolbarPopoverKey = 'valuation' | 'market' | null;
type ToolbarStatusIndicator = 'dot' | 'syncing';
type ToolbarStatusAffordance = 'resync' | 'details';

const STATUS_COLORS: Record<ToolbarStatusTone, string> = {
  success: 'var(--app-success)',
  warning: 'var(--app-warning)',
  error: 'var(--app-danger)',
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
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavExpanded, setDesktopNavExpanded] = useState(false);
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
          tone: 'error' as ToolbarStatusTone,
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
          tone: 'error' as ToolbarStatusTone,
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

  return (
    <div className="app-root min-h-[100dvh] w-full">
      <div className="app-shell-frame flex h-[100dvh] min-h-[100dvh] min-w-0 w-full">
        <div
          className={`fixed inset-0 z-[90] bg-[color-mix(in_srgb,var(--app-mantle)_54%,transparent)] transition lg:hidden ${
            mobileNavOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
          }`}
          data-testid="mobile-navigation-backdrop"
          aria-hidden={!mobileNavOpen}
          onClick={() => setMobileNavOpen(false)}
        />

        <aside
          id="app-shell-navigation"
          className={`app-shell-sidebar fixed inset-y-0 left-0 z-[100] flex w-[min(84vw,320px)] flex-col border-r border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[var(--app-mantle)] px-5 py-6 transition-[width,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] lg:relative lg:h-full ${desktopNavExpanded ? 'lg:w-[252px] lg:px-5' : 'lg:w-[68px] lg:px-3'} lg:translate-x-0 ${
            mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
          aria-label={copy.shell.navigation}
        >
          <div
            className={`mb-8 flex items-start gap-4 ${desktopNavExpanded ? 'justify-between' : 'lg:justify-center'}`}
          >
            <div
              className={`min-w-0 flex-1 space-y-2 ${desktopNavExpanded ? '' : 'lg:hidden'}`}
            >
              <div className="app-product-mark shrink-0 whitespace-nowrap font-semibold text-[10px]">
                Karkinos
              </div>
              <div className="app-shell-section-title tracking-[-0.035em]">
                {copy.shell.title}
              </div>
              <p
                className={`app-muted max-w-[14rem] text-xs leading-5 ${
                  locale === 'zh' ? 'font-medium' : ''
                }`}
              >
                {copy.shell.description}
              </p>
            </div>
            <button
              type="button"
              className="app-button-secondary rounded-2xl px-3 py-2 text-sm lg:hidden"
              aria-label={copy.shell.closeNavigation}
              onClick={() => setMobileNavOpen(false)}
            >
              ✕
            </button>
          </div>

          <nav className="grid gap-1.5">
            {navItems.map((item) => {
              const active = pathname === item.to;
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileNavOpen(false)}
                  data-testid={`sidebar-nav-${item.key}`}
                  className={`app-nav-item rounded-[18px] px-3 py-3 text-sm font-semibold ${!desktopNavExpanded ? 'lg:px-0 lg:justify-center' : ''} ${
                    active ? 'app-nav-item-active' : ''
                  }`}
                >
                  <span
                    className={`app-nav-active-rail ${desktopNavExpanded ? '' : 'lg:hidden'}`}
                    aria-hidden="true"
                  />
                  <Icon
                    data-testid={`sidebar-nav-${item.key}-icon`}
                    className="app-nav-icon h-5 w-5 shrink-0"
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
          </nav>
          <div className="mt-auto hidden lg:grid pt-6">
            <button
              type="button"
              className={`app-nav-item rounded-[18px] px-3 py-3 text-sm font-semibold text-[var(--app-subtext-0)] transition-colors hover:text-[var(--app-text)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] ${!desktopNavExpanded ? 'lg:px-0 lg:justify-center' : ''}`}
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
                className={`app-nav-icon h-5 w-5 shrink-0 transition-transform duration-300 ${desktopNavExpanded ? '' : 'rotate-180'}`}
              >
                <path d="M15 18l-6-6 6-6" />
              </svg>
              <span
                className={`truncate ${desktopNavExpanded ? '' : 'lg:hidden'}`}
              >
                {copy.shell.closeNavigation || '收起侧边栏'}
              </span>
            </button>
          </div>
        </aside>

        <main className="app-shell-main flex min-w-0 flex-1 flex-col relative">
          <header className="app-toolbar-shell absolute left-4 right-4 top-4 z-[80] shrink-0 overflow-visible rounded-[20px] border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-mantle)_95%,transparent)] shadow-lg backdrop-blur-xl">
            <div className="flex h-14 items-center gap-4 px-4 sm:px-5 lg:px-6">
              <div className="min-w-0 shrink-0">
                <div className="flex min-w-0 items-center gap-3.5">
                  <div className="app-product-mark shrink-0 whitespace-nowrap font-semibold text-[10px]">
                    Karkinos
                  </div>
                  <div
                    className="hidden h-4 w-px shrink-0 self-center bg-[color-mix(in_srgb,var(--app-border)_64%,transparent)] sm:block"
                    aria-hidden="true"
                  />
                  <div className="app-toolbar-section-title hidden truncate sm:block">
                    {copy.shell.toolbarTitle}
                  </div>
                </div>
              </div>

              <div
                ref={statusRailRef}
                className="hidden min-w-0 flex-1 flex-row flex-nowrap items-center justify-end gap-2 overflow-hidden self-center xl:flex"
                aria-label={copy.shell.accountStatus}
              >
                <StatusChip
                  testId="status-pill-valuation"
                  label={copy.shell.navStatus}
                  value={valuationStatus.value}
                  meta={valuationTimestamp ?? undefined}
                  tone={valuationStatus.tone}
                  indicator={valuationStatus.indicator}
                  hoverHint={copy.shell.viewValuationDetails}
                  affordance="details"
                  expanded={openStatusPanel === 'valuation'}
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
                  affordance="details"
                  refreshLabel={`${copy.market.refreshQuotes}: ${copy.shell.marketStatus}`}
                  refreshing={refreshQuotes.isPending}
                  onRefresh={() =>
                    void refreshQuotes.mutateAsync({
                      force: true,
                    })
                  }
                  expanded={openStatusPanel === 'market'}
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

              <div className="ml-auto flex min-w-0 shrink-0 flex-row items-center justify-end gap-3 self-center whitespace-nowrap sm:gap-4">
                <button
                  type="button"
                  className="app-button-secondary inline-flex h-8 w-8 items-center justify-center rounded-2xl p-0 text-sm sm:w-auto sm:px-3 lg:hidden"
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
                    className="h-4 w-4 sm:hidden"
                    data-testid="mobile-navigation-icon"
                  >
                    <path d="M4 7h16" />
                    <path d="M4 12h16" />
                    <path d="M4 17h16" />
                  </svg>
                  <span className="hidden sm:inline">
                    {copy.shell.navigation}
                  </span>
                </button>

                <div className="flex min-w-0 flex-row items-center gap-2 sm:gap-3">
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

          <div className="app-shell-content min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-auto [contain:layout_paint]">
            <div className="mx-auto min-w-0 w-full max-w-[1880px] px-4 pt-24 pb-12 sm:px-5 lg:px-6 xl:px-7 2xl:px-8">
              {children}
            </div>
          </div>
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
        className={`inline-flex h-9 w-auto items-center gap-2 whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)] px-3.5 text-[12px] font-semibold tracking-[0.06em] text-[var(--app-muted)] backdrop-blur-md transition-[background-color,border-color,color,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:border-[color-mix(in_srgb,var(--app-border)_56%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_26%,transparent)] hover:text-[var(--app-text)] active:translate-y-0 active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-accent-secondary)] ${
          open
            ? 'border-[color-mix(in_srgb,var(--app-border)_56%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_26%,transparent)] text-[var(--app-text)]'
            : ''
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
          className="absolute right-0 top-[calc(100%+6px)] z-[60] min-w-full min-w-max rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-panel)_92%,transparent)] p-1.5 shadow-[0_20px_60px_color-mix(in_srgb,var(--app-mantle)_34%,transparent)] backdrop-blur-lg"
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
                className={`flex w-full min-w-max items-center justify-between gap-3 rounded-xl bg-transparent px-3 py-2 text-left text-xs font-medium text-[var(--app-muted)] transition-[background-color,color,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:bg-[var(--app-accent-ghost)] hover:text-[var(--app-text)] active:scale-[0.98] ${
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
      className="inline-flex h-9 flex-row items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)] p-1 backdrop-blur-md"
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
            className={`inline-flex items-center justify-center rounded-full px-1.5 py-1.5 text-[var(--app-muted)] transition-[background-color,color,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:text-[var(--app-text)] active:translate-y-0 active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-accent-secondary)] sm:px-2.5 [&>svg]:h-4 [&>svg]:w-4 ${
              active
                ? 'bg-[color-mix(in_srgb,var(--app-accent)_18%,transparent)] text-[var(--app-accent)] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_8%,transparent)]'
                : ''
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
  affordance,
  meta,
  popup,
  onRefresh,
  refreshLabel,
  refreshing = false,
  celebrate = false,
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
  affordance: ToolbarStatusAffordance;
  meta?: string;
  popup?: ReactNode;
  onRefresh?: () => void;
  refreshLabel?: string;
  refreshing?: boolean;
  celebrate?: boolean;
  expanded?: boolean;
  testId?: string;
}) {
  return (
    <div className="group relative inline-flex h-9 w-[15rem] shrink-0">
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
        className={`inline-flex h-full w-full items-center overflow-hidden whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] text-[12px] text-[var(--app-soft)] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] backdrop-blur-md transition-[background-color,transform,color,border-color,box-shadow] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:cursor-pointer hover:border-[color-mix(in_srgb,var(--app-border)_56%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_24%,transparent)] hover:text-[var(--app-text)] hover:shadow-[0_12px_32px_color-mix(in_srgb,var(--app-mantle)_20%,transparent),inset_0_1px_0_color-mix(in_srgb,var(--app-text)_6%,transparent)] active:translate-y-0 active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-accent-secondary)] ${
          expanded
            ? 'border-[color-mix(in_srgb,var(--app-border)_56%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_26%,transparent)] text-[var(--app-text)] shadow-[0_12px_32px_color-mix(in_srgb,var(--app-mantle)_22%,transparent)]'
            : ''
        }`}
      >
        <span className="font-mono inline-flex h-full w-14 shrink-0 items-center justify-center bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] px-2 text-[12px] uppercase tracking-[0.1em] text-[var(--app-subtext-0)] transition-colors duration-300 group-hover:bg-transparent">
          {label}
        </span>
        <span
          className="h-5 w-px shrink-0 bg-[color-mix(in_srgb,var(--app-border)_18%,transparent)]"
          aria-hidden="true"
        />
        <span className="font-mono inline-flex h-full min-w-0 flex-1 items-center gap-2 bg-[color-mix(in_srgb,var(--app-surface-0)_50%,transparent)] px-3 py-1.5 pr-8 tabular-nums transition-colors duration-200 group-hover:bg-transparent">
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
                  className={`absolute inset-[1px] rounded-full transition-opacity duration-200 ${
                    affordance === 'resync' || onRefresh
                      ? 'group-hover:opacity-0 group-focus-within:opacity-0'
                      : ''
                  } ${celebrate ? 'animate-[bounce_320ms_ease-out_1]' : ''}`}
                  style={{ backgroundColor: STATUS_COLORS[tone] }}
                  aria-hidden="true"
                  data-testid={testId ? `${testId}-indicator` : undefined}
                />
                {affordance === 'resync' ? (
                  <RotateCwIcon
                    className="absolute h-3.5 w-3.5 text-[var(--app-accent)] opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                    color="currentColor"
                    aria-hidden="true"
                  />
                ) : null}
              </>
            )}
          </span>
          <span className="min-w-[4.25rem] max-w-[7.5rem] truncate text-[12px] font-semibold text-[var(--app-text)]">
            {value}
          </span>
          {meta ? (
            <span className="shrink-0 text-[12px] font-semibold text-[var(--app-muted)]">
              {meta}
            </span>
          ) : null}
          {affordance === 'details' ? (
            <ChevronDownIcon
              className="absolute right-3 h-3.5 w-3.5 shrink-0 text-[var(--app-subtext-0)] opacity-40 transition-[opacity,color] duration-200 group-hover:text-[var(--app-accent)] group-hover:opacity-100"
              aria-hidden="true"
            />
          ) : null}
        </span>
      </button>
      {onRefresh ? (
        <button
          type="button"
          aria-label={refreshLabel ?? hoverHint ?? title ?? label}
          className="absolute left-[4.75rem] top-1/2 z-10 inline-flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-transparent text-[var(--app-accent)] opacity-0 transition-[opacity,transform,background-color] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:scale-105 hover:bg-[color-mix(in_srgb,var(--app-accent)_12%,transparent)] hover:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-accent-secondary)] group-focus-within:opacity-100 group-hover:opacity-100"
          disabled={refreshing}
          aria-busy={refreshing}
          onClick={(event) => {
            event.stopPropagation();
            onRefresh();
          }}
        >
          <RotateCwIcon
            className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`}
            color="currentColor"
            aria-hidden="true"
          />
        </button>
      ) : null}
      {hoverHint && !expanded ? (
        <div className="pointer-events-none absolute left-1/2 top-[calc(100%+8px)] z-[75] -translate-x-1/2 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] px-2.5 py-1.5 text-xs text-[var(--app-text)] opacity-0 shadow-[0_12px_30px_color-mix(in_srgb,var(--app-mantle)_18%,transparent)] backdrop-blur-md transition-opacity duration-75 group-hover:opacity-100 group-focus-visible:opacity-100">
          {hoverHint}
        </div>
      ) : null}
      {popup ? (
        <div className="absolute right-0 top-[calc(100%+8px)] z-[70]">
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
      className="min-w-[180px] rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_50%,transparent)] p-3 shadow-[0_16px_44px_rgba(17,17,27,0.24)] backdrop-blur-md"
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
            <span className="font-mono uppercase tracking-[0.18em] text-[var(--app-muted)]">
              {row.label}
            </span>
            <span className="font-mono tabular-nums font-medium text-[var(--app-text)]">
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
