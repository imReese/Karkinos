import type { ShadowResearchCandidate } from './shadow-research-api';

export function resolveCandidateEngine(
  candidate: ShadowResearchCandidate | null | undefined,
): string {
  if (!candidate) return '—';

  // 1. Authoritative model_id directly from backend if available
  if (candidate.model_id) {
    return formatModelDisplayName(candidate.model_id);
  }

  // 2. Authoritative provider_id if available
  if (candidate.provider_id) {
    return formatModelDisplayName(candidate.provider_id);
  }

  const draftId = (candidate.draft_id || '').toLowerCase();
  const candId = (candidate.candidate_id || '').toLowerCase();

  // 3. Explicit model identifier saved in draft or candidate id
  if (
    draftId.includes('gemini') ||
    candId.includes('7f8a7bb') ||
    candId.includes('d02c03e')
  ) {
    return 'Gemini 3.8 Flash';
  }

  // DeepSeek Flash
  if (
    draftId.includes('deepseek-v7') ||
    candId.includes('9a4f21d') ||
    draftId.includes('flash')
  ) {
    return 'DeepSeek V4.1 Flash';
  }

  // DeepSeek Pro
  if (
    draftId.includes('51a80e75') ||
    draftId.includes('870abf84') ||
    draftId.includes('1952a2c4') ||
    draftId.includes('14876873') ||
    draftId.includes('v4') ||
    draftId.includes('v3') ||
    draftId.includes('v2') ||
    draftId.includes('v1') ||
    draftId.includes('deepseek') ||
    candidate.comparison?.deepseek_critique
  ) {
    return 'DeepSeek V4 Pro';
  }
  return '—';
}

export function formatModelDisplayName(
  rawModel: string | null | undefined,
  fallback?: string,
): string {
  if (!rawModel) return fallback ?? '—';
  const lower = rawModel.toLowerCase();
  if (lower.includes('deepseek-v4-pro') || lower.includes('v4-pro')) {
    return 'DeepSeek V4 Pro';
  }
  if (
    lower.includes('deepseek-flash') ||
    lower.includes('v4.1-flash') ||
    lower.includes('v4.1')
  ) {
    return 'DeepSeek V4.1 Flash';
  }
  if (lower.includes('gemini-3.8-flash') || lower.includes('gemini')) {
    return 'Gemini 3.8 Flash';
  }
  return rawModel;
}

export function formatDraftSummaryName(
  draftId: string | null | undefined,
  zh: boolean,
): string {
  if (!draftId) return zh ? '无记录' : 'Not recorded';
  const lower = draftId.toLowerCase();

  if (
    lower.includes('v7') ||
    lower.includes('gen7') ||
    lower.includes('gen-7')
  ) {
    return 'Gen 7 · DeepSeek V4.1 Flash';
  }
  if (
    lower.includes('v6') ||
    lower.includes('gen6') ||
    lower.includes('gen-6')
  ) {
    return 'Gen 6 · Gemini 3.8 Flash';
  }
  if (
    lower.includes('v5') ||
    lower.includes('gen5') ||
    lower.includes('gen-5')
  ) {
    return 'Gen 5 · Gemini 3.8 Flash';
  }
  if (
    lower.includes('v4') ||
    lower.includes('gen4') ||
    lower.includes('51a80e75')
  ) {
    return 'Gen 4 · DeepSeek V4 Pro';
  }
  if (
    lower.includes('v3') ||
    lower.includes('gen3') ||
    lower.includes('870abf84')
  ) {
    return 'Gen 3 · DeepSeek V4 Pro';
  }
  if (
    lower.includes('v2') ||
    lower.includes('gen2') ||
    lower.includes('1952a2c4')
  ) {
    return 'Gen 2 · DeepSeek V4 Pro';
  }
  if (
    lower.includes('v1') ||
    lower.includes('gen1') ||
    lower.includes('14876873')
  ) {
    return 'Gen 1 · DeepSeek V4 Pro';
  }

  // Generic fallback: clean ID
  const cleanId = draftId.replace(/^ai-strategy-draft-/, '');
  return cleanId.length > 12 ? `${cleanId.slice(0, 8)}…` : cleanId;
}

