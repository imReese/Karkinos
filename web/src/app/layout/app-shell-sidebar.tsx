import type { RefObject } from 'react';

import { Link } from '@tanstack/react-router';

import { KarkinosMark } from '../../shared/ui/brand/karkinos-mark';
import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import {
  isNavigationItemActive,
  NAVIGATION_GROUPS,
} from './app-shell-navigation-config';

type AppShellSidebarProps = {
  copy: AppCopy;
  desktopNavExpanded: boolean;
  locale: Locale;
  mobileNavCloseRef: RefObject<HTMLButtonElement | null>;
  mobileNavOpen: boolean;
  mobileNavRef: RefObject<HTMLElement | null>;
  onDesktopToggle: () => void;
  onMobileNavClose: () => void;
  pathname: string;
};

export function AppShellSidebar({
  copy,
  desktopNavExpanded,
  locale,
  mobileNavCloseRef,
  mobileNavOpen,
  mobileNavRef,
  onDesktopToggle,
  onMobileNavClose,
  pathname,
}: AppShellSidebarProps) {
  return (
    <aside
      ref={mobileNavRef}
      id="app-shell-navigation"
      data-mobile-open={mobileNavOpen}
      data-desktop-expanded={desktopNavExpanded}
      className={`app-shell-sidebar fixed inset-y-0 left-0 z-[100] flex w-[min(84vw,280px)] flex-col border-r border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-3 xl:relative xl:h-full ${desktopNavExpanded ? 'xl:w-52' : 'xl:w-14'} xl:translate-x-0 ${
        mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div
        className={`app-brand-lockup mb-4 flex min-h-10 items-center gap-2.5 px-1.5 ${desktopNavExpanded ? 'justify-between' : 'xl:justify-center'}`}
      >
        <Link
          to="/"
          aria-label={copy.shell.publicHome}
          className="flex min-w-0 flex-1 items-center gap-2.5"
        >
          <span className="app-brand-glyph" aria-hidden="true">
            <KarkinosMark />
          </span>
          <div className="app-sidebar-brand-copy min-w-0">
            <div className="app-product-mark truncate whitespace-nowrap">
              Karkinos
            </div>
            <div className="app-type-micro mt-1 truncate font-medium text-[var(--app-text-tertiary)]">
              {copy.shell.workspaceLabel}
            </div>
          </div>
        </Link>
        <button
          ref={mobileNavCloseRef}
          type="button"
          className="app-button-secondary h-8 w-8 rounded-[var(--app-radius-control)] p-0 text-sm xl:hidden"
          aria-label={copy.shell.closeNavigation}
          onClick={onMobileNavClose}
        >
          ✕
        </button>
      </div>

      <nav
        className="min-h-0 flex-1 space-y-3 overflow-y-auto"
        aria-label={copy.shell.navigation}
      >
        {NAVIGATION_GROUPS.map((group) => (
          <div key={group.key} className="grid gap-1">
            <div className="app-nav-group-label app-type-micro px-2 pt-1 pb-1 font-semibold uppercase text-[var(--app-text-tertiary)]">
              {group.label[locale]}
            </div>
            {group.items.map((item) => {
              const active = isNavigationItemActive(pathname, item.to);
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={onMobileNavClose}
                  data-testid={`sidebar-nav-${item.key}`}
                  title={
                    desktopNavExpanded ? undefined : copy.shell.nav[item.key]
                  }
                  className={`app-nav-item min-h-9 rounded-[var(--app-radius-control)] px-2 py-2 text-sm font-medium ${!desktopNavExpanded ? 'xl:justify-center xl:px-0' : ''} ${
                    active ? 'app-nav-item-active' : ''
                  }`}
                >
                  <span className="app-nav-active-rail" aria-hidden="true" />
                  <Icon
                    data-testid={`sidebar-nav-${item.key}-icon`}
                    className="app-nav-icon h-4 w-4 shrink-0"
                    aria-hidden="true"
                  />
                  <span className="app-nav-copy truncate">
                    {copy.shell.nav[item.key]}
                  </span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="mt-3 hidden border-t border-[var(--app-divider)] pt-2 xl:grid">
        <button
          type="button"
          className={`app-nav-item min-h-9 rounded-[var(--app-radius-control)] px-2 py-2 text-sm font-medium text-[var(--app-text-secondary)] ${!desktopNavExpanded ? 'xl:justify-center xl:px-0' : ''}`}
          onClick={onDesktopToggle}
          aria-label={
            desktopNavExpanded
              ? copy.shell.closeNavigation
              : copy.shell.openNavigation
          }
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="app-nav-icon app-nav-collapse-icon h-4 w-4 shrink-0"
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
          <span className="app-nav-copy truncate">
            {copy.shell.closeNavigation}
          </span>
        </button>
      </div>
    </aside>
  );
}
