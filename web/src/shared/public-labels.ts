import type { Locale } from './locale';
import { CODE_LABELS } from './public-code-labels';
import {
  BROKER_EVIDENCE_TYPE_LABELS,
  EVIDENCE_REFERENCE_TYPE_LABELS,
  EVIDENCE_SOURCE_LABELS,
  NOTE_LABELS,
  REVIEW_ACTION_LABELS,
  STATUS_LABELS,
} from './public-context-labels';

function normalized(value: string | null | undefined) {
  const text = value?.trim();
  return text && text.length > 0 ? text : '--';
}

function looksLikeUnmappedEnglishNote(value: string) {
  return (
    /[A-Za-z]/.test(value) &&
    !/[\u4e00-\u9fff]/.test(value) &&
    /^[A-Za-z0-9\s.,;:'"()!?/@+-]+$/.test(value)
  );
}

function fallbackLabel(value: string, locale: Locale, kind: string) {
  if (value === '--') {
    return value;
  }
  if (locale === 'zh' && looksLikeUnmappedEnglishNote(value)) {
    if (kind === 'status') {
      return '待确认状态';
    }
    if (kind === 'note') {
      return '待人工复核说明';
    }
    return '待人工复核项';
  }
  const hasWhitespace = /\s/.test(value);
  const looksLikeSnakeCode = !hasWhitespace && value.includes('_');
  const looksLikeDottedCode =
    !hasWhitespace &&
    value.includes('.') &&
    /[A-Za-z]/.test(value) &&
    /^[A-Za-z0-9_.:-]+$/.test(value);
  if (looksLikeSnakeCode || looksLikeDottedCode) {
    if (locale === 'zh') {
      if (kind === 'status') {
        return '待确认状态';
      }
      if (kind === 'note') {
        return '待人工复核说明';
      }
      return '待人工复核项';
    }
    if (kind === 'status') {
      return 'Status needs review';
    }
    if (kind === 'note') {
      return 'Review note';
    }
    return 'Review item';
  }
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(' ');
}

export function formatPublicStatus(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    STATUS_LABELS[locale][key] ??
    CODE_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'status')
  );
}

export function formatPublicCode(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    CODE_LABELS[locale][key] ??
    STATUS_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'code')
  );
}

export function formatPublicNote(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    NOTE_LABELS[locale][key] ??
    CODE_LABELS[locale][key] ??
    STATUS_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'note')
  );
}

export function formatPublicOperationalNote(
  value: string | null | undefined,
  locale: Locale,
) {
  const text = value?.trim();
  if (!text) {
    return null;
  }

  if (/^Prepared from signal action \d+\.$/.test(text)) {
    return locale === 'zh'
      ? '已从决策待办生成手工确认订单。'
      : 'Prepared from Decision action queue.';
  }

  return (
    NOTE_LABELS[locale][text] ??
    CODE_LABELS[locale][text] ??
    STATUS_LABELS[locale][text] ??
    (locale === 'zh' && looksLikeUnmappedEnglishNote(text)
      ? '待人工复核说明'
      : looksLikeInternalCode(text)
        ? locale === 'zh'
          ? '待人工复核说明'
          : 'Review note'
        : text)
  );
}

export function formatPublicReviewActionLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    REVIEW_ACTION_LABELS[locale][key] ??
    STATUS_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'code')
  );
}

export function formatPublicCodeList(values: string[], locale: Locale) {
  return values.map((value) => formatPublicCode(value, locale));
}

export function formatPublicEvidenceReference(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  if (key === '--') {
    return key;
  }

  const brokerReference = parseBrokerEvidenceReference(key);
  if (brokerReference) {
    const source =
      EVIDENCE_SOURCE_LABELS[locale][brokerReference.sourceType] ??
      formatPublicCode(brokerReference.sourceType, locale);
    const eventType =
      BROKER_EVIDENCE_TYPE_LABELS[locale][brokerReference.eventType] ??
      formatPublicCode(brokerReference.eventType, locale);
    return [
      source,
      brokerReference.subject,
      eventType,
      brokerReference.importRunId,
    ]
      .filter(Boolean)
      .join(' · ');
  }

  const omsTransitionReference = parseOmsTransitionEvidenceReference(
    key,
    locale,
  );
  if (omsTransitionReference) {
    return omsTransitionReference;
  }

  const publicReference = parsePublicEvidenceReference(key, locale);
  if (publicReference) {
    return publicReference;
  }

  return formatPublicCode(key, locale);
}

function parsePublicEvidenceReference(reference: string, locale: Locale) {
  const [rawType, ...parts] = reference.split(':');
  if (parts.length === 0) {
    return null;
  }
  const label = EVIDENCE_REFERENCE_TYPE_LABELS[locale][rawType];
  if (!label) {
    return null;
  }
  const auditRef = publicEvidenceAuditRef(parts);
  return auditRef ? `${label} · ${auditRef}` : label;
}

function parseOmsTransitionEvidenceReference(
  reference: string,
  locale: Locale,
) {
  const [rawType, orderId, sequence, status] = reference.split(':');
  if (rawType !== 'oms_transition' || !orderId || !sequence || !status) {
    return null;
  }

  const label = locale === 'zh' ? 'OMS 状态变更' : 'OMS transition';
  return `${label} · ${orderId} #${sequence} ${formatOmsTransitionStatus(
    status,
    locale,
  )}`;
}

function formatOmsTransitionStatus(value: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    accepted: {
      en: 'Accepted',
      zh: '已接受模拟',
    },
    cancelled: {
      en: 'Cancelled',
      zh: '已取消',
    },
    expired: {
      en: 'Expired',
      zh: '已过期',
    },
    filled: {
      en: 'Filled',
      zh: '已成交',
    },
    partially_filled: {
      en: 'Partially Filled',
      zh: '部分成交',
    },
    reconciled: {
      en: 'Reconciled',
      zh: '已对账',
    },
    rejected: {
      en: 'Rejected',
      zh: '已拒绝',
    },
    staged: {
      en: 'Staged',
      zh: '已暂存',
    },
    submitted: {
      en: 'Submitted',
      zh: '已提交模拟',
    },
  };

  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function publicEvidenceAuditRef(parts: string[]) {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const candidate = parts[index]?.trim();
    if (candidate) {
      return candidate;
    }
  }
  return null;
}

function parseBrokerEvidenceReference(reference: string) {
  const [sourceType, importRunId, subject, ...eventTypeParts] =
    reference.split(':');
  if (
    sourceType !== 'broker_event' ||
    !importRunId ||
    !subject ||
    eventTypeParts.length === 0
  ) {
    return null;
  }
  const eventType = eventTypeParts.join(':');
  return {
    sourceType,
    importRunId,
    subject,
    eventType,
  };
}

function looksLikeInternalCode(value: string) {
  return /^[a-z][a-z0-9]*(?:[._][a-z0-9]+)+$/i.test(value);
}
