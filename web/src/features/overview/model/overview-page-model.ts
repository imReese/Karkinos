import { getErrorMessage } from '../../../shared/error-message';
import type { AppCopy } from '../../../shared/i18n/context';
export function getEquityCurveErrorDetail(error: unknown, copy: AppCopy) {
  const detail = getErrorMessage(error);
  if (
    detail.includes(
      'Current valuation facts have not been published as an immutable snapshot',
    )
  ) {
    return copy.overview.curveSnapshotPending;
  }
  return `${copy.overview.curveError} ${detail}`;
}
