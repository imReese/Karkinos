import type { Locale } from '../../shared/locale';
import { isFundEstimateQuoteSource } from '../../shared/market-data-status';
import { formatPublicStatus } from '../../shared/public-labels';
import type { MarketHealthQuote } from './api';

type MarketQuoteRecord = Pick<
  MarketHealthQuote,
  'asset_class' | 'instrument_type'
> & {
  quote_status: string;
  quote_source?: string | null;
};

// A healthy quote status also covers published NAVs and stored session prices;
// it does not establish a realtime feed or the current market session.
export function formatMarketQuoteLabel(
  quote: MarketQuoteRecord | null | undefined,
  locale: Locale,
) {
  if (
    !quote ||
    !['live', 'confirmed', 'cache', 'estimated', 'stale'].includes(
      quote.quote_status,
    )
  ) {
    return formatPublicStatus(quote?.quote_status ?? 'unknown', locale);
  }

  const instrument = quote.instrument_type ?? quote.asset_class;
  const isFund = ['fund', 'open_end_fund', 'openend_fund'].includes(instrument);
  const source = quote.quote_source?.trim().toLowerCase();
  const estimated =
    quote.quote_status === 'estimated' || isFundEstimateQuoteSource(source);
  const publishedNav =
    isFund &&
    (source === 'tushare_fund_nav' ||
      source === 'eastmoney_fund_page' ||
      quote.quote_status === 'confirmed');
  const label = estimated
    ? isFund
      ? locale === 'zh'
        ? '估算净值 · 非确认数据'
        : 'Estimated NAV · unconfirmed'
      : locale === 'zh'
        ? '估算行情'
        : 'Estimated quote'
    : publishedNav
      ? locale === 'zh'
        ? '已公布净值'
        : 'Published NAV'
      : locale === 'zh'
        ? '行情记录'
        : 'Recorded quote';

  return quote.quote_status === 'stale'
    ? `${label} · ${locale === 'zh' ? '待更新' : 'Update required'}`
    : label;
}

export function marketQuoteCacheLabel(
  quote:
    | (Pick<MarketHealthQuote, 'using_persistent_cache'> & {
        quote_status: string;
      })
    | null
    | undefined,
  locale: Locale,
) {
  return quote?.using_persistent_cache || quote?.quote_status === 'cache'
    ? locale === 'zh'
      ? '缓存记录'
      : 'Cached record'
    : null;
}
