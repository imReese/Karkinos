import type { Locale } from '../../shared/locale';

import { portfolioEnCopy } from './copy.en';
import { portfolioZhCopy } from './copy.zh';

export const portfolioCopy = {
  en: portfolioEnCopy,
  zh: portfolioZhCopy,
} satisfies Record<Locale, Record<string, unknown>>;

export type PortfolioCopy = (typeof portfolioCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    portfolio: PortfolioCopy;
  }
}
