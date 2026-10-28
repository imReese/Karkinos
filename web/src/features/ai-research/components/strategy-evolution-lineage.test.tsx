import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StrategyEvolutionLineage } from './strategy-evolution-lineage';
import type { ShadowResearchCandidate } from '../shadow-research-api';

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function createMockCandidate(
  id: string,
  iteration: number,
  total: number,
  sharpe: number,
  totalReturn: number,
  hypothesis: string,
): ShadowResearchCandidate {
  return {
    candidate_id: id,
    run_id: 'run-1',
    session_id: 'session-1',
    draft_id: `draft-${id}`,
    backtest_run_id: null,
    critique_id: null,
    baseline_result_id: 1,
    candidate_result_id: 2,
    status: 'awaiting_human_approval',
    recommendation: 'paper_shadow_review',
    promotion_status: 'awaiting_human_approval',
    created_at: '2026-08-11T16:00:00Z',
    updated_at: '2026-08-11T16:00:00Z',
    comparison: {
      economic_hypothesis: hypothesis,
      iteration_lineage: {
        iteration_number: iteration,
        total_iterations: total,
        formula_fingerprint: `fp-${id}`,
        parent_candidate_id: iteration > 1 ? `cand-${iteration - 1}` : null,
        parent_draft_id: null,
        parent_formula_fingerprint: null,
        iteration_context_fingerprint: `ctx-${id}`,
        sequential_feedback_bound: true,
      },
      candidate: {
        result_id: 2,
        total_return: totalReturn,
        sharpe,
        max_drawdown: -0.1,
        total_cost: 100,
        total_commission: 50,
        total_slippage: 50,
        total_trades: 20,
        gross_turnover: 10000,
        oos_fold_count: 5,
        mean_oos_return: 0.05,
        worst_oos_return: 0.01,
        oos_validation_status: 'pass',
        evidence_gate_status: 'pass',
        dataset_snapshot_id: 'snap-1',
      },
      promotion_gate: {
        status: 'pass',
        blockers: [],
      },
    },
    automatic_strategy_replacement_enabled: false,
    production_strategy_mutation_enabled: false,
    broker_submission_enabled: false,
    human_paper_shadow_approval_required: true,
  };
}

