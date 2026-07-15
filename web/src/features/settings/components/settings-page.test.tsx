import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { MarketDataHealthResponse } from '../../market/api';
import type {
  AssetMetadataStatusResponse,
  DataSourceStatusResponse,
} from '../api';
import { SettingsPage } from './settings-page';

const defaultSettings = {
  host: '0.0.0.0',
  port: 8000,
  live_auto_start: true,
  initial_cash: 100000,
  start_date: '2025-01-02',
  end_date: '2026-05-16',
  assets: [
    { symbol: '600519', asset_class: 'stock' },
    { symbol: '019999', asset_class: 'fund' },
  ],
  strategy: 'dual_ma',
  short_period: 5,
  long_period: 20,
  data_source: 'akshare',
  tushare_token_configured: true,
  notification: { type: 'console', configured: true },
  live_poll_interval: 60,
  account_commission_rate: 0.0001,
  account_min_commission: 5,
};

const defaultLiveStatus = {
  running: true,
  market_open: true,
};

const defaultMarketHealth: MarketDataHealthResponse = {
  quotes: [],
  market_open: true,
  refresh_policy: 'live',
  provider_status: 'healthy',
  provider_name: 'akshare',
  provider_configured: true,
  provider_requires_token: false,
  provider_supports_funds: true,
  provider_last_error: null,
  provider_timeout_seconds: 8,
  next_action: null,
  metadata_configured_count: 2,
  source_health: 'live',
  cache_age_seconds: null,
  latest_quote_timestamp: '2026-05-16T22:40:00+08:00',
  last_refresh_attempt: null,
  last_refresh_error: null,
  stale_symbols_count: 0,
  stale_symbols_sample: [],
  real_data_available: true,
  has_persistent_cache: true,
  latest_persistent_quote_timestamp: '2026-05-16T22:40:00+08:00',
  persistent_cache_status: 'available',
};

const defaultDataSourceStatus: DataSourceStatusResponse = {
  data_source: 'akshare',
  provider_name: 'akshare',
  provider_configured: true,
  provider_supports_funds: true,
  provider_requires_token: false,
  requires_restart: false,
  next_action: null,
  metadata_configured_count: 2,
  has_persistent_cache: true,
  latest_persistent_quote_timestamp: '2026-05-16T22:40:00+08:00',
  persistent_cache_status: 'available',
  available_providers: ['akshare', 'tushare'],
};

const defaultAssetMetadataStatus: AssetMetadataStatusResponse = {
  configured_count: 2,
  missing_symbols: [],
  configured_assets: [
    {
      symbol: '600519',
      display_name: '贵州茅台',
      asset_class: 'stock',
      provider_symbol: '600519',
      aliases: [],
      source: 'assets',
    },
    {
      symbol: '019999',
      display_name: '示例基金',
      asset_class: 'fund',
      provider_symbol: '019999',
      aliases: [],
      source: 'assets',
    },
  ],
  suggested_config: { assets: [] },
  metadata_source: 'config',
  has_missing_metadata: false,
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

type MockSettings = Omit<typeof defaultSettings, 'notification'> & {
  notification?: Record<string, unknown>;
};

type MockOverview = Omit<
  typeof defaultOverview,
  'quote_status' | 'valuation_timestamp'
> & {
  quote_status?: string;
  valuation_timestamp?: string | null;
};

type MockOptions = {
  settings?: Partial<MockSettings> & Record<string, unknown>;
  liveStatus?: typeof defaultLiveStatus;
  marketHealth?: MarketDataHealthResponse;
  dataSourceStatus?: DataSourceStatusResponse;
  assetMetadataStatus?: AssetMetadataStatusResponse;
  overview?: Partial<MockOverview> & Record<string, unknown>;
  failLiveStatus?: boolean;
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installFetchMock({
  settings = defaultSettings,
  liveStatus = defaultLiveStatus,
  marketHealth = defaultMarketHealth,
  dataSourceStatus = defaultDataSourceStatus,
  assetMetadataStatus = defaultAssetMetadataStatus,
  overview = defaultOverview,
  failLiveStatus = false,
}: MockOptions = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/settings/data-source')) {
      if (init?.method === 'PUT') {
        return jsonResponse({
          ...settings,
          ...(JSON.parse(String(init?.body ?? '{}')) as object),
        });
      }
      return jsonResponse(dataSourceStatus);
    }
    if (url.includes('/api/settings/asset-metadata')) {
      return jsonResponse(assetMetadataStatus);
    }
    if (url.includes('/api/settings/live/start')) {
      return jsonResponse({ running: true, market_open: true });
    }
    if (url.includes('/api/settings/live/stop')) {
      return jsonResponse({ running: false, market_open: false });
    }
    if (url.includes('/api/settings/notification/test')) {
      return jsonResponse({ status: 'ok', message: 'sent' });
    }
    if (url.endsWith('/api/settings')) {
      if (init?.method === 'PUT') {
        return jsonResponse({
          ...settings,
          ...(JSON.parse(String(init?.body ?? '{}')) as object),
        });
      }
      return jsonResponse(settings);
    }
    if (url.includes('/api/settings/live/status')) {
      return failLiveStatus
        ? jsonResponse({ detail: 'live unavailable' }, { status: 503 })
        : jsonResponse(liveStatus);
    }
    if (url.includes('/api/market/data-health')) {
      return jsonResponse(marketHealth);
    }
    if (url.includes('/api/portfolio/overview')) {
      return jsonResponse(overview);
    }
    return new Response('Not found', { status: 404 });
  });
}

