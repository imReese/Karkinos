import { describe, expect, it } from 'vitest';
import {
  formatCandidateOptionLabel,
  formatCandidateTitle,
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
  it('formats strategy title from economic hypothesis, never guessing from draft ID', () => {
    // Hypothesis is prioritized, even if draft ID contains v7, v6, v5
    const c7 = makeMockCandidate(
      'ai-strategy-draft-deepseek-v7-promoted',
      7,
      '缩量超跌均值回归策略',
      'deepseek-flash',
    );
    expect(formatCandidateTitle(c7, true)).toBe('Gen 7 · 缩量超跌均值回归策略');
    expect(resolveCandidateEngine(c7)).toBe('DeepSeek V4.1 Flash');
    expect(formatCandidateOptionLabel(c7, true)).toBe(
      'Gen 7 · 缩量超跌均值回归策略 (DeepSeek V4.1 Flash)',
    );

    // When draft ID contains v5 but hypothesis is something else, hypothesis MUST win
    const c5 = makeMockCandidate(
      'ai-strategy-draft-gemini-v5-custom',
      5,
      '真实研究假设：高频量价共振反转',
      'gemini-3.8-flash',
    );
    expect(formatCandidateTitle(c5, true)).toBe('Gen 5 · 高频量价共振反转');
    expect(resolveCandidateEngine(c5)).toBe('Gemini 3.8 Flash');

    // When no hypothesis is provided, draft ID acts strictly as identifier, never guessing strategy type
    const cNoHypo = makeMockCandidate('ai-strategy-draft-v5-opaque-1234', 5);
    expect(formatCandidateTitle(cNoHypo, true)).toBe(
      'Gen 5 · 策略候选 v5-opaqu',
    );
    expect(formatCandidateTitle(cNoHypo, false)).toBe(
      'Gen 5 · Candidate v5-opaqu',
    );
  });

  it('preserves exact raw model values for unknown models like gemini-2.5-pro', () => {
    // Crucial requirement: gemini-2.5-pro must NOT be formatted as Gemini 3.8 Flash
    expect(formatModelDisplayName('gemini-2.5-pro')).toBe('gemini-2.5-pro');
    expect(formatModelDisplayName('gemini-2.0-flash')).toBe('gemini-2.0-flash');
    expect(formatModelDisplayName('deepseek-r1-custom')).toBe(
      'deepseek-r1-custom',
    );

    // Known exact aliases still format nicely
    expect(
      formatModelDisplayName(
        'karkinos.strategy_research.hypothesis.deepseek.v1:deepseek-v4-pro',
      ),
    ).toBe('DeepSeek V4 Pro');
    expect(formatModelDisplayName('deepseek-v4-pro')).toBe('DeepSeek V4 Pro');
    expect(formatModelDisplayName('deepseek-flash')).toBe(
      'DeepSeek V4.1 Flash',
    );
    expect(formatModelDisplayName('gemini-3.8-flash')).toBe('Gemini 3.8 Flash');
    expect(formatModelDisplayName(null, 'DeepSeek V4 Pro')).toBe(
      'DeepSeek V4 Pro',
    );
  });

  it('resolves candidate engine strictly from model_id or provider_id without guessing from draft ID', () => {
    const candidate = makeMockCandidate(
      'ai-strategy-draft-opaque-hash-1234',
      1,
      undefined,
      'gemini-2.5-pro',
    );
    expect(resolveCandidateEngine(candidate)).toBe('gemini-2.5-pro');

    const noModelCandidate = makeMockCandidate(
      'ai-strategy-draft-v5-random',
      1,
    );
    expect(resolveCandidateEngine(noModelCandidate)).toBe('—');
  });

  it('formats draft summary names as clean identifiers without guessing models', () => {
    expect(formatDraftSummaryName(null, true)).toBe('无记录');
    expect(
      formatDraftSummaryName('ai-strategy-draft-gemini-v6-promoted', true),
    ).toBe('gemini-v6-pr…');
    expect(
      formatDraftSummaryName('ai-strategy-draft-51a80e75-gen4', true),
    ).toBe('51a80e75-gen…');
  });
});
