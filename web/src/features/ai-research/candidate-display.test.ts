import { describe, expect, it } from 'vitest';
import {
  formatCandidateTitle,
  formatCandidateOptionLabel,
  formatDraftSummaryName,
  resolveCandidateEngine,
} from './candidate-display';
import type { ShadowResearchCandidate } from './shadow-research-api';

function makeMockCandidate(
  draftId: string,
  iteration?: number,
  hypothesis?: string,
): ShadowResearchCandidate {
  return {
    candidate_id: `cand-${draftId}`,
    run_id: 'run-1',
    session_id: 'session-1',
    draft_id: draftId,
    backtest_run_id: null,
    critique_id: null,
    baseline_result_id: 1,
    candidate_result_id: 2,
    status: 'awaiting_human_approval',
    recommendation: 'paper_shadow_review',
    promotion_status: 'awaiting_human_approval',
    created_at: '2026-10-14T14:30:00Z',
    updated_at: '2026-10-14T14:30:00Z',
    comparison: {
      economic_hypothesis: hypothesis ?? null,
      iteration_lineage: iteration
        ? {
            iteration_number: iteration,
            total_iterations: 7,
            formula_fingerprint: 'fp-1',
            parent_candidate_id: null,
            parent_draft_id: null,
            parent_formula_fingerprint: null,
            iteration_context_fingerprint: 'ctx-1',
            sequential_feedback_bound: true,
          }
        : null,
      promotion_gate: { status: 'pass', blockers: [] },
    },
    automatic_strategy_replacement_enabled: false,
    production_strategy_mutation_enabled: false,
    broker_submission_enabled: false,
    human_paper_shadow_approval_required: true,
  };
}

describe('candidate-display', () => {
  it('formats Gen 7 DeepSeek strategy title and option correctly', () => {
    const c7 = makeMockCandidate('ai-strategy-draft-deepseek-v7-promoted', 7);
    expect(formatCandidateTitle(c7, true)).toBe('Gen 7 · 缩量超跌均值回归策略');
    expect(formatCandidateTitle(c7, false)).toBe(
      'Gen 7 · Deep Pullback Reversion Strategy',
    );
    expect(resolveCandidateEngine(c7)).toBe('DeepSeek-V3');
    expect(formatCandidateOptionLabel(c7, true)).toBe(
      'Gen 7 · 缩量超跌均值回归策略 (DeepSeek-V3)',
    );
  });

  it('formats Gen 6 Gemini strategy title correctly', () => {
    const c6 = makeMockCandidate('ai-strategy-draft-gemini-v6-promoted', 6);
    expect(formatCandidateTitle(c6, true)).toBe('Gen 6 · 量价共振波动防御策略');
    expect(resolveCandidateEngine(c6)).toBe('Gemini 3.8 Flash');
    expect(formatCandidateOptionLabel(c6, true)).toBe(
      'Gen 6 · 量价共振波动防御策略 (Gemini 3.8 Flash)',
    );
  });

  it('formats Gen 5 Gemini strategy title correctly', () => {
    const c5 = makeMockCandidate('ai-strategy-draft-gemini-v5-promoted', 5);
    expect(formatCandidateTitle(c5, true)).toBe(
      'Gen 5 · 中周期均线趋势回踩策略',
    );
    expect(resolveCandidateEngine(c5)).toBe('Gemini 3.8 Flash');
  });

  it('formats draft summary names for parent lineages', () => {
    expect(
      formatDraftSummaryName('ai-strategy-draft-gemini-v6-promoted', true),
    ).toBe('Gen 6 · Gemini 3.8 Flash');
    expect(
      formatDraftSummaryName('ai-strategy-draft-deepseek-v7-promoted', true),
    ).toBe('Gen 7 · DeepSeek-V3');
    expect(formatDraftSummaryName(null, true)).toBe('无记录');
  });

  it('handles generic candidates gracefully with clean fallback', () => {
    const fallback = makeMockCandidate(
      'ai-strategy-draft-abc12345xyz',
      undefined,
      '在等权分配的股票池中捕捉突破',
    );
    expect(formatCandidateTitle(fallback, true)).toContain(
      '在等权分配的股票池中捕捉突破',
    );
  });
});
