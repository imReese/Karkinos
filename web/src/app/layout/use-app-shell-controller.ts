import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { useRouterState } from '@tanstack/react-router';

import { usePreferences } from '../../shared/preferences/context';
import { useCopy } from '../copy';
import { useToolbarStatusController } from './use-toolbar-status-controller';

export function useAppShellController() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const copy = useCopy();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [desktopNavExpanded, setDesktopNavExpanded] = useState(true);
  const [commandOpen, setCommandOpen] = useState(false);
  const mobileNavRef = useRef<HTMLElement | null>(null);
  const mobileNavCloseRef = useRef<HTMLButtonElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const previousPathnameRef = useRef(pathname);
  const routeScrollPositionsRef = useRef(
    new Map<string, { left: number; top: number }>(),
  );
  const status = useToolbarStatusController(copy, locale);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const previousPathname = previousPathnameRef.current;
    if (!content || previousPathname === pathname) {
      return;
    }

    routeScrollPositionsRef.current.set(previousPathname, {
      left: content.scrollLeft,
      top: content.scrollTop,
    });
    const nextPosition = routeScrollPositionsRef.current.get(pathname);
    content.scrollLeft = nextPosition?.left ?? 0;
    content.scrollTop = nextPosition?.top ?? 0;
    previousPathnameRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    if (!mobileNavOpen) {
      return;
    }

    const returnFocus = document.activeElement as HTMLElement | null;
    mobileNavCloseRef.current?.focus();

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileNavOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('keydown', handleEscape);
      const activeElement = document.activeElement as HTMLElement | null;
      if (
        !activeElement ||
        activeElement === document.body ||
        mobileNavRef.current?.contains(activeElement)
      ) {
        returnFocus?.focus();
      }
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    const handleCommandKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen(true);
        return;
      }
      if (event.key === 'Escape') {
        setCommandOpen(false);
      }
    };

    window.addEventListener('keydown', handleCommandKey);
    return () => window.removeEventListener('keydown', handleCommandKey);
  }, []);

  return {
    closeCommand: () => setCommandOpen(false),
    closeMobileNav: () => setMobileNavOpen(false),
    commandOpen,
    contentRef,
    copy,
    desktopNavExpanded,
    locale,
    mobileNavCloseRef,
    mobileNavOpen,
    mobileNavRef,
    openCommand: () => setCommandOpen(true),
    pathname,
    setLocale,
    setTheme,
    status,
    theme,
    toggleDesktopNav: () => setDesktopNavExpanded((expanded) => !expanded),
    toggleMobileNav: () => setMobileNavOpen((open) => !open),
  };
}
