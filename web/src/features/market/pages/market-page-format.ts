import type { AppCopy } from '../../../shared/i18n/context';

export function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(Math.round(seconds), 0)}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  }
  return `${Math.round(seconds / 86400)}d`;
}

export function getNoteTypeLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'note':
      return copy.market.note;
    case 'thesis':
      return copy.market.thesis;
    case 'catalyst':
      return copy.market.catalyst;
    default:
      return value;
  }
}

export function getPriorityLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'high':
      return copy.market.highPriority;
    case 'normal':
      return copy.market.normalPriority;
    case 'low':
      return copy.market.lowPriority;
    default:
      return value;
  }
}
