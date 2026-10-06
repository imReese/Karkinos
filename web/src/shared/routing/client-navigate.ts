import type { MouseEvent } from 'react';

/**
 * Intercepts standard left-clicks on anchor tags to perform client-side SPA navigation
 * without full document reload, while preserving native anchor semantics (Cmd/Ctrl+click,
 * right click to open in new tab, accessibility tree, and automated test contracts).
 */
export function handleClientNavigation(
  event: MouseEvent<HTMLAnchorElement>,
  to: string,
): void {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }

  if (typeof window !== 'undefined') {
    event.preventDefault();
    const globalWithNav = window as unknown as {
      __karkinosNavigate?: (path: string) => void;
    };
    if (typeof globalWithNav.__karkinosNavigate === 'function') {
      globalWithNav.__karkinosNavigate(to);
    } else {
      window.dispatchEvent(
        new CustomEvent('karkinos:navigate', { detail: { to } }),
      );
    }
  }
}
