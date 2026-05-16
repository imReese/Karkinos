import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { AppShell } from './app-shell';
import { PreferencesProvider } from '../preferences';

type MatchMediaMock = {
  setDarkMode: (matches: boolean) => void;
};

const defaultOverview = {
  total_equity: 4101.16,
  available_cash: 2301.2,
  total_deposits: 4000,
  positions_count: 3,
  unrealized_pnl: 101.16,
  realized_pnl: 0,
  cash_ratio: 0.561,
  valuation_timestamp: '2026-05-16T22:40:00+08:00',
  quote_status: 'live',
};

const defaultLiveStatus = {
  running: true,
  market_open: true,
};

const defaultMarketHealth = {
  quotes: [],
  market_open: true,
  refresh_policy: 'live',
};

type ShellStatusMockOptions = {
  overview?: typeof defaultOverview;
  liveStatus?: typeof defaultLiveStatus;
  marketHealth?: typeof defaultMarketHealth;
  fetchImpl?: typeof fetch;
  locale?: 'en' | 'zh';
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installShellStatusFetchMock({
  overview = defaultOverview,
  liveStatus = defaultLiveStatus,
  marketHealth = defaultMarketHealth,
  fetchImpl,
}: ShellStatusMockOptions = {}) {
  const statusFetch =
    fetchImpl ??
    vi.fn(async (input: RequestInfo | URL) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();
      if (url.includes('/api/portfolio/overview')) {
        return jsonResponse(overview);
      }
      if (url.includes('/api/settings/live/status')) {
        return jsonResponse(liveStatus);
      }
      if (url.includes('/api/market/data-health')) {
        return jsonResponse(marketHealth);
      }
      return new Response('Not found', { status: 404 });
    });

  vi.stubGlobal('fetch', statusFetch);
  return statusFetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function installMatchMediaMock(initialDark = false): MatchMediaMock {
  let darkMode = initialDark;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-color-scheme: dark')
        ? darkMode
        : !darkMode,
      media: query,
      onchange: null,
      addEventListener: vi.fn(
        (event: string, listener: (event: MediaQueryListEvent) => void) => {
          if (event === 'change') {
            listeners.add(listener);
          }
        },
      ),
      removeEventListener: vi.fn(
        (event: string, listener: (event: MediaQueryListEvent) => void) => {
          if (event === 'change') {
            listeners.delete(listener);
          }
        },
      ),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  return {
    setDarkMode(matches: boolean) {
      darkMode = matches;
      const event = {
        matches,
        media: '(prefers-color-scheme: dark)',
      } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

function renderShell(options: ShellStatusMockOptions = {}) {
  window.scrollTo = () => {};
  window.localStorage.clear();
  if (options.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  installShellStatusFetchMock(options);
  const matchMedia = installMatchMediaMock();

  const rootRoute = createRootRoute({
    component: () => (
      <AppShell>
        <Outlet />
      </AppShell>
    ),
  });

  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: () => <div>Overview page</div>,
  });

  const routeTree = rootRoute.addChildren([indexRoute]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  });
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { matchMedia };
}

test('renders portfolio workspace navigation', async () => {
  renderShell();

  expect(await screen.findByText('Overview')).toBeTruthy();
  expect(await screen.findByText('Portfolio')).toBeTruthy();
  expect(await screen.findByText('Activity')).toBeTruthy();
  expect(await screen.findByText('Risk')).toBeTruthy();
  expect(await screen.findByText('Overview page')).toBeTruthy();
  expect(await screen.findByText('Workspace toolbar')).toBeTruthy();
  expect(await screen.findByLabelText('Account Status')).toBeTruthy();
});

test('uses minimalist sidebar active styling and subtext icons', async () => {
  renderShell();

  const activeItem = await screen.findByTestId('sidebar-nav-overview');
  const activeIcon = await screen.findByTestId('sidebar-nav-overview-icon');
  const inactiveIcon = await screen.findByTestId('sidebar-nav-portfolio-icon');

  expect(activeItem.className).toContain('app-nav-item-active');
  expect(activeItem.className).not.toContain('app-button-primary');
  expect(activeIcon.getAttribute('class')).toContain('app-nav-icon');
  expect(inactiveIcon.getAttribute('class')).toContain('app-nav-icon');
});

test('keeps the KARKINOS brand mark unwrapped in the sidebar header', async () => {
  renderShell();

  const brandMarks = await screen.findAllByText('Karkinos');
  const sidebarBrand = brandMarks[0] as HTMLElement;

  expect(sidebarBrand.className).toContain('whitespace-nowrap');
  expect(sidebarBrand.className).toContain('shrink-0');
  expect(sidebarBrand.className).toContain('font-semibold');
});

test('switches interface language from english to chinese', async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole('button', { name: 'Language' }));
  await user.click(await screen.findByRole('menuitemradio', { name: '中文' }));

  expect(await screen.findByText('总览')).toBeTruthy();
  expect(await screen.findByText('组合')).toBeTruthy();
  expect(await screen.findByText('流水')).toBeTruthy();
  expect(await screen.findByText('风险')).toBeTruthy();
  expect(await screen.findByText('全局工具栏')).toBeTruthy();
  expect(window.localStorage.getItem('karkinos.locale')).toBe('zh');
});

test('uses stronger chinese typography in the sidebar', async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole('button', { name: 'Language' }));
  await user.click(await screen.findByRole('menuitemradio', { name: '中文' }));

  const workspaceTitle = await screen.findByText('组合工作台');
  const overviewNav = await screen.findByTestId('sidebar-nav-overview');

  expect(workspaceTitle.className).not.toContain('tracking-[-0.02em]');
  expect(overviewNav.className).toContain('font-semibold');
});

