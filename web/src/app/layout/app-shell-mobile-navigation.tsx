import { Link } from '@tanstack/react-router';

import type { AppCopy } from '../copy';
import { MenuIcon } from './app-shell-icons';
import {
  isNavigationItemActive,
  MOBILE_PRIMARY_ITEMS,
} from './app-shell-navigation-config';

type AppShellMobileNavigationProps = {
  copy: AppCopy;
  mobileNavOpen: boolean;
  onMobileNavClose: () => void;
  onMobileNavToggle: () => void;
  pathname: string;
};

export function AppShellMobileNavigation({
  copy,
  mobileNavOpen,
  onMobileNavClose,
  onMobileNavToggle,
  pathname,
}: AppShellMobileNavigationProps) {
  return (
    <nav
      className="app-mobile-primary-nav relative z-[80] grid shrink-0 grid-cols-4 border-t border-[var(--app-divider)] bg-[var(--app-surface-raised)] xl:hidden"
      aria-label={copy.shell.primaryNavigation}
    >
      {MOBILE_PRIMARY_ITEMS.map((item) => {
        const active = isNavigationItemActive(pathname, item.to);
        const Icon = item.icon;
        return (
          <Link
            key={item.to}
            to={item.to}
            className={`app-mobile-primary-item ${
              active ? 'app-mobile-primary-item-active' : ''
            }`}
            onClick={onMobileNavClose}
          >
            <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
            <span>{copy.shell.nav[item.key]}</span>
          </Link>
        );
      })}
      <button
        type="button"
        className={`app-mobile-primary-item ${mobileNavOpen ? 'app-mobile-primary-item-active' : ''}`}
        aria-label={copy.shell.moreNavigation}
        aria-controls="app-shell-navigation"
        aria-expanded={mobileNavOpen}
        onClick={onMobileNavToggle}
      >
        <MenuIcon className="h-[18px] w-[18px]" aria-hidden="true" />
        <span>{copy.shell.moreNavigation}</span>
      </button>
    </nav>
  );
}