export function formatCandidateTitle(
  candidate: ShadowResearchCandidate | null | undefined,
  zh: boolean,
): string {
  if (!candidate) return zh ? '未选定策略' : 'No strategy selected';

  const lineage = candidate.comparison?.iteration_lineage;
  const genNum = lineage?.iteration_number;
  const draftId = (
    candidate.draft_id ||
    candidate.candidate_id ||
    ''
  ).toLowerCase();

  // 1. Explicit promoted generation titles from recorded draft ID
  if (draftId.includes('deepseek-v7') || draftId.includes('v7')) {
    return zh
      ? 'Gen 7 · 缩量超跌均值回归策略'
      : 'Gen 7 · Deep Pullback Reversion Strategy';
  }
  if (
    draftId.includes('gemini-v6') ||
    draftId.includes('deepseek-v6') ||
    draftId.includes('v6')
  ) {
    return zh
      ? 'Gen 6 · 量价共振波动防御策略'
      : 'Gen 6 · Volume-Price Resonance Defense';
  }
  if (
    draftId.includes('gemini-v5') ||
    draftId.includes('v5') ||
    candidate.candidate_id?.includes('7f8a7bb')
  ) {
    return zh
      ? 'Gen 5 · 中周期均线趋势回踩策略'
      : 'Gen 5 · Trend Pullback & Vol Defense';
  }
  if (draftId.includes('51a80e75') || draftId.includes('gen4')) {
    return zh ? 'Gen 4 · 短期均线反转策略' : 'Gen 4 · Short MA Reversal';
  }
  if (draftId.includes('870abf84') || draftId.includes('gen3')) {
    return zh ? 'Gen 3 · 波动率止损过滤策略' : 'Gen 3 · Volatility Stop Filter';
  }
  if (draftId.includes('1952a2c4') || draftId.includes('gen2')) {
    return zh
      ? 'Gen 2 · 滚动均线偏离跟踪策略'
      : 'Gen 2 · Rolling Mean Deviation';
  }
  if (draftId.includes('14876873') || draftId.includes('gen1')) {
    return zh ? 'Gen 1 · 双均线交叉基础策略' : 'Gen 1 · Dual MA Baseline';
  }

  // 2. Extract theme from hypothesis if available
  const hypo = (candidate.comparison?.economic_hypothesis || '').trim();
  if (hypo) {
    // If hypothesis has a title pattern like "第X代策略（...）：..." or "..."
    const titleMatch = hypo.match(
      /^(?:第[一二三四五六七八九十\d]+代策略)?(?:\s*[(（][^）)]+[）)])?[：:]?\s*([^。，；\n]{4,20})/,
    );
    if (titleMatch && titleMatch[1]) {
      const theme = titleMatch[1].replace(/^[（(][^）)]+[）)]\s*/, '').trim();
      if (theme.length >= 4) {
        return genNum ? `Gen ${genNum} · ${theme}` : theme;
      }
    }
  }

  // 3. Fallback
  const shortId = candidate.draft_id
    ? candidate.draft_id.replace(/^ai-strategy-draft-/, '').slice(0, 8)
    : candidate.candidate_id.replace(/^ai-shadow-candidate-/, '').slice(0, 8);

  if (genNum) {
    return zh
      ? `Gen ${genNum} · 策略候选 ${shortId}`
      : `Gen ${genNum} · Candidate ${shortId}`;
  }
  return zh ? `策略候选 ${shortId}` : `Candidate ${shortId}`;
}

export function formatCandidateOptionLabel(
  candidate: ShadowResearchCandidate,
  zh: boolean,
): string {
  const title = formatCandidateTitle(candidate, zh);
  const engine = resolveCandidateEngine(candidate);
  const engineBadge = engine !== '—' ? ` (${engine})` : '';

  // Compact label for select dropdowns
  return `${title}${engineBadge}`;
}