describe('StrategyEvolutionLineage', () => {
  it('renders generations in chronological order with deltas and handles click selection', () => {
    const candidates = [
      createMockCandidate(
        'cand-2',
        2,
        3,
        1.5,
        0.15,
        'Volume confirmation filter',
      ),
      createMockCandidate('cand-1', 1, 3, 1.1, 0.08, 'Base momentum breakout'),
      createMockCandidate(
        'cand-3',
        3,
        3,
        1.84,
        0.24,
        'Adaptive holding period',
      ),
    ];

    const onSelect = vi.fn();
    const verifiedWinners = new Set(['cand-3']);

    renderWithClient(
      <StrategyEvolutionLineage
        candidates={candidates}
        selectedCandidateId="cand-2"
        onSelectCandidate={onSelect}
        verifiedWinnerCandidateIds={verifiedWinners}
      />,
    );

    expect(screen.getByTestId('strategy-evolution-lineage')).toBeTruthy();
    expect(
      screen.getByTestId('strategy-lineage-sliding-indicator'),
    ).toBeTruthy();
    expect(screen.getByText('Base momentum breakout')).toBeTruthy();
    expect(screen.getByText('Volume confirmation filter')).toBeTruthy();
    expect(screen.getByText('Adaptive holding period')).toBeTruthy();

    // Winner badge
    expect(screen.getByText(/当日优选|Top Pick/)).toBeTruthy();

    // Click on Gen 3
    fireEvent.click(screen.getByText('Adaptive holding period'));
    expect(onSelect).toHaveBeenCalledWith('cand-3');
  });

  it('returns null gracefully when candidates array is empty', () => {
    const { container } = renderWithClient(
      <StrategyEvolutionLineage
        candidates={[]}
        selectedCandidateId={null}
        onSelectCandidate={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  describe('evidence validation parity across entrypoints', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('1. 正常报告: displays valid metrics and deltas for matching valid report', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/backtest/results/101') {
          return jsonResponse({
            id: 101,
            metrics: {
              sharpe: 2.5,
              total_return: 0.25,
              max_drawdown: -0.1,
            },
            evidence_invalidation: null,
          });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetchMock);

      const base = createMockCandidate(
        'cand-1',
        1,
        1,
        2.5,
        0.25,
        'Valid candidate',
      );
      const candidate: ShadowResearchCandidate = {
        ...base,
        candidate_result_id: 101,
        comparison: {
          ...base.comparison,
          candidate: undefined,
        },
      };

      renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
        />,
      );

      // Sharpe and total return should be rendered from source report
      await waitFor(() => {
        expect(screen.getByText('2.50')).toBeTruthy();
        expect(screen.getByText('25.0%')).toBeTruthy();
      });

      // No fake queued beacon should be rendered without real scheduler record
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      expect(screen.queryByText(/DeepSeek 已排队|待命中/)).toBeNull();
    });

    it('2. 已撤回报告: suppresses metrics and deltas when candidate is failed_closed or evidence is withdrawn', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/backtest/results/102') {
          return jsonResponse({
            id: 102,
            metrics: {
              sharpe: 2.5,
              total_return: 0.25,
              max_drawdown: -0.1,
            },
            evidence_invalidation: {
              status: 'withdrawn',
              reason: 'evidence_retracted',
            },
          });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetchMock);

      // Candidate marked failed_closed with evidence_invalidation
      const candidateFailedClosed: ShadowResearchCandidate = {
        ...createMockCandidate(
          'cand-failed',
          1,
          1,
          2.5,
          0.25,
          'Failed closed candidate',
        ),
        candidate_result_id: 102,
        status: 'failed_closed',
        evidence_invalidation: { status: 'withdrawn' },
      };

      renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidateFailedClosed]}
          selectedCandidateId="cand-failed"
          onSelectCandidate={() => {}}
        />,
      );

      // Metrics must NOT be displayed
      expect(screen.queryByText('2.50')).toBeNull();
      expect(screen.queryByText('+25.0%')).toBeNull();
      expect(screen.queryByText('25.0%')).toBeNull();

      // Dashes should be displayed instead
      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThanOrEqual(2);

      // Withdrawn badge should appear
      expect(
        screen.getByTestId('lineage-evidence-withdrawn-badge'),
      ).toBeTruthy();

      // No fake queued beacon should appear
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      expect(screen.queryByText(/DeepSeek 已排队|待命中/)).toBeNull();
    });

    it('3. 错 ID: suppresses metrics when backtest report ID mismatches candidate_result_id', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/backtest/results/103') {
          // Returning wrong ID 999 instead of 103
          return jsonResponse({
            id: 999,
            metrics: {
              sharpe: 2.5,
              total_return: 0.25,
              max_drawdown: -0.1,
            },
            evidence_invalidation: null,
          });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetchMock);

      const base = createMockCandidate(
        'cand-wrong-id',
        1,
        1,
        2.5,
        0.25,
        'Wrong id candidate',
      );
      const candidate: ShadowResearchCandidate = {
        ...base,
        candidate_result_id: 103,
        comparison: {
          ...base.comparison,
          candidate: undefined,
        },
      };

      renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-wrong-id"
          onSelectCandidate={() => {}}
        />,
      );

      await waitFor(() => {
        // Query finished with wrong ID, metrics must be suppressed
        expect(screen.queryByText('2.50')).toBeNull();
        expect(screen.queryByText('25.0%')).toBeNull();
      });

      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThanOrEqual(2);
    });

    it('4. 请求失败: suppresses metrics when backtest report query fails with network/server error', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/backtest/results/104') {
          return new Response(JSON.stringify({ error: 'internal_error' }), {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetchMock);

      const base = createMockCandidate(
        'cand-error',
        1,
        1,
        2.5,
        0.25,
        'Query error candidate',
      );
      const candidate: ShadowResearchCandidate = {
        ...base,
        candidate_result_id: 104,
        comparison: {
          ...base.comparison,
          candidate: undefined,
        },
      };

      renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-error"
          onSelectCandidate={() => {}}
        />,
      );

      await waitFor(() => {
        // Query failed, metrics must be suppressed
        expect(screen.queryByText('2.50')).toBeNull();
        expect(screen.queryByText('25.0%')).toBeNull();
      });

      const dashes = screen.getAllByText('—');
      expect(dashes.length).toBeGreaterThanOrEqual(2);
    });

    it('5. 调度信标: only renders queued beacon when genuine scheduler record is enqueued', () => {
      const candidate = createMockCandidate(
        'cand-1',
        1,
        1,
        1.5,
        0.1,
        'Baseline',
      );

      // Without scheduler record: no beacon
      const { unmount } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={null}
        />,
      );
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      unmount();

      // With blocked scheduler record: no beacon
      const { unmount: unmountBlocked } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={{ status: 'blocked', failure_code: 'off_peak_only' }}
        />,
      );
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      unmountBlocked();

      // With real enqueued record: renders beacon with model name from record
      const { unmount: unmountEnqueued } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={{
            status: 'enqueued',
            job_id: 'job-task-1',
            model_name: 'DeepSeek V4.1 Flash',
          }}
          persistedTasks={[{ id: 'job-task-1', status: 'pending' }]}
        />,
      );
      expect(screen.getByTestId('strategy-lineage-queued-beacon')).toBeTruthy();
      expect(
        screen.getByText(
          /DeepSeek V4.1 Flash 待命中|DeepSeek V4.1 Flash Scheduled/,
        ),
      ).toBeTruthy();
      expect(screen.getByText(/已排队|Queued/)).toBeTruthy();
      unmountEnqueued();

      // Lifecycle progression: running task suppresses queued beacon
      const { unmount: unmountRunning } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={{
            status: 'enqueued',
            job_id: 'job-task-1',
            model_name: 'DeepSeek V4.1 Flash',
          }}
          persistedTasks={[{ id: 'job-task-1', status: 'running' }]}
        />,
      );
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      unmountRunning();

      // Lifecycle progression: completed task suppresses queued beacon
      const { unmount: unmountCompleted } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={{
            status: 'enqueued',
            job_id: 'job-task-1',
            model_name: 'DeepSeek V4.1 Flash',
          }}
          persistedTasks={[{ id: 'job-task-1', status: 'completed' }]}
        />,
      );
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      unmountCompleted();

      // Lifecycle progression: failed task suppresses queued beacon
      const { unmount: unmountFailed } = renderWithClient(
        <StrategyEvolutionLineage
          candidates={[candidate]}
          selectedCandidateId="cand-1"
          onSelectCandidate={() => {}}
          schedulerRecord={{
            status: 'enqueued',
            job_id: 'job-task-1',
            model_name: 'DeepSeek V4.1 Flash',
          }}
          persistedTasks={[{ id: 'job-task-1', status: 'failed' }]}
        />,
      );
      expect(screen.queryByTestId('strategy-lineage-queued-beacon')).toBeNull();
      unmountFailed();
    });

    it('6. 两代对比差值: suppresses delta when either current or prior generation evidence is invalid', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/backtest/results/201') {
          return jsonResponse({
            id: 201,
            metrics: { sharpe: 1.5, total_return: 0.15, max_drawdown: -0.1 },
            evidence_invalidation: null,
          });
        }
        if (url === '/api/backtest/results/202') {
          // Gen 2 report is withdrawn!
          return jsonResponse({
            id: 202,
            metrics: { sharpe: 2.5, total_return: 0.25, max_drawdown: -0.05 },
            evidence_invalidation: { status: 'withdrawn' },
          });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetchMock);

      const baseG1 = createMockCandidate(
        'cand-g1',
        1,
        2,
        1.5,
        0.15,
        'Gen 1 candidate',
      );
      const gen1: ShadowResearchCandidate = {
        ...baseG1,
        candidate_result_id: 201,
        comparison: {
          ...baseG1.comparison,
          candidate: undefined,
        },
      };
      const baseG2 = createMockCandidate(
        'cand-g2',
        2,
        2,
        2.5,
        0.25,
        'Gen 2 candidate',
      );
      const gen2: ShadowResearchCandidate = {
        ...baseG2,
        candidate_result_id: 202,
        comparison: {
          ...baseG2.comparison,
          candidate: undefined,
        },
      };

      renderWithClient(
        <StrategyEvolutionLineage
          candidates={[gen1, gen2]}
          selectedCandidateId="cand-g2"
          onSelectCandidate={() => {}}
        />,
      );

      await waitFor(() => {
        // Gen 1 is valid, should display 1.50
        expect(screen.getByText('1.50')).toBeTruthy();
        // Gen 2 report is withdrawn, so 2.50 must be suppressed
        expect(screen.queryByText('2.50')).toBeNull();
      });

      // Deltas must NOT be shown
      expect(screen.queryByText('+1.00')).toBeNull();
      expect(screen.queryByText('+10.0%')).toBeNull();
    });
  });
});
