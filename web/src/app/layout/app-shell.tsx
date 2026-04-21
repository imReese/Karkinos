import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type SVGProps,
} from "react";

import { Link, useRouterState } from "@tanstack/react-router";

import { useCopy } from "../copy";
import { usePreferences, type Locale, type ThemePreference } from "../preferences";

const navItems = [
  { to: "/", key: "overview" },
  { to: "/portfolio", key: "portfolio" },
  { to: "/activity", key: "activity" },
  { to: "/risk", key: "risk" },
  { to: "/market", key: "market" },
  { to: "/settings", key: "settings" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const copy = useCopy();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="app-root h-screen w-full overflow-hidden">
      <div className="app-shell-frame flex h-screen w-full lg:gap-3 lg:p-3">
        <div
          className={`fixed inset-0 z-30 bg-black/50 transition lg:hidden ${
            mobileNavOpen ? "opacity-100" : "pointer-events-none opacity-0"
          }`}
          aria-hidden={!mobileNavOpen}
          onClick={() => setMobileNavOpen(false)}
        />

        <aside
          className={`app-shell-sidebar fixed inset-y-0 left-0 z-40 flex w-[min(82vw,320px)] flex-col border-r px-5 py-5 transition-transform duration-200 lg:relative lg:h-full lg:w-[260px] lg:translate-x-0 lg:px-6 lg:py-6 ${
            mobileNavOpen ? "translate-x-0" : "-translate-x-full"
          }`}
          aria-label={copy.shell.navigation}
        >
          <div className="mb-6 flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-1.5">
              <div className="app-product-mark">MyQuant</div>
              <div className="text-lg font-semibold leading-6">{copy.shell.title}</div>
              <p className="app-muted max-w-52 text-xs leading-5">{copy.shell.description}</p>
            </div>
            <button
              type="button"
              className="app-button-secondary rounded-xl px-3 py-2 text-sm lg:hidden"
              aria-label={copy.shell.closeNavigation}
              onClick={() => setMobileNavOpen(false)}
            >
              ✕
            </button>
          </div>

          <nav className="grid gap-2">
            {navItems.map((item) => {
              const active = pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileNavOpen(false)}
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

        <main className="app-shell-main flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="app-toolbar-shell shrink-0 border-b">
            <div className="flex items-center justify-between gap-4 px-4 py-2.5 sm:px-6 lg:px-8 xl:px-10 2xl:px-12">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="app-product-mark">MyQuant</div>
                  <div className="app-toolbar-divider hidden sm:block" aria-hidden="true" />
                  <div className="truncate text-sm font-semibold sm:text-[15px]">
                    {copy.shell.toolbarTitle}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 self-center">
                <div
                  className="hidden flex-wrap items-center gap-1.5 self-center xl:flex"
                  aria-label={copy.shell.accountStatus}
                >
                  <StatusChip label={copy.shell.accountStatus} value={copy.shell.ledgerMode} />
                  <StatusChip label={copy.shell.apiStatus} value={copy.shell.brokerMode} />
                  <StatusChip label={copy.shell.navStatus} value={copy.shell.valuationMode} />
                </div>

                <button
                  type="button"
                  className="app-button-secondary rounded-xl px-3 py-2 text-sm lg:hidden"
                  aria-label={
                    mobileNavOpen ? copy.shell.closeNavigation : copy.shell.openNavigation
                  }
                  aria-expanded={mobileNavOpen}
                  onClick={() => setMobileNavOpen((open) => !open)}
                >
                  {copy.shell.navigation}
                </button>

                <div className="toolbar-control-widget self-center">
                  <ThemeSwitcher
                    label={copy.shell.theme}
                    value={theme}
                    onChange={(value) => setTheme(value as ThemePreference)}
                    options={[
                      {
                        value: "system",
                        label: copy.shell.systemThemeLabel,
                        icon: SystemThemeIcon,
                      },
                      {
                        value: "light",
                        label: copy.shell.lightThemeLabel,
                        icon: LightThemeIcon,
                      },
                      {
                        value: "dark",
                        label: copy.shell.darkThemeLabel,
                        icon: DarkThemeIcon,
                      },
                    ]}
                  />
                  <div className="toolbar-control-separator" aria-hidden="true" />
                  <LanguageMenu
                    label={copy.shell.language}
                    value={locale}
                    onChange={(value) => setLocale(value as Locale)}
                  />
                </div>
              </div>
            </div>
          </header>

          <div className="app-shell-content min-h-0 flex-1 overflow-y-auto">
            <div className="w-full px-4 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8 xl:px-10 2xl:px-12">
              {children}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function LanguageMenu({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Locale;
  onChange: (value: Locale) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const currentLabel = value === "zh" ? "ZH" : "EN";

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        className="toolbar-control-trigger toolbar-control-trigger-block"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <GlobeIcon />
        <span className="text-[10px] font-medium tracking-[0.08em]">{currentLabel}</span>
      </button>
      {open ? (
        <div className="toolbar-floating-menu" role="menu" aria-label={label}>
          {([
            ["en", "EN"],
            ["zh", "ZH"],
          ] as const).map(([nextValue, menuLabel]) => {
            const active = nextValue === value;
            return (
              <button
                key={nextValue}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className={`toolbar-floating-item ${active ? "toolbar-floating-item-active" : ""}`}
                onClick={() => {
                  onChange(nextValue as Locale);
                  setOpen(false);
                }}
              >
                <span>{menuLabel}</span>
                {active ? <CheckIcon /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ThemeSwitcher({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: ThemePreference;
  onChange: (value: ThemePreference) => void;
  options: ReadonlyArray<{
    value: ThemePreference;
    label: string;
    icon: ComponentType<SVGProps<SVGSVGElement>>;
  }>;
}) {
  const activeIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  return (
    <div
      className="theme-switcher theme-switcher-compact theme-switcher-block"
      role="group"
      aria-label={label}
      style={{ ["--theme-index" as string]: activeIndex }}
    >
      <div className="theme-switcher-indicator" aria-hidden="true" />
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-label={option.label}
            aria-pressed={active}
            className={`theme-switcher-btn ${active ? "theme-switcher-btn-active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}

function SystemThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function LightThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function DarkThemeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3A7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-toolbar-chip app-toolbar-chip-subtle rounded-full px-2.5 py-1.5 text-[11px]">
      <span className="app-toolbar-label mr-1.5 uppercase tracking-[0.16em]">{label}</span>
      <span className="font-medium text-[var(--app-text)]">{value}</span>
    </div>
  );
}

function GlobeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a15.3 15.3 0 0 1 0 18" />
      <path d="M12 3a15.3 15.3 0 0 0 0 18" />
    </svg>
  );
}

function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
