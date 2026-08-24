import { createContext, useContext } from 'react';

import type { Locale } from '../locale';

export type { Locale } from '../locale';
export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export type PreferencesContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  resolvedTheme: ResolvedTheme;
};

export const PreferencesContext = createContext<PreferencesContextValue>({
  locale: 'en',
  setLocale: () => undefined,
  theme: 'system',
  setTheme: () => undefined,
  resolvedTheme: 'dark',
});

export function usePreferences() {
  return useContext(PreferencesContext);
}
