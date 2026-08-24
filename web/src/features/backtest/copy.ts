import type { Locale } from '../../shared/locale';

import { backtestDetailsCopy } from './copy-details';
import { backtestPageEn } from './copy-page.en';
import { backtestPageZh } from './copy-page.zh';

export const backtestCopy = {
  en: {
    page: backtestPageEn,
    ...backtestDetailsCopy.en,
  },
  zh: {
    page: backtestPageZh,
    ...backtestDetailsCopy.zh,
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type BacktestCopy = (typeof backtestCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    backtest: BacktestCopy;
  }
}
