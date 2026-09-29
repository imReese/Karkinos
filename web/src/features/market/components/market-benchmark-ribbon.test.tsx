import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import { marketCopy } from '../copy';
import { MarketBenchmarkRibbon } from './market-benchmark-ribbon';
import type { MarketPageController } from '../pages/market-page-controller';

function createMockController(
  overrides: Partial<MarketPageController> = {},
): MarketPageController {
  const setSelectedSymbol = vi.fn();
  return {
    copy: {
      ...marketCopy.zh,
      market: marketCopy.zh,
    } as any,
    locale: 'zh',
    toasts: [],
    board: {
      data: { items: [], health: {} as any },
      isLoading: false,
      isError: false,
    } as any,
    addWatchlistItem: {} as any,
    removeWatchlistItem: {} as any,
    createResearchNote: {} as any,
    quoteFetchRuns: {} as any,
    holdingMarketEvidenceReview: {} as any,
    metadataBackfill: {} as any,
    barsBackfill: {} as any,
    selectedSymbol: '600519',
    setSelectedSymbol,
    newSymbol: '',
    setNewSymbol: vi.fn(),
    newAssetClass: 'stock',
    setNewAssetClass: vi.fn(),
    noteFilterType: '',
    setNoteFilterType: vi.fn(),
    noteFilterPriority: '',
    setNoteFilterPriority: vi.fn(),
    noteFilterDateFrom: '',
    setNoteFilterDateFrom: vi.fn(),
    noteFilterDateTo: '',
    setNoteFilterDateTo: vi.fn(),
    noteType: 'note',
    setNoteType: vi.fn(),
    notePriority: 'normal',
    setNotePriority: vi.fn(),
    noteTitle: '',
    setNoteTitle: vi.fn(),
    noteContent: '',
    setNoteContent: vi.fn(),
    noteDate: '',
    setNoteDate: vi.fn(),
    editingNoteId: null,
    setEditingNoteId: vi.fn(),
    items: [],
    health: {
      quotes: [],
      market_open: true,
      refresh_policy: 'live',
      provider_status: 'available',
      provider_name: 'fixture',
      provider_configured: true,
      provider_requires_token: false,
      provider_supports_funds: true,
      provider_last_error: null,
      provider_timeout_seconds: 8,
      next_action: null,
      metadata_configured_count: 1,
      source_health: 'healthy',
      cache_age_seconds: 60,
      latest_quote_timestamp: '2026-06-17T14:10:00+08:00',
      last_refresh_attempt: '2026-06-17T14:10:00+08:00',
      last_refresh_error: null,
      stale_symbols_count: 0,
      stale_symbols_sample: [],
    },
    healthBySymbol: new Map(),
    activeSymbol: '600519',
    updateResearchNote: {} as any,
    selectedItem: null,
    selectedHealthQuote: null,
    providerAction: null,
    providerActionIsFundCoverage: false,
    selectedQuoteNextAction: null,
    sourceHealthLabel: 'Healthy',
    refreshPolicyLabel: 'Live',
    cacheBound: false,
    evidenceModeLabel: 'Healthy',
    providerStatusLabel: 'Available',
    providerConfiguredLabel: 'Configured',
    providerFundsLabel: 'Supported',
    holdingItemsCount: 0,
    staleCount: 0,
    latestQuoteLabel: '2026-06-17',
    marketStateLabel: 'Open',
    holdingReviewNeedsAttention: false,
    kline: {} as any,
    notes: {} as any,
    deleteResearchNote: {} as any,
    assetClassOptions: [] as any,
    pushToast: vi.fn(),
    ...overrides,
  };
}

