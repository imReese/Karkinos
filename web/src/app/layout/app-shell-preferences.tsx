import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type SVGProps,
} from 'react';

import { useMotionPresence } from '../../shared/motion';
import type { Locale, ThemePreference } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import {
  CheckIcon,
  DarkThemeIcon,
  GlobeIcon,
  LightThemeIcon,
  SystemThemeIcon,
} from './app-shell-icons';

type ThemeOption = {
  value: ThemePreference;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
};

type AppShellPreferencesProps = {
  copy: AppCopy;
  locale: Locale;
  onLocaleChange: (value: Locale) => void;
  onThemeChange: (value: ThemePreference) => void;
  theme: ThemePreference;
};

export function AppShellPreferences({
  copy,
  locale,
  onLocaleChange,
  onThemeChange,
  theme,
}: AppShellPreferencesProps) {
  const themeOptions: ReadonlyArray<ThemeOption> = [
    {
      value: 'system',
      label: copy.shell.systemThemeLabel,
      icon: SystemThemeIcon,
    },
    {
      value: 'light',
      label: copy.shell.lightThemeLabel,
      icon: LightThemeIcon,
    },
    {
      value: 'dark',
      label: copy.shell.darkThemeLabel,
      icon: DarkThemeIcon,
    },
  ];

  return (
    <div className="flex min-w-0 shrink-0 flex-row items-center justify-end whitespace-nowrap">
      <div className="hidden min-w-0 flex-row items-center gap-2 sm:flex">
        <ThemeSwitcher
          label={copy.shell.theme}
          value={theme}
          onChange={onThemeChange}
          options={themeOptions}
        />
        <LanguageMenu
          label={copy.shell.language}
          value={locale}
          onChange={onLocaleChange}
        />
      </div>
      <div className="sm:hidden">
        <PreferenceMenu
          themeLabel={copy.shell.theme}
          languageLabel={copy.shell.language}
          theme={theme}
          locale={locale}
          onThemeChange={onThemeChange}
          onLocaleChange={onLocaleChange}
          themeOptions={themeOptions}
        />
      </div>
    </div>
  );
}

