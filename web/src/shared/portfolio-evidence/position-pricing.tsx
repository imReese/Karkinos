import { useCopy } from '../i18n/context';
import { formatStaleReason } from '../stale-reason';
import type { Locale } from '../locale';
import type { Position } from './contracts';

const pricingLabels = {
  zh: {
    realtime_quote: '实时行情',
    session_close: '收盘价',
    published_nav: '已公布净值',
    estimated_nav: '估算净值',
    nav_pending: '已确认净值缺失',
    manual_mark: '手动估值',
    unavailable: '价格不可用',
    unknown: '定价状态待确认',
    non_authoritative: '非确认数据',
    missing: '缺少价格证据',
    conflicting: '价格证据冲突',
    stale: '价格待更新',
    error: '价格证据错误',
  },
  en: {
    realtime_quote: 'Live quote',
    session_close: 'Session close',
    published_nav: 'Published NAV',
    estimated_nav: 'Estimated NAV',
    nav_pending: 'Confirmed NAV unavailable',
    manual_mark: 'Manual valuation',
    unavailable: 'Price unavailable',
    unknown: 'Pricing unverified',
    non_authoritative: 'Unconfirmed data',
    missing: 'Price evidence missing',
    conflicting: 'Conflicting price evidence',
    stale: 'Price update required',
    error: 'Price evidence error',
  },
};

export function PositionPricing({
  position,
  locale,
}: {
  position: Position;
  locale: Locale;
}) {
  const labels = pricingLabels[locale];
  const copy = useCopy();
  const kind = position.pricing_kind ?? 'unknown';
  const date = position.pricing_as_of ? new Date(position.pricing_as_of) : null;
  const asOf =
    date && !Number.isNaN(date.getTime())
      ? new Intl.DateTimeFormat(
          'en-US',
          kind === 'realtime_quote'
            ? {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
                timeZone: 'Asia/Shanghai',
              }
            : { month: '2-digit', day: '2-digit', timeZone: 'Asia/Shanghai' },
        ).format(date)
      : null;
  const authority = position.pricing_authority;
  const authorityLabel =
    authority === 'non_authoritative' ||
    authority === 'missing' ||
    authority === 'conflicting'
      ? labels[authority]
      : authority !== 'authoritative' && kind !== 'unknown'
        ? labels.unknown
        : null;
  const quoteIssue =
    position.quote_status === 'error'
      ? labels.error
      : position.valuation_available === true &&
          !position.valuation_blockers?.length
        ? null
        : position.quote_status === 'stale'
          ? labels.stale
          : position.valuation_available === false ||
              position.valuation_blockers?.length
            ? labels.unavailable
            : null;
  return (
    <div
      className="text-[length:var(--app-font-size-micro)] leading-5"
      data-testid={`position-pricing-${position.symbol}`}
    >
      <span className="text-[var(--app-text-secondary)]">
        {labels[kind] ?? labels.unknown}
        {asOf ? ` · ${asOf}` : ''}
      </span>
      {authorityLabel || quoteIssue ? (
        <span className="block max-w-full whitespace-normal [overflow-wrap:anywhere] text-[var(--app-warning-text)]">
          {authorityLabel ??
            (position.stale_reason
              ? formatStaleReason(
                  position.stale_reason,
                  copy.common.staleReasons,
                )
              : quoteIssue)}
        </span>
      ) : null}
    </div>
  );
}