function renderSettingsPage(options: MockOptions = {}) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installFetchMock(options);
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <SettingsPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders backend data status and service state', async () => {
  renderSettingsPage();

  expect(await screen.findByText('Control center')).toBeTruthy();
  expect(await screen.findByText('Data status')).toBeTruthy();
  expect(
    await screen.findByLabelText('Market state: Market open'),
  ).toBeTruthy();
  expect(await screen.findByLabelText('Refresh policy: Live')).toBeTruthy();
  expect(await screen.findByText('Scheduler running')).toBeTruthy();
  expect(await screen.findByText('Runtime boundary')).toBeTruthy();
  expect(
    await screen.findByLabelText('Boundary item: Scheduler Scheduler running'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Boundary item: Execution default Manual confirmation',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('Safety register')).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Safety item: Execution default Manual confirmation required',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByRole('button', { name: 'Data source: AKShare' }),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Current provider: akshare'),
  ).toBeTruthy();
  expect(await screen.findByText('2 tracked assets')).toBeTruthy();
  expect(await screen.findByText('Operations register')).toBeTruthy();
  expect(
    await screen.findByLabelText('Register item: Provider akshare'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Register item: Poll interval 60s'),
  ).toBeTruthy();
  expect(await screen.findByText('Provider configuration')).toBeTruthy();
  expect(await screen.findByText('Metadata readiness')).toBeTruthy();
});

test('shows cached quote guidance for cache-only and stale valuation states', async () => {
  renderSettingsPage({
    marketHealth: {
      ...defaultMarketHealth,
      market_open: false,
      refresh_policy: 'cache_only',
    },
    overview: {
      ...defaultOverview,
      quote_status: 'stale',
    },
  });

  expect(
    await screen.findByLabelText('Quote state: Cached quotes'),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Current valuation is based on cached market data. Next action: Refresh quotes or check the data source',
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/real-time/i)).toBeNull();
});

test('surfaces non-cache unconfirmed valuation states as needing review', async () => {
  renderSettingsPage({
    overview: {
      ...defaultOverview,
      quote_status: 'confirmed_nav_missing',
    },
  });

  expect(
    await screen.findByLabelText('Quote state: Confirmed NAV missing'),
  ).toBeTruthy();
  expect(await screen.findByText('Valuation requires review')).toBeTruthy();
  expect(
    await screen.findByText(
      'Quote state is Confirmed NAV missing. Treat valuation and returns as unconfirmed until data is refreshed or reconciled. Next action: Wait for confirmed fund NAV or sync NAV data',
    ),
  ).toBeTruthy();
});

test('does not claim live interface availability when live status fails', async () => {
  renderSettingsPage({ failLiveStatus: true });

  expect(
    await screen.findByText('Failed to load settings state.'),
  ).toBeTruthy();
  expect(await screen.findByText('Interface not running')).toBeTruthy();
  expect(screen.queryByText('Interface status available')).toBeNull();
});

