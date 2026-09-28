import { useEffect, useRef, useState } from 'react';

import { Link } from '@tanstack/react-router';

import { useMotionPresence } from '../../shared/motion';
import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import { MarketNavIcon, SearchIcon } from './app-shell-icons';
import {
  isNavigationItemActive,
  MARKET_ROUTE,
  NAVIGATION_GROUPS,
} from './app-shell-navigation-config';

type WorkspaceCommandMenuProps = {
  copy: AppCopy;
  open: boolean;
  locale: Locale;
  onClose: () => void;
  pathname: string;
};

type CommandResultItem = {
  key: string;
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  search?: Record<string, string>;
  isDirectJump?: boolean;
};

type CommandResultGroup = {
  key: string;
  label: string;
  items: CommandResultItem[];
};

export function WorkspaceCommandMenu({
  copy,
  open,
  locale,
  onClose,
  pathname,
}: WorkspaceCommandMenuProps) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const presence = useMotionPresence(open);

  useEffect(() => {
    if (!open) {
      return;
    }
    const returnFocus = document.activeElement as HTMLElement | null;
    setQuery('');
    setActiveIndex(0);
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
  const trimmedQuery = query.trim();

  const filteredGroups: CommandResultGroup[] = NAVIGATION_GROUPS.map(
    (group) => ({
      key: group.key,
      label: group.label[locale],
      items: group.items
        .filter((item) =>
          copy.shell.nav[item.key]
            .toLocaleLowerCase()
            .includes(normalizedQuery),
        )
        .map((item) => ({
          key: item.to,
          to: item.to,
          label: copy.shell.nav[item.key],
          icon: item.icon,
        })),
    }),
  ).filter((group) => group.items.length > 0);

  const isNumericTicker = /^[0-9]{4,6}(\.(SH|SZ|BJ))?$/i.test(trimmedQuery);
  const isAlphaTicker = /^[A-Za-z]{2,6}$/.test(trimmedQuery);
  const shouldShowDirectJump =
    isNumericTicker || (filteredGroups.length === 0 && isAlphaTicker);

  const directQuoteGroup: CommandResultGroup | null = shouldShowDirectJump
    ? {
        key: 'direct-quote',
        label: locale === 'zh' ? '行情直达' : 'Direct Quote',
        items: [
          {
            key: `direct-${trimmedQuery.toUpperCase()}`,
            to: MARKET_ROUTE,
            label:
              locale === 'zh'
                ? `在行情中查看 ${trimmedQuery.toUpperCase()}`
                : `View ${trimmedQuery.toUpperCase()} in Market`,
            icon: MarketNavIcon,
            search: { symbol: trimmedQuery.toUpperCase() },
            isDirectJump: true,
          },
        ],
      }
    : null;

  const allGroups: CommandResultGroup[] = [
    ...filteredGroups,
    ...(directQuoteGroup ? [directQuoteGroup] : []),
  ];

  const flatItems = allGroups.flatMap((group) => group.items);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open || activeIndex < 0) {
      return;
    }
    const itemEl = panelRef.current?.querySelector<HTMLElement>(
      `[data-command-item-index="${activeIndex}"]`,
    );
    if (typeof itemEl?.scrollIntoView === 'function') {
      itemEl.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex, open]);

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (flatItems.length === 0) return;
      setActiveIndex((prev) => (prev + 1) % flatItems.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (flatItems.length === 0) return;
      setActiveIndex((prev) => (prev <= 0 ? flatItems.length - 1 : prev - 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (flatItems.length === 0) return;
      const targetIndex =
        activeIndex >= 0 && activeIndex < flatItems.length ? activeIndex : 0;
      const linkEl = panelRef.current?.querySelector<HTMLAnchorElement>(
        `[data-command-item-index="${targetIndex}"]`,
      );
      linkEl?.click();
    }
  };

  if (!presence.mounted) {
    return null;
  }

  let runningIndex = 0;

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
            onKeyDown={handleInputKeyDown}
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
          {allGroups.length > 0 ? (
            allGroups.map((group) => (
              <div className="app-command-group" key={group.key}>
                <div className="app-command-group-label">{group.label}</div>
                {group.items.map((item) => {
                  const itemIndex = runningIndex++;
                  const Icon = item.icon;
                  const isSelected = itemIndex === activeIndex;
                  const isCurrent =
                    !item.isDirectJump &&
                    isNavigationItemActive(pathname, item.to);
                  return (
                    <Link
                      key={item.key}
                      to={item.to}
                      search={item.search as any}
                      data-command-item-index={itemIndex}
                      aria-selected={isSelected ? 'true' : undefined}
                      className={`app-command-result ${
                        isSelected || isCurrent
                          ? 'app-command-result-active'
                          : ''
                      }`}
                      onClick={onClose}
                      onMouseEnter={() => setActiveIndex(itemIndex)}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      <span>{item.label}</span>
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
