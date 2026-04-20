import type { ReactNode } from "react";

import { Link, useRouterState } from "@tanstack/react-router";

import { useCopy } from "../copy";
import { usePreferences, type Locale, type ThemePreference } from "../preferences";

const navItems = [
  { to: "/", key: "overview" },
  { to: "/portfolio", key: "portfolio" },
  { to: "/activity", key: "activity" },
  { to: "/market", key: "market" },
  { to: "/settings", key: "settings" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const copy = useCopy();

  return (
    <div className="app-root min-h-screen">
      <div className="mx-auto grid min-h-screen max-w-[1600px] grid-cols-1 lg:grid-cols-[240px_1fr]">
        <aside className="border-b px-6 py-6 lg:border-b-0 lg:border-r" style={{ borderColor: "var(--app-border)" }}>
          <div className="mb-8">
            <div className="app-kicker text-xs font-medium uppercase tracking-[0.24em]">
              MyQuant
            </div>
            <div className="mt-2 text-2xl font-semibold">{copy.shell.title}</div>
            <p className="app-muted mt-3 max-w-52 text-sm leading-6">
              {copy.shell.description}
            </p>
          </div>

          <div className="mb-6 space-y-4">
            <div>
              <div className="app-kicker mb-2 text-xs font-medium uppercase tracking-[0.18em]">
                {copy.shell.language}
              </div>
              <div className="flex gap-2">
                {([
                  ["en", "EN"],
                  ["zh", "中文"],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setLocale(value as Locale)}
                    className={`rounded-xl px-3 py-2 text-sm transition ${
                      locale === value
                        ? "app-button-primary"
                        : "app-button-secondary"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="app-kicker mb-2 text-xs font-medium uppercase tracking-[0.18em]">
                {copy.shell.theme}
              </div>
              <div className="grid gap-2">
                {([
                  ["light", copy.shell.light],
                  ["dark", copy.shell.dark],
                  ["system", copy.shell.system],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setTheme(value as ThemePreference)}
                    className={`rounded-xl px-3 py-2 text-left text-sm transition ${
                      theme === value ? "app-button-primary" : "app-button-secondary"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <nav className="grid gap-2">
            {navItems.map((item) => {
              const active = pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`app-nav-item rounded-xl px-4 py-3 text-sm transition ${
                    active ? "app-nav-item-active" : ""
                  }`}
                >
                  {copy.shell.nav[item.key]}
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="px-6 py-6 lg:px-10 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
