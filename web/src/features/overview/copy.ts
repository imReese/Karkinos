import type { Locale } from '../../shared/locale';

import { overviewCopyEn } from './copy.en';
import { overviewCopyZh } from './copy.zh';

export const overviewCopy = {
  en: overviewCopyEn,
  zh: overviewCopyZh,
} satisfies Record<Locale, Record<string, unknown>>;

export type OverviewCopy = (typeof overviewCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    overview: OverviewCopy;
  }
}
