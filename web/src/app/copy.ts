import { activityCopy } from '../features/activity/copy';
import { aiResearchPageCopy } from '../features/ai-research/copy';
import { backtestCopy } from '../features/backtest/copy';
import { decisionCopy } from '../features/decision/copy';
import { marketCopy } from '../features/market/copy';
import { operationsPageCopy } from '../features/operations/copy';
import { overviewCopy } from '../features/overview/copy';
import { portfolioCopy } from '../features/portfolio/copy';
import { riskPageCopy } from '../features/risk/copy';
import { settingsCopy } from '../features/settings/copy';
import { tradingCopy } from '../features/trading/copy';
import { sharedCopy } from '../shared/i18n/catalog';
import { type ApplicationCopy, useCopy } from '../shared/i18n/context';
import { resolveLocalizedCatalog } from '../shared/i18n/locale-catalog';
import type { Locale } from '../shared/locale';
import { shellCopy } from './shell-copy';

export const copy = {
  en: {
    shell: shellCopy.en.shell,
    aiResearchPage: aiResearchPageCopy.en,
    operationsPage: operationsPageCopy.en,
    states: sharedCopy.en.states,
    common: sharedCopy.en.common,
    mode: sharedCopy.en.mode,
    overview: overviewCopy.en,
    portfolio: portfolioCopy.en,
    riskPage: riskPageCopy.en,
    decision: decisionCopy.en,
    trading: tradingCopy.en,
    backtest: backtestCopy.en,
    market: marketCopy.en,
    explainability: sharedCopy.en.explainability,
    activity: activityCopy.en,
    settings: settingsCopy.en,
    placeholder: shellCopy.en.placeholder,
  },
  zh: {
    shell: shellCopy.zh.shell,
    aiResearchPage: aiResearchPageCopy.zh,
    operationsPage: operationsPageCopy.zh,
    states: sharedCopy.zh.states,
    common: sharedCopy.zh.common,
    mode: sharedCopy.zh.mode,
    overview: overviewCopy.zh,
    portfolio: portfolioCopy.zh,
    riskPage: riskPageCopy.zh,
    decision: decisionCopy.zh,
    trading: tradingCopy.zh,
    backtest: backtestCopy.zh,
    market: marketCopy.zh,
    explainability: sharedCopy.zh.explainability,
    activity: activityCopy.zh,
    settings: settingsCopy.zh,
    placeholder: shellCopy.zh.placeholder,
  },
} satisfies Record<Locale, ApplicationCopy>;

export type AppCopy = ApplicationCopy;

export { useCopy };

export function getCopy(locale: Locale): ApplicationCopy {
  return resolveLocalizedCatalog<ApplicationCopy>(copy, locale);
}