test('updates local theme and language preferences', async () => {
  const user = userEvent.setup();
  renderSettingsPage();

  await screen.findByText('Control center');
  await user.click(screen.getByRole('button', { name: 'Latte' }));
  expect(window.localStorage.getItem('karkinos.theme')).toBe('light');

  await user.click(screen.getByRole('button', { name: '中文' }));
  expect(window.localStorage.getItem('karkinos.locale')).toBe('zh');
  expect(await screen.findByText('控制中心')).toBeTruthy();
});

test('saves data source settings through the settings endpoint', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderSettingsPage();

  const intervalInput = (await screen.findByRole('spinbutton', {
    name: 'Poll interval',
  })) as HTMLInputElement;
  await waitFor(() => expect(intervalInput.disabled).toBe(false));
  await user.clear(intervalInput);
  await user.type(intervalInput, '90');
  await user.click(screen.getByRole('button', { name: 'Save data settings' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/settings/data-source',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          data_source: 'akshare',
          live_poll_interval: 90,
        }),
      }),
    );
  });
  expect(
    screen.queryByRole('textbox', { name: 'TuShare credential' }),
  ).toBeNull();
  expect(
    await screen.findByText('Not required by the selected provider'),
  ).toBeTruthy();
  expect(await screen.findByText('Data settings saved')).toBeTruthy();
});

test('blocks TuShare selection until the environment credential is configured', async () => {
  const user = userEvent.setup();
  renderSettingsPage({
    settings: { ...defaultSettings, tushare_token_configured: false },
  });

  await user.click(
    await screen.findByRole('button', { name: 'Data source: Tushare' }),
  );

  expect(
    await screen.findByText(
      'Missing; configure TUSHARE_TOKEN before switching',
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole('button', {
        name: 'Save data settings',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.queryByRole('textbox', { name: 'TuShare credential' }),
  ).toBeNull();
});

test('saves account commission settings through the settings endpoint', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderSettingsPage();

  const rateInput = (await screen.findByRole('spinbutton', {
    name: 'Stock commission rate',
  })) as HTMLInputElement;
  const minInput = screen.getByRole('spinbutton', {
    name: 'Minimum commission',
  }) as HTMLInputElement;

  await waitFor(() => expect(rateInput.disabled).toBe(false));
  await user.clear(rateInput);
  await user.type(rateInput, '0.00025');
  await user.clear(minInput);
  await user.type(minInput, '3');
  await user.click(screen.getByRole('button', { name: 'Save account costs' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/settings',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          ...defaultSettings,
          account_commission_rate: 0.00025,
          account_min_commission: 3,
        }),
      }),
    );
  });
  expect(await screen.findByText('Account costs saved')).toBeTruthy();
});

test('shows provider timeout guidance without alternate local provider action', async () => {
  renderSettingsPage({
    marketHealth: {
      ...defaultMarketHealth,
      provider_last_error: 'provider_timeout',
      last_refresh_error: 'provider_timeout',
      source_health: 'degraded',
      next_action: 'check_provider_network_or_use_cache',
    },
    dataSourceStatus: {
      ...defaultDataSourceStatus,
      provider_supports_funds: false,
      next_action: 'switch_to_fund_supported_provider',
    },
  });

  expect(
    await screen.findByText('The configured quote source is timing out.'),
  ).toBeTruthy();
});

