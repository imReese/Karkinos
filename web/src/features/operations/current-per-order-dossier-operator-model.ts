import { formatPublicStatus } from '../../shared/public-labels';
import type { OperationsLocale } from './controlled-operation-panel-primitives';

export interface CurrentPerOrderDossierOperatorPanelProps {
  locale: OperationsLocale;
}

export function adapterReadOnlyStatusLabel(
  status: string,
  locale: OperationsLocale,
) {
  if (status === 'observing_readonly') {
    return locale === 'zh' ? '只读观测中' : 'Read-only observation active';
  }
  return formatPublicStatus(status, locale);
}