function PreferenceMenu({
  themeLabel,
  languageLabel,
  theme,
  locale,
  onThemeChange,
  onLocaleChange,
  themeOptions,
}: {
  themeLabel: string;
  languageLabel: string;
  theme: ThemePreference;
  locale: Locale;
  onThemeChange: (value: ThemePreference) => void;
  onLocaleChange: (value: Locale) => void;
  themeOptions: ReadonlyArray<ThemeOption>;
}) {
  const [open, setOpen] = useState(false);
  const presence = useMotionPresence(open);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const wasOpenRef = useRef(false);
  const activeTheme =
    themeOptions.find((option) => option.value === theme) ?? themeOptions[0];
  const ActiveThemeIcon = activeTheme?.icon ?? SystemThemeIcon;
  const menuLabel = `${themeLabel} · ${languageLabel}`;

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
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  useEffect(() => {
    if (
      wasOpenRef.current &&
      !open &&
      rootRef.current?.contains(document.activeElement)
    ) {
      triggerRef.current?.focus();
    }
    wasOpenRef.current = open;
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        className={`app-button-secondary inline-flex h-8 w-8 items-center justify-center rounded-[var(--app-radius-control)] p-0 ${
          open
            ? 'border-[var(--app-accent-border)] text-[var(--app-accent)]'
            : ''
        }`}
        data-testid="mobile-preferences-toggle"
        aria-label={menuLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <ActiveThemeIcon className="h-4 w-4" aria-hidden="true" />
      </button>
      {presence.mounted ? (
        <div
          role="dialog"
          aria-label={menuLabel}
          aria-hidden={presence.state === 'closing' ? true : undefined}
          inert={presence.state === 'closing'}
          data-motion-state={presence.state}
          className="app-shell-popover absolute right-0 top-[calc(100%+6px)] z-[70] w-[min(18rem,calc(100vw-1.5rem))] rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3 shadow-[var(--app-shadow-overlay)]"
        >
          <div className="app-kicker">{themeLabel}</div>
          <div className="mt-2 grid grid-cols-3 gap-1" role="group">
            {themeOptions.map((option) => {
              const Icon = option.icon;
              const active = option.value === theme;
              return (
                <button
                  key={option.value}
                  type="button"
                  aria-label={option.label}
                  aria-pressed={active}
                  className={`app-type-label inline-flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--app-radius-control)] px-2 font-semibold transition-colors ${
                    active
                      ? 'bg-[var(--app-accent-bg)] text-[var(--app-accent)]'
                      : 'text-[var(--app-text-secondary)] hover:bg-[var(--app-accent-bg)] hover:text-[var(--app-text)]'
                  }`}
                  onClick={() => {
                    onThemeChange(option.value);
                    setOpen(false);
                  }}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                  <span className="truncate">{option.label}</span>
                </button>
              );
            })}
          </div>
          <div className="my-3 border-t border-[var(--app-divider)]" />
          <div className="app-kicker">{languageLabel}</div>
          <div className="mt-2 grid grid-cols-2 gap-1" role="group">
            {(
              [
                ['en', 'English'],
                ['zh', '中文'],
              ] as const
            ).map(([value, label]) => {
              const active = value === locale;
              return (
                <button
                  key={value}
                  type="button"
                  aria-label={label}
                  aria-pressed={active}
                  className={`app-type-label min-h-11 rounded-[var(--app-radius-control)] px-3 font-semibold transition-colors ${
                    active
                      ? 'bg-[var(--app-accent-bg)] text-[var(--app-accent)]'
                      : 'text-[var(--app-text-secondary)] hover:bg-[var(--app-accent-bg)] hover:text-[var(--app-text)]'
                  }`}
                  onClick={() => {
                    onLocaleChange(value);
                    setOpen(false);
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
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
  const presence = useMotionPresence(open);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const wasOpenRef = useRef(false);
  const currentLabel = value === 'zh' ? '中文' : 'English';

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
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);

    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  useEffect(() => {
    if (
      wasOpenRef.current &&
      !open &&
      rootRef.current?.contains(document.activeElement)
    ) {
      triggerRef.current?.focus();
    }
    wasOpenRef.current = open;
  }, [open]);

  return (
    <div ref={rootRef} className="relative w-auto">
      <button
        ref={triggerRef}
        type="button"
        className={`app-language-control inline-flex h-8 w-auto items-center gap-2 whitespace-nowrap rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-transparent px-2.5 text-xs font-semibold text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-surface-overlay)] hover:text-[var(--app-text)] ${
          open ? 'bg-[var(--app-surface-overlay)] text-[var(--app-text)]' : ''
        }`}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <GlobeIcon className="h-3.5 w-3.5" />
        <span className="hidden min-w-max whitespace-nowrap sm:block">
          {currentLabel}
        </span>
      </button>
      {presence.mounted ? (
        <div
          className="app-shell-popover absolute right-0 top-[calc(100%+6px)] z-[60] min-w-max rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-1 shadow-[var(--app-shadow-overlay)]"
          role="menu"
          aria-label={label}
          aria-hidden={presence.state === 'closing' ? true : undefined}
          inert={presence.state === 'closing'}
          data-motion-state={presence.state}
        >
          {(
            [
              ['en', 'English'],
              ['zh', '中文'],
            ] as const
          ).map(([nextValue, menuLabel]) => {
            const active = nextValue === value;
            return (
              <button
                key={nextValue}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className={`flex w-full min-w-max items-center justify-between gap-3 rounded-[var(--app-radius-control)] bg-transparent px-3 py-2 text-left text-xs font-medium text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-accent-bg)] hover:text-[var(--app-text)] ${
                  active ? 'text-[var(--app-text)]' : ''
                }`}
                onClick={() => {
                  onChange(nextValue);
                  setOpen(false);
                }}
              >
                <span>{menuLabel}</span>
                {active ? <CheckIcon className="h-3 w-3" /> : null}
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
  options: ReadonlyArray<ThemeOption>;
}) {
  return (
    <div
      className="app-theme-switcher inline-flex h-8 flex-row items-center gap-0.5 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-transparent p-0.5"
      role="group"
      aria-label={label}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-label={option.label}
            aria-pressed={active}
            className={`app-theme-switcher-option inline-flex h-6 items-center justify-center rounded-[var(--app-radius-control)] px-1.5 text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-surface-overlay)] hover:text-[var(--app-text)] sm:px-2 [&>svg]:h-3.5 [&>svg]:w-3.5 ${
              active
                ? 'bg-[var(--app-surface-overlay)] text-[var(--app-accent)] shadow-[inset_0_-2px_0_var(--app-accent)]'
                : ''
            }`}
            onClick={() => onChange(option.value)}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}