describe('MarketBenchmarkRibbon', () => {
  test('renders benchmark indices and market breadth fallback when quotes are empty', () => {
    const controller = createMockController({
      items: [
        {
          symbol: '600519',
          name: '贵州茅台',
          is_holding: true,
          asset_class: 'stock',
          quantity: 100,
          avg_cost: 1600,
          market_value: 170000,
          unrealized_pnl: 10000,
          realized_pnl: 0,
          last_snapshot_at: null,
          price: 1700,
          volume: 1000,
          research_count: 0,
          last_research_at: null,
        },
      ],
    });

    render(<MarketBenchmarkRibbon controller={controller} />);

    expect(screen.getByTestId('market-benchmark-ribbon')).toBeTruthy();
    expect(screen.getByTestId('benchmark-card-sse')).toBeTruthy();
    expect(screen.getByTestId('benchmark-card-csi300')).toBeTruthy();
    expect(screen.getByTestId('benchmark-card-chinext')).toBeTruthy();
    expect(screen.getByText('上证指数')).toBeTruthy();
    expect(screen.getByText('沪深300')).toBeTruthy();
    expect(screen.getByText('创业板指')).toBeTruthy();
    expect(screen.getByText('统计 1 只')).toBeTruthy();
  });

  test('extracts live quote changes and computes breadth ratio correctly', () => {
    const controller = createMockController({
      health: {
        quotes: [
          {
            symbol: '000001',
            asset_class: 'index',
            name: '上证指数',
            timestamp: '2026-06-17T14:10:00+08:00',
            price: 3150.88,
            daily_change_pct: 1.25,
            daily_change: 38.9,
            quote_status: 'live',
            quote_source: 'fixture',
            quote_age_seconds: 30,
            stale_reason: null,
            last_refresh_attempt: null,
            last_refresh_error: null,
          },
          {
            symbol: '000300',
            asset_class: 'index',
            name: '沪深300',
            timestamp: '2026-06-17T14:10:00+08:00',
            price: 3820.12,
            daily_change_pct: -0.65,
            daily_change: -25.0,
            quote_status: 'live',
            quote_source: 'fixture',
            quote_age_seconds: 30,
            stale_reason: null,
            last_refresh_attempt: null,
            last_refresh_error: null,
          },
          {
            symbol: '600519',
            asset_class: 'stock',
            name: '贵州茅台',
            timestamp: '2026-06-17T14:10:00+08:00',
            price: 1750,
            daily_change_pct: 2.1,
            daily_change: 36,
            quote_status: 'live',
            quote_source: 'fixture',
            quote_age_seconds: 30,
            stale_reason: null,
            last_refresh_attempt: null,
            last_refresh_error: null,
          },
          {
            symbol: '000002',
            asset_class: 'stock',
            name: '万科A',
            timestamp: '2026-06-17T14:10:00+08:00',
            price: 8.5,
            daily_change_pct: 0,
            daily_change: 0,
            quote_status: 'live',
            quote_source: 'fixture',
            quote_age_seconds: 30,
            stale_reason: null,
            last_refresh_attempt: null,
            last_refresh_error: null,
          },
        ],
      } as any,
    });

    render(<MarketBenchmarkRibbon controller={controller} />);

    // Check SSE index card price and change
    expect(screen.getByText('3,150.88')).toBeTruthy();
    expect(screen.getByText('+1.25%')).toBeTruthy();

    // Check CSI 300 index card price and change
    expect(screen.getByText('3,820.12')).toBeTruthy();
    expect(screen.getByText('-0.65%')).toBeTruthy();

    // Check breadth counts: 2 advances, 1 flat, 1 decline
    expect(screen.getByTestId('breadth-advances').textContent).toContain('2');
    expect(screen.getByTestId('breadth-flat').textContent).toContain('1');
    expect(screen.getByTestId('breadth-declines').textContent).toContain('1');
  });

  test('allows selecting benchmark when item is in the board', () => {
    const setSelectedSymbol = vi.fn();
    const controller = createMockController({
      setSelectedSymbol,
      items: [
        {
          symbol: '000300',
          name: '沪深300',
          is_holding: false,
          asset_class: 'index',
          quantity: null,
          avg_cost: null,
          market_value: null,
          unrealized_pnl: null,
          realized_pnl: null,
          last_snapshot_at: null,
          price: 3800,
          volume: null,
          research_count: 0,
          last_research_at: null,
        },
      ],
    });

    render(<MarketBenchmarkRibbon controller={controller} />);

    const csi300Card = screen.getByTestId('benchmark-card-csi300');
    fireEvent.click(csi300Card);
    expect(setSelectedSymbol).toHaveBeenCalledWith('000300');
  });
});
