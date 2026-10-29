import type { ShadowResearchCandidate } from './shadow-research-api';

const EXACT_MODEL_ALIASES: Record<string, string> = {
  'deepseek-v4-pro': 'DeepSeek V4 Pro',
  'deepseek-v4.1-flash': 'DeepSeek V4.1 Flash',
  'deepseek-flash': 'DeepSeek V4.1 Flash',
  'gemini-3.8-flash': 'Gemini 3.8 Flash',
};

export function resolveCandidateEngine(
  candidate: ShadowResearchCandidate | null | undefined,
): string {
  if (!candidate) return '—';

  // 1. Authoritative model_id directly from candidate metadata
  if (candidate.model_id) {
    return formatModelDisplayName(candidate.model_id);
  }

  // 2. Authoritative provider_id if available
  if (candidate.provider_id) {
    return formatModelDisplayName(candidate.provider_id);
  }

  return '—';
}

export function formatModelDisplayName(
  rawModel: string | null | undefined,
  fallback?: string,
): string {
  if (!rawModel) return fallback ?? '—';
  const trimmed = rawModel.trim();
  const normalizedKey = (
    trimmed.includes(':') ? trimmed.split(':').pop()! : trimmed
  )
    .trim()
    .toLowerCase();

  // Model aliases use exact matching only; unknown models retain their exact raw value.
  if (EXACT_MODEL_ALIASES[normalizedKey]) {
    return EXACT_MODEL_ALIASES[normalizedKey];
  }
  return trimmed;
}

export function formatDraftSummaryName(
  draftId: string | null | undefined,
  zh: boolean,
): string {
  if (!draftId) return zh ? '无记录' : 'Not recorded';
  const cleanId = draftId.replace(/^ai-strategy-draft-/, '');
  return cleanId.length > 12 ? `${cleanId.slice(0, 12)}…` : cleanId;
}

export function formatCandidateTitle(
  candidate: ShadowResearchCandidate | null | undefined,
  zh: boolean,
): string {
  if (!candidate) return zh ? '未选定策略' : 'No strategy selected';

  const lineage = candidate.comparison?.iteration_lineage;
  const genNum = lineage?.iteration_number;
  const shortId = candidate.draft_id
    ? candidate.draft_id.replace(/^ai-strategy-draft-/, '').slice(0, 8)
    : candidate.candidate_id.replace(/^ai-shadow-candidate-/, '').slice(0, 8);

  // 1. Prioritize saved explicit strategy name
  const candidateRecord = candidate as Record<string, unknown>;
  const savedName = (
    (typeof candidateRecord.strategy_name === 'string'
      ? candidateRecord.strategy_name
      : typeof candidateRecord.name === 'string'
        ? candidateRecord.name
        : '') || ''
  ).trim();
  if (savedName) {
    return genNum ? `Gen ${genNum} · ${savedName}` : savedName;
  }

  // 2. Extract theme from economic hypothesis
  const hypo = (candidate.comparison?.economic_hypothesis || '').trim();
  if (hypo) {
    const titleMatch = hypo.match(
      /^(?:(?:真实)?(?:研究)?(?:经济)?(?:核心)?假设|第[一二三四五六七八九十\d]+代策略)?(?:\s*[(（][^）)]+[）)])?[：:]?\s*([^。，；\n]{2,80})/,
    );
    const theme =
      titleMatch && titleMatch[1]
        ? titleMatch[1].replace(/^[（(][^）)]+[）)]\s*/, '').trim()
        : hypo.length <= 24
          ? hypo
          : `${hypo.slice(0, 20)}…`;
    if (theme.length >= 2) {
      return genNum ? `Gen ${genNum} · ${theme}` : theme;
    }
  }

  // 3. Fallback: draft ID is used strictly as an identifier, never to guess strategy type
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

  return `${title}${engineBadge}`;
}
