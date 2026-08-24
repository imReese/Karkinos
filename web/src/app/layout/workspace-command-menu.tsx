import { useEffect, useRef, useState } from 'react';

import { Link } from '@tanstack/react-router';

import { useMotionPresence } from '../../shared/motion';
import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import { SearchIcon } from './app-shell-icons';
import {
  isNavigationItemActive,
  NAVIGATION_GROUPS,
} from './app-shell-navigation-config';

type WorkspaceCommandMenuProps = {
  copy: AppCopy;
  open: boolean;
  locale: Locale;
  onClose: () => void;
  pathname: string;
};

export function WorkspaceCommandMenu({
  copy,
  open,
  locale,
  onClose,
  pathname,
}: WorkspaceCommandMenuProps) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const presence = useMotionPresence(open);

  useEffect(() => {
    if (!open) {
      return;
    }
    const returnFocus = document.activeElement as HTMLElement | null;
    setQuery('');
    inputRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') {
        return;
      }
      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => !element.hasAttribute('hidden'));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      returnFocus?.focus();
    };
  }, [open]);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredGroups = NAVIGATION_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) =>
      copy.shell.nav[item.key].toLocaleLowerCase().includes(normalizedQuery),
    ),
  })).filter((group) => group.items.length > 0);

  if (!presence.mounted) {
    return null;
  }

  return (
    <div
      className="app-command-backdrop"
      data-motion-state={presence.state}
      aria-hidden={presence.state === 'closing' ? true : undefined}
      inert={presence.state === 'closing'}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        ref={panelRef}
        className="app-command-panel"
        role="dialog"
        aria-modal={open ? 'true' : undefined}
        aria-label={copy.shell.commandTitle}
      >
        <div className="app-command-input-row">
          <SearchIcon className="h-4 w-4" aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={copy.shell.commandPlaceholder}
            placeholder={copy.shell.commandPlaceholder}
            autoComplete="off"
          />
          <button
            type="button"
            aria-label={copy.shell.closeCommand}
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <nav
          className="app-command-results"
          aria-label={copy.shell.commandResults}
        >
          {filteredGroups.length > 0 ? (
            filteredGroups.map((group) => (
              <div className="app-command-group" key={group.key}>
                <div className="app-command-group-label">
                  {group.label[locale]}
                </div>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isNavigationItemActive(pathname, item.to);
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      className={`app-command-result ${
                        active ? 'app-command-result-active' : ''
                      }`}
                      onClick={onClose}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      <span>{copy.shell.nav[item.key]}</span>
                      <span aria-hidden="true">→</span>
                    </Link>
                  );
                })}
              </div>
            ))
          ) : (
            <div className="app-command-empty">{copy.shell.commandEmpty}</div>
          )}
        </nav>
      </section>
    </div>
  );
}
