import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Locale = "en" | "zh";
export type ThemePreference = "system" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

type PreferencesContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  resolvedTheme: ResolvedTheme;
};

const PreferencesContext = createContext<PreferencesContextValue>({
  locale: "en",
  setLocale: () => undefined,
  theme: "system",
  setTheme: () => undefined,
  resolvedTheme: "dark",
});

const LOCALE_KEY = "myquant.locale";
const THEME_KEY = "myquant.theme";

function resolveSystemTheme(): ResolvedTheme {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: light)").matches
  ) {
    return "light";
  }
  return "dark";
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    if (typeof window === "undefined") {
      return "en";
    }
    const stored = window.localStorage.getItem(LOCALE_KEY);
    return stored === "zh" ? "zh" : "en";
  });
  const [theme, setTheme] = useState<ThemePreference>(() => {
    if (typeof window === "undefined") {
      return "system";
    }
    const stored = window.localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : "system";
  });
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(
    resolveSystemTheme(),
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LOCALE_KEY, locale);
  }, [locale]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(THEME_KEY, theme);

    const mediaQuery = window.matchMedia("(prefers-color-scheme: light)");
    const applyTheme = () => {
      const nextTheme = theme === "system" ? resolveSystemTheme() : theme;
      setResolvedTheme(nextTheme);
      document.documentElement.dataset.theme = nextTheme;
      document.documentElement.style.colorScheme = nextTheme;
    };

    applyTheme();
    mediaQuery.addEventListener("change", applyTheme);

    return () => {
      mediaQuery.removeEventListener("change", applyTheme);
    };
  }, [theme]);

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      theme,
      setTheme,
      resolvedTheme,
    }),
    [locale, theme, resolvedTheme],
  );

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences() {
  return useContext(PreferencesContext);
}
