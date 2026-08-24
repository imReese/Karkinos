import type { RefObject } from 'react';

import { KarkinosMark } from '../../shared/ui/brand/karkinos-mark';
import type { Locale, ThemePreference } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import { ChevronDownIcon, SearchIcon } from './app-shell-icons';
import { AppShellPreferences } from './app-shell-preferences';
import {
  StatusChip,
  StatusPopover,
  TOOLBAR_STATUS_COLORS,
} from './app-shell-status';
import type {
  ToolbarPopoverKey,
  ToolbarStatusModel,
} from './app-shell-status-model';

type ToolbarStatusState = ToolbarStatusModel & {
  openStatusPanel: ToolbarPopoverKey;
  statusRailRef: RefObject<HTMLDivElement | null>;
  statusRailVisible: boolean;
  toggleStatusPanel: (panel: Exclude<ToolbarPopoverKey, null>) => void;
};

type AppShellToolbarProps = {
  commandOpen: boolean;
  copy: AppCopy;
  locale: Locale;
  mobileNavOpen: boolean;
  onCommandOpen: () => void;
  onLocaleChange: (value: Locale) => void;
  onMobileNavToggle: () => void;
  onThemeChange: (value: ThemePreference) => void;
  status: ToolbarStatusState;
  theme: ThemePreference;
};

export function AppShellToolbar({
  commandOpen,
  copy,
  locale,
  mobileNavOpen,
  onCommandOpen,
  onLocaleChange,
  onMobileNavToggle,
  onThemeChange,
  status,
  theme,
}: AppShellToolbarProps) {
  return (
    <header className="app-toolbar-shell relative z-[80] shrink-0 overflow-visible border-b border-[var(--app-divider)] bg-[var(--app-surface-raised)]">
      <div className="flex h-12 items-center gap-3 px-3 sm:px-4">
        <button
          type="button"
          className="app-button-secondary inline-flex h-8 w-8 items-center justify-center rounded-[var(--app-radius-control)] p-0 text-sm xl:hidden"
          data-testid="mobile-navigation-toggle"
          aria-label={
            mobileNavOpen
              ? copy.shell.closeNavigation
              : copy.shell.openNavigation
          }
          aria-controls="app-shell-navigation"
          aria-expanded={mobileNavOpen}
          onClick={onMobileNavToggle}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
            className="h-4 w-4"
            data-testid="mobile-navigation-icon"
          >
            <path d="M4 7h16" />
            <path d="M4 12h16" />
            <path d="M4 17h16" />
          </svg>
        </button>

        <div className="app-toolbar-brand min-w-0 shrink-0 items-center gap-2 xl:hidden">
          <span
            className="app-brand-glyph app-brand-glyph-compact"
            aria-hidden="true"
          >
            <KarkinosMark />
          </span>
          <span className="app-product-mark truncate">Karkinos</span>
        </div>

        <div className="app-toolbar-state hidden shrink-0 items-center min-[1360px]:flex">
          <div
            className="app-toolbar-mode"
            aria-label={`${copy.shell.accountMode}: ${status.executionMode}`}
          >
            <span>{copy.shell.accountMode}</span>
            <strong>{status.executionMode}</strong>
          </div>
        </div>

        <ToolbarStatusRail copy={copy} status={status} />

        <button
          type="button"
          className="app-command-trigger ml-auto"
          data-testid="workspace-command-trigger"
          aria-label={copy.shell.commandTrigger}
          aria-haspopup="dialog"
          aria-expanded={commandOpen}
          onClick={onCommandOpen}
        >
          <SearchIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{copy.shell.commandPlaceholder}</span>
          <kbd aria-hidden="true">⌘K</kbd>
        </button>

        <AppShellPreferences
          copy={copy}
          locale={locale}
          onLocaleChange={onLocaleChange}
          onThemeChange={onThemeChange}
          theme={theme}
        />
      </div>
    </header>
  );
}