test('shows tushare capability matrix and manual daily tasks', async () => {
  renderSettingsPage({
    settings: {
      ...defaultSettings,
      data_source: 'tushare',
    },
    marketHealth: {
      ...defaultMarketHealth,
      provider_name: 'tushare',
      provider_status: 'partial',
      provider_supports_funds: true,
      provider_last_error: 'tushare_fund_nav_permission_denied',
      last_refresh_error: 'tushare_fund_nav_permission_denied',
      next_action: 'refresh_quotes_or_check_source',
      quotes: [
        {
          symbol: '600519',
          asset_class: 'stock',
          timestamp: '2026-06-15T11:20:35+08:00',
          price: 28.72,
          quote_status: 'live',
          quote_source: 'tushare_realtime_quote',
          quote_age_seconds: 120,
          stale_reason: null,
          last_refresh_attempt: null,
          last_refresh_error: null,
          using_persistent_cache: false,
          nav_date: null,
        },
        {
          symbol: '019999',
          asset_class: 'fund',
          timestamp: '2026-06-15 11:20',
          price: 2.3077,
          quote_status: 'live',
          quote_source: 'eastmoney_fund_estimate',
          quote_age_seconds: 180,
          stale_reason: 'tushare_fund_nav_permission_denied',
          last_refresh_attempt: null,
          last_refresh_error: null,
          using_persistent_cache: false,
          nav_date: null,
        },
      ],
    },
    dataSourceStatus: {
      ...defaultDataSourceStatus,
      data_source: 'tushare',
      provider_name: 'tushare',
      provider_requires_token: true,
      provider_supports_funds: false,
      next_action: 'switch_to_fund_supported_provider',
    },
  });

  expect(await screen.findByText('Provider capability matrix')).toBeTruthy();
  expect(await screen.findByText('TuShare permissions')).toBeTruthy();
  expect((await screen.findAllByText('fund_nav')).length).toBeGreaterThan(0);
  expect(
    (await screen.findAllByText('Permission blocked')).length,
  ).toBeGreaterThan(0);
  expect(
    (await screen.findAllByText('Eastmoney fund estimate')).length,
  ).toBeGreaterThan(0);
  expect(await screen.findByText('Manual daily task checklist')).toBeTruthy();
  expect(
    await screen.findByLabelText('Manual task: TuShare sign-in'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Manual task: Guess market direction'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Manual task: Check points and permissions'),
  ).toBeTruthy();
  expect(screen.queryByText('Submit bugs or data requests')).toBeNull();
});

test('guides users to configure asset metadata when none is available', async () => {
  renderSettingsPage({
    marketHealth: {
      ...defaultMarketHealth,
      metadata_configured_count: 0,
    },
    dataSourceStatus: {
      ...defaultDataSourceStatus,
      metadata_configured_count: 0,
      next_action: 'configure_asset_metadata',
    },
    assetMetadataStatus: {
      ...defaultAssetMetadataStatus,
      configured_count: 0,
      missing_symbols: ['029999', '012999'],
      configured_assets: [],
      suggested_config: {
        assets: [
          {
            symbol: '029999',
            asset_class: 'fund',
            display_name: '<填入资产名称>',
            provider_symbol: '029999',
            aliases: ['029999'],
          },
        ],
      },
      has_missing_metadata: true,
    },
  });

  expect(
    await screen.findByText('Asset metadata is not configured'),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Backfill asset names and provider symbols into the local instrument metadata table. Keep config.json for runtime settings and watchlist symbols only.',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('Assets missing metadata')).toBeTruthy();
  expect(await screen.findByText('029999, 012999')).toBeTruthy();
  const snippet = (await screen.findByLabelText(
    'Suggested config snippet',
  )) as HTMLTextAreaElement;
  expect(snippet.value).toContain('"symbol": "029999"');
});

test('shows configured asset metadata state when no symbols are missing', async () => {
  renderSettingsPage();

  expect(await screen.findByText('Asset metadata configured')).toBeTruthy();
  expect(
    await screen.findByText(
      'Current holdings have configured asset identities or safe fallbacks.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('undefined')).toBeNull();
});

test('handles missing backend status without crashing', async () => {
  renderSettingsPage({
    settings: {
      ...defaultSettings,
      assets: [],
      notification: {},
    },
    overview: {
      ...defaultOverview,
      valuation_timestamp: null,
      quote_status: undefined,
    },
  });

  expect(await screen.findByText('No valuation timestamp')).toBeTruthy();
  expect(await screen.findByText('0 tracked assets')).toBeTruthy();
  expect(
    await screen.findByText('No notification channel configured'),
  ).toBeTruthy();
});

test('disables notification tests when environment credentials are missing', async () => {
  renderSettingsPage({
    settings: {
      ...defaultSettings,
      notification: { type: 'telegram', configured: false },
    },
  });

  expect(
    await screen.findByText('Required environment values are missing'),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole('button', {
        name: 'Send test notification',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
