import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { StrategyEvolutionLineage } from './strategy-evolution-lineage';
import type { ShadowResearchCandidate } from '../shadow-research-api';

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
});
