import { useEffect, useRef, useState } from 'react';

import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';
import {
  useAccountOverviewQuery,
  useMarketDataHealthQuery,
} from './app-shell-feature-boundary';
import {
  deriveToolbarStatusModel,
  type ToolbarPopoverKey,
} from './app-shell-status-model';

const STATUS_RAIL_MEDIA_QUERY = '(min-width: 1360px)';

export function useToolbarStatusController(copy: AppCopy, locale: Locale) {
  const [statusRailVisible, setStatusRailVisible] = useState(() =>
    typeof window === 'undefined' || typeof window.matchMedia !== 'function'
      ? false
      : window.matchMedia(STATUS_RAIL_MEDIA_QUERY).matches,
  );
  const [openStatusPanel, setOpenStatusPanel] =
    useState<ToolbarPopoverKey>(null);
  const statusQueriesEnabled = statusRailVisible || openStatusPanel !== null;
  const accountOverview = useAccountOverviewQuery(statusQueriesEnabled);
  const marketHealth = useMarketDataHealthQuery(statusQueriesEnabled);
  const statusRailRef = useRef<HTMLDivElement | null>(null);

  const toggleStatusPanel = (panel: Exclude<ToolbarPopoverKey, null>) => {
    setOpenStatusPanel((current) => (current === panel ? null : panel));
  };

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      return;
    }
    const mediaQuery = window.matchMedia(STATUS_RAIL_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      setStatusRailVisible(event.matches);
    };
    setStatusRailVisible(mediaQuery.matches);
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    if (!openStatusPanel) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!statusRailRef.current?.contains(event.target as Node)) {
        setOpenStatusPanel(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenStatusPanel(null);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [openStatusPanel]);

  return {
    ...deriveToolbarStatusModel({
      accountOverview,
      copy,
      locale,
      marketHealth,
    }),
    openStatusPanel,
    statusRailRef,
    statusRailVisible,
    toggleStatusPanel,
  };
}
