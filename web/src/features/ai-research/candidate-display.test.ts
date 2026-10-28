import { describe, expect, it } from 'vitest';
import {
  formatCandidateTitle,
  formatCandidateOptionLabel,
  formatDraftSummaryName,
  formatModelDisplayName,
  resolveCandidateEngine,
} from './candidate-display';
import type { ShadowResearchCandidate } from './shadow-research-api';

function makeMockCandidate(
  draftId: string,
  iteration?: number,
  hypothesis?: string,
  modelId?: string,
): ShadowResearchCandidate {
  return {
    candidate_id: `cand-${draftId}`,
    run_id: 'run-1',
    session_id: 'session-1',
    draft_id: draftId,
    model_id: modelId ?? null,
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
    expect(resolveCandidateEngine(c7)).toBe('DeepSeek V4.1 Flash');
    expect(formatCandidateOptionLabel(c7, true)).toBe(
      'Gen 7 · 缩量超跌均值回归策略 (DeepSeek V4.1 Flash)',
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
    ).toBe('Gen 7 · DeepSeek V4.1 Flash');
    expect(formatDraftSummaryName(null, true)).toBe('无记录');
    expect(
      formatDraftSummaryName('ai-strategy-draft-51a80e75-gen4', true),
    ).toBe('Gen 4 · DeepSeek V4 Pro');
    expect(
      formatDraftSummaryName('ai-strategy-draft-870abf84-gen3', true),
    ).toBe('Gen 3 · DeepSeek V4 Pro');
    expect(
      formatDraftSummaryName('ai-strategy-draft-1952a2c4-gen2', true),
    ).toBe('Gen 2 · DeepSeek V4 Pro');
    expect(
      formatDraftSummaryName('ai-strategy-draft-14876873-gen1', true),
    ).toBe('Gen 1 · DeepSeek V4 Pro');
  });

  it('formats Gen 1-4 DeepSeek V4 Pro strategy candidates correctly', () => {
    const c4 = makeMockCandidate('ai-strategy-draft-51a80e75-gen4', 4);
    expect(resolveCandidateEngine(c4)).toBe('DeepSeek V4 Pro');
    expect(formatCandidateOptionLabel(c4, true)).toContain('DeepSeek V4 Pro');

    const c3 = makeMockCandidate('ai-strategy-draft-870abf84-gen3', 3);
    expect(resolveCandidateEngine(c3)).toBe('DeepSeek V4 Pro');

    const c2 = makeMockCandidate('ai-strategy-draft-1952a2c4-gen2', 2);
    expect(resolveCandidateEngine(c2)).toBe('DeepSeek V4 Pro');

    const c1 = makeMockCandidate('ai-strategy-draft-14876873-gen1', 1);
    expect(resolveCandidateEngine(c1)).toBe('DeepSeek V4 Pro');
  });

  it('formats model display names from provider or session registration correctly', () => {
    expect(
      formatModelDisplayName(
        'karkinos.strategy_research.hypothesis.deepseek.v1:deepseek-v4-pro',
      ),
    ).toBe('DeepSeek V4 Pro');
    expect(formatModelDisplayName('deepseek-flash')).toBe(
      'DeepSeek V4.1 Flash',
    );
    expect(formatModelDisplayName('gemini-3.8-flash')).toBe('Gemini 3.8 Flash');
    expect(formatModelDisplayName(null, 'DeepSeek V4 Pro')).toBe(
      'DeepSeek V4 Pro',
    );
  });

  it('prefers authoritative model_id directly from candidate over heuristics', () => {
    const candidate = makeMockCandidate(
      'ai-strategy-draft-opaque-hash-1234',
      1,
      undefined,
      'karkinos.strategy_research.hypothesis.deepseek.v1:deepseek-v4-pro',
    );
    expect(resolveCandidateEngine(candidate)).toBe('DeepSeek V4 Pro');

    const geminiCandidate = makeMockCandidate(
      'ai-strategy-draft-opaque-hash-5678',
      1,
      undefined,
      'gemini-3.8-flash',
    );
    expect(resolveCandidateEngine(geminiCandidate)).toBe('Gemini 3.8 Flash');
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

  it('does not guess model name or strategy title merely by generation number', () => {
    const candidateGen1 = makeMockCandidate('opaque-draft-alpha', 1);
    expect(resolveCandidateEngine(candidateGen1)).toBe('—');
    expect(formatCandidateTitle(candidateGen1, true)).toBe(
      'Gen 1 · 策略候选 opaque-d',
    );

    const candidateGen7 = makeMockCandidate('opaque-draft-beta', 7);
    expect(resolveCandidateEngine(candidateGen7)).toBe('—');
    expect(formatCandidateTitle(candidateGen7, true)).toBe(
      'Gen 7 · 策略候选 opaque-d',
    );
  });
});