function ToolbarStatusRail({
  copy,
  status,
}: {
  copy: AppCopy;
  status: ToolbarStatusState;
}) {
  return (
    <div ref={status.statusRailRef} className="relative min-w-0 shrink-0">
      {!status.statusRailVisible ? (
        <div className="relative hidden shrink-0 xl:block min-[1360px]:hidden">
          <button
            type="button"
            className="app-button-secondary app-type-compact inline-flex h-8 items-center gap-1.5 rounded-[var(--app-radius-control)] px-2.5 font-semibold"
            data-testid="compact-status-trigger"
            aria-label={`${copy.shell.accountStatus}: ${copy.shell.navStatus}, ${copy.shell.marketStatus}`}
            aria-haspopup="dialog"
            aria-expanded={status.openStatusPanel === 'valuation'}
            onClick={() => status.toggleStatusPanel('valuation')}
          >
            <span>{copy.shell.navStatus}</span>
            <span
              className="h-2 w-2 rounded-full"
              style={{
                backgroundColor:
                  TOOLBAR_STATUS_COLORS[status.valuationStatus.tone],
              }}
              aria-hidden="true"
            />
            <span
              className="text-[var(--app-text-tertiary)]"
              aria-hidden="true"
            >
              /
            </span>
            <span>{copy.shell.marketStatus}</span>
            <span
              className="h-2 w-2 rounded-full"
              style={{
                backgroundColor:
                  TOOLBAR_STATUS_COLORS[status.marketStatus.tone],
              }}
              aria-hidden="true"
            />
            <ChevronDownIcon
              className={`h-3 w-3 shrink-0 text-[var(--app-text-tertiary)] transition-transform ${status.openStatusPanel === 'valuation' ? 'rotate-180' : ''}`}
              aria-hidden="true"
            />
          </button>
          {status.openStatusPanel === 'valuation' ? (
            <div className="app-status-popover-root absolute left-0 top-[calc(100%+8px)] z-[90]">
              <StatusPopover
                title={copy.shell.accountStatus}
                rows={[
                  {
                    label: copy.shell.navStatus,
                    value: status.valuationStatus.value,
                  },
                  {
                    label: copy.shell.valuationUpdated,
                    value: status.valuationMeta ?? copy.shell.statusUnknown,
                  },
                  {
                    label: copy.shell.marketStatus,
                    value: status.marketStatus.value,
                  },
                  {
                    label: copy.shell.lastSync,
                    value: status.marketTimestamp ?? copy.shell.statusUnknown,
                  },
                ]}
              />
            </div>
          ) : null}
        </div>
      ) : null}
      <div
        className="app-toolbar-status-rail relative hidden min-w-0 shrink items-center gap-1 overflow-visible min-[1360px]:flex"
        aria-label={copy.shell.accountStatus}
      >
        <StatusChip
          testId="status-pill-valuation"
          label={copy.shell.navStatus}
          value={status.valuationStatus.value}
          meta={status.valuationTimestamp ?? undefined}
          tone={status.valuationStatus.tone}
          indicator={status.valuationStatus.indicator}
          hoverHint={copy.shell.viewValuationDetails}
          expanded={status.openStatusPanel === 'valuation'}
          title={`${copy.shell.navStatus}: ${status.valuationStatus.value}${
            status.valuationMeta ? ` · ${status.valuationMeta}` : ''
          }`}
          popup={
            <StatusPopover
              title={copy.shell.navStatus}
              rows={[
                {
                  label: copy.shell.valuationUpdated,
                  value: status.valuationMeta ?? copy.shell.statusUnknown,
                },
                {
                  label: copy.shell.quoteStatus,
                  value: status.quoteStatus,
                },
              ]}
            />
          }
          onClick={() => status.toggleStatusPanel('valuation')}
        />
        <StatusChip
          testId="status-pill-market"
          label={copy.shell.marketStatus}
          value={status.marketStatus.value}
          meta={status.marketTimestamp ?? undefined}
          tone={status.marketStatus.tone}
          indicator={status.marketStatus.indicator}
          hoverHint={copy.shell.viewStatusDetails}
          expanded={status.openStatusPanel === 'market'}
          title={`${copy.shell.marketStatus}: ${status.marketStatus.value}${
            status.marketTimestamp ? ` · ${status.marketTimestamp}` : ''
          }`}
          popup={
            <StatusPopover
              title={copy.shell.marketStatus}
              rows={[
                {
                  label: copy.shell.lastSync,
                  value: status.marketTimestamp ?? copy.shell.statusUnknown,
                },
                {
                  label: copy.shell.marketSession,
                  value: status.marketOpenText,
                },
                {
                  label: copy.shell.refreshPolicy,
                  value: status.refreshPolicy,
                },
                {
                  label: copy.shell.quoteStatus,
                  value: status.quoteStatus,
                },
              ]}
            />
          }
          onClick={() => status.toggleStatusPanel('market')}
        />
      </div>
    </div>
  );
}
