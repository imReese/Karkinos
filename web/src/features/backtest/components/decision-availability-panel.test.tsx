import type { ReactNode } from 'react';
import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type {
  BacktestReport,
  DatasetDecisionAvailability,
  StrategySignalPreviewResponse,
} from '../api';
import { DatasetSnapshotPanel } from './dataset-snapshot-panel';
import { StrategySignalPreviewPanel } from './strategy-signal-preview-panel';

const availability: DatasetDecisionAvailability = {
  schema_version: 'karkinos.dataset_decision_availability.v1',
  decision_time_basis: 'bar_event_time',
  covers: 'bound_bar_and_verification_availability_at_replay_event_time',
  does_not_validate: [
    'execution_timing',
    'historical_universe',
    'corporate_action_returns',
  ],
  status: 'blocked',
  checked_bar_count: 5,
  late_bar_count: 2,
  late_verification_count: 1,
  first_late_bar: {
    instrument_type: 'stock',
    symbol: '600000',
    session_date: '2026-09-07',
    decision_at: '2026-09-07T15:00:00+08:00',
    available_at: '2026-09-07T15:05:00+08:00',
  },
  first_late_verification: {
    instrument_type: 'stock',
    symbol: '600000',
    session_date: '2026-09-08',
    decision_at: '2026-09-08T15:00:00+08:00',
    checked_at: '2026-09-08T16:00:00+08:00',
  },
};

function report(
  evidence: DatasetDecisionAvailability | null | undefined,
): BacktestReport {
  return {
    id: 7,
    created_at: '2026-09-09T09:00:00+08:00',
    config: {
      dataset_id: `sha256:${'a'.repeat(64)}`,
      start_date: '2026-09-07',
      end_date: '2026-09-11',
      initial_cash: 100000,
      strategy: 'dual_ma',
    },
    metrics: {
      initial_cash: 100000,
      final_equity: 100000,
      total_return: 0,
      annual_return: 0,
      sharpe: 0,
      sortino: 0,
      max_drawdown: 0,
      win_rate: 0,
      duration_days: 5,
    },
    metrics_json: {
      dataset_snapshot: {
        immutable_dataset_id: `sha256:${'a'.repeat(64)}`,
        snapshot_id: 'snapshot-7',
        provider: { configured_source: 'baostock' },
        cache: { store_available: false, metadata_available: false },
        date_range: { start: '2026-09-07', end: '2026-09-11' },
        row_count: 5,
        adjustment_mode: 'none',
        data_quality: { status: 'ok', issues: [] },
        symbol_universe: [],
      },
      dataset_binding: { decision_availability: evidence },
    },
    equity_curve: [],
  };
}

function mount(node: ReactNode, locale: 'en' | 'zh') {
  window.localStorage.setItem('karkinos.locale', locale);
  render(<PreferencesProvider>{node}</PreferencesProvider>);
  return within(screen.getByTestId('decision-availability-panel'));
}

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      addEventListener: vi.fn(),
      matches: false,
      media: query,
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

test('saved Dataset report shows bound timing failures separately from data quality and promotion', () => {
  const panel = mount(
    <DatasetSnapshotPanel report={report(availability)} />,
    'en',
  );

  expect(panel.getByText('Late evidence found')).toBeTruthy();
  expect(panel.getByText('Bars checked').nextElementSibling?.textContent).toBe(
    '5',
  );
  expect(
    panel.getByText('Bars available after replay time').nextElementSibling
      ?.textContent,
  ).toBe('2');
  expect(
    panel.getByText('Bars whose verification finished after replay time')
      .nextElementSibling?.textContent,
  ).toBe('1');
  expect(panel.getByText('First late bar: 600000 · 2026-09-07')).toBeTruthy();
  expect(
    panel.getByText('First late verification: 600000 · 2026-09-08'),
  ).toBeTruthy();
  expect(panel.getByText(/fill on that same bar/i)).toBeTruthy();
  expect(
    panel.getByText(/cannot establish executable PIT performance/i),
  ).toBeTruthy();
  expect(panel.getByText(/does not allow strategy promotion/i)).toBeTruthy();
});

test('a locally clear check and an older report never claim historical PIT admission', () => {
  const clear = {
    ...availability,
    status: 'pass' as const,
    late_bar_count: 0,
    late_verification_count: 0,
    first_late_bar: null,
    first_late_verification: null,
  };
  const { rerender } = render(
    <PreferencesProvider>
      <DatasetSnapshotPanel report={report(clear)} />
    </PreferencesProvider>,
  );
  let panel = within(screen.getByTestId('decision-availability-panel'));
  expect(panel.getByText('No late evidence in this check')).toBeTruthy();
  expect(panel.getByText(/not historical PIT admission/i)).toBeTruthy();

  rerender(
    <PreferencesProvider>
      <DatasetSnapshotPanel report={report(undefined)} />
    </PreferencesProvider>,
  );
  panel = within(screen.getByTestId('decision-availability-panel'));
  expect(panel.getByText('Not evaluated')).toBeTruthy();
  expect(
    panel.getByText(/no supported decision-time availability check/i),
  ).toBeTruthy();

  rerender(
    <PreferencesProvider>
      <DatasetSnapshotPanel
        report={report({ ...availability, status: 'pass' })}
      />
    </PreferencesProvider>,
  );
  panel = within(screen.getByTestId('decision-availability-panel'));
  expect(panel.getByText('Not evaluated')).toBeTruthy();
  expect(panel.queryByText('No late evidence in this check')).toBeNull();
});

test('Dataset signal preview shows the same check in Chinese without implying a fill', () => {
  const preview: StrategySignalPreviewResponse = {
    schema_version: 'karkinos.strategy_signal_preview.v1',
    strategy_id: 'dual_ma',
    symbol: '600000',
    params: {},
    run_id: 'preview-7',
    dataset_snapshot_id: 'snapshot-7',
    decision_availability: availability,
    record_count: 1,
    outputs: [
      {
        output_id: 'preview-7:0001:no_action',
        output_type: 'no_action',
        record_kind: 'explanation',
        action: 'no_action',
        reason: 'No action',
        symbol: '600000',
        evidence: { bar_count: 5, data_quality_status: 'ok' },
        requires_risk_gate: false,
        requires_account_truth_gate: false,
        requires_paper_shadow_review: false,
        requires_manual_review: false,
        does_not_enable_execution: true,
      },
    ],
    limitations: [],
    does_not_enable_execution: true,
  };
  const panel = mount(
    <StrategySignalPreviewPanel
      preview={preview}
      loading={false}
      error={false}
      singleAsset={{ symbol: '600000', asset_class: 'stock' }}
      onRiskPreview={() => undefined}
      onPaperShadowPreview={() => undefined}
      riskPreviewResult={null}
      riskPreviewLoading={false}
      riskPreviewError={false}
      paperShadowPreviewResult={null}
      paperShadowPreviewLoading={false}
      paperShadowPreviewError={false}
      attributionPreviewResult={null}
      attributionPreviewLoading={false}
      attributionPreviewError={false}
    />,
    'zh',
  );

  expect(panel.getByText('发现延迟证据')).toBeTruthy();
  expect(panel.getByText('核验晚于回放时点的 K 线')).toBeTruthy();
  expect(panel.getByText('首条延迟 K 线: 600000 · 2026-09-07')).toBeTruthy();
  expect(panel.getByText(/本预览不创建订单或成交/)).toBeTruthy();
  expect(panel.getByText(/不能证明历史时点可执行的表现/)).toBeTruthy();
  expect(panel.getByText(/不允许策略晋级/)).toBeTruthy();
});