test('switches theme preference and persists it', async () => {
  const { matchMedia } = renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByRole('button', { name: 'Dark theme' }));
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(window.localStorage.getItem('karkinos.theme')).toBe('dark');

  await user.click(await screen.findByRole('button', { name: 'Light theme' }));
  expect(document.documentElement.dataset.theme).toBe('light');
  expect(window.localStorage.getItem('karkinos.theme')).toBe('light');

  act(() => {
    matchMedia.setDarkMode(true);
  });
  expect(document.documentElement.dataset.theme).toBe('light');

  await user.click(await screen.findByRole('button', { name: 'System theme' }));
  expect(window.localStorage.getItem('karkinos.theme')).toBeNull();
  expect(document.documentElement.dataset.theme).toBe('dark');

  act(() => {
    matchMedia.setDarkMode(false);
  });
  expect(document.documentElement.dataset.theme).toBe('light');
});

test('keeps the desktop toolbar controls in a single centered row', async () => {
  renderShell();

  const toolbarTitle = await screen.findByText('Workspace toolbar');
  const toolbarRow = toolbarTitle.closest('header')
    ?.firstElementChild as HTMLElement | null;
  expect(toolbarRow).toBeTruthy();
  expect(toolbarRow?.className).toContain('h-14');
  expect(toolbarRow?.className).toContain('items-center');
  expect(toolbarRow?.className).toContain('px-4');

  const accountStatus = await screen.findByLabelText('Account Status');
  expect(accountStatus.className).toContain('flex-nowrap');
  expect(accountStatus.className).not.toContain('flex-wrap');

  const themeSwitcher = await screen.findByRole('group', { name: 'Theme' });
  expect(themeSwitcher.className).toContain('flex-row');
  expect(themeSwitcher.className).toContain('items-center');
  expect(themeSwitcher.className).toContain('rounded-full');

  const languageButton = await screen.findByRole('button', {
    name: 'Language',
  });
  expect(languageButton.className).toContain('w-auto');
  expect(languageButton.className).toContain('whitespace-nowrap');
  expect(languageButton.textContent).toBe('English');
});

test('uses full language names and fluid menu width', async () => {
  renderShell();
  const user = userEvent.setup();

  const languageButton = await screen.findByRole('button', {
    name: 'Language',
  });
  expect(languageButton.className).toContain('w-auto');
  expect(languageButton.className).toContain('px-3');
  expect(languageButton.textContent).toBe('English');

  await user.click(languageButton);

  const menu = await screen.findByRole('menu', { name: 'Language' });
  expect(menu.className).toContain('min-w-max');
  expect(
    await screen.findByRole('menuitemradio', { name: 'English' }),
  ).toBeTruthy();
  expect(
    await screen.findByRole('menuitemradio', { name: '中文' }),
  ).toBeTruthy();
});

test('shows cached quote status and valuation time from account overview', async () => {
  renderShell({
    locale: 'zh',
    overview: {
      ...defaultOverview,
      quote_status: 'stale',
      valuation_timestamp: '2026-05-16T22:40:00+08:00',
    },
  });

  expect((await screen.findAllByText('缓存行情')).length).toBeGreaterThan(0);
  expect(await screen.findByText('估值 22:40')).toBeTruthy();
});

test('shows cache-only market state from data health', async () => {
  renderShell({
    locale: 'zh',
    marketHealth: {
      quotes: [],
      market_open: false,
      refresh_policy: 'cache_only',
    },
  });

  expect(await screen.findByText('市场休市')).toBeTruthy();
});

test('does not report ready states while status queries are loading', async () => {
  renderShell({
    locale: 'zh',
    fetchImpl: vi.fn(() => new Promise<Response>(() => {})),
  });

  expect((await screen.findAllByText('检查中')).length).toBeGreaterThan(0);
  expect(screen.queryByText('券商接口就绪')).toBeNull();
  expect(screen.queryByText('估值已启用')).toBeNull();
});

test('shows degraded states when status APIs fail', async () => {
  renderShell({
    locale: 'zh',
    fetchImpl: vi.fn(async () => {
      throw new Error('offline');
    }),
  });

  expect(await screen.findByText('账本异常')).toBeTruthy();
  expect(await screen.findByText('接口异常')).toBeTruthy();
  expect(await screen.findByText('估值异常')).toBeTruthy();
  expect(await screen.findByText('行情异常')).toBeTruthy();
  expect(screen.queryByText('券商接口就绪')).toBeNull();
});

test('shows broker status details without simulated latency', async () => {
  renderShell();
  const user = userEvent.setup();

  await user.click(await screen.findByTestId('status-pill-broker'));

  const dialog = await screen.findByRole('dialog', {
    name: 'API',
  });
  expect(dialog).toBeTruthy();
  expect(within(dialog).getByText('Broker API ready')).toBeTruthy();
  expect(screen.queryByText('42ms')).toBeNull();
});

test('toggles mobile navigation from the global toolbar', async () => {
  renderShell();
  const user = userEvent.setup();

  const openButton = await screen.findByRole('button', {
    name: 'Open navigation',
  });
  expect(openButton.getAttribute('aria-expanded')).toBe('false');

  await user.click(openButton);

  expect(
    (await screen.findAllByRole('button', { name: 'Close navigation' })).length,
  ).toBeGreaterThan(0);
  expect(openButton.getAttribute('aria-expanded')).toBe('true');
  expect(await screen.findByLabelText('Navigation')).toBeTruthy();
});
