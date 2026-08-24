import { useEffect, useState } from 'react';

export const APP_MOTION = {
  chartDurationMs: 320,
  easing: 'ease-out',
  exitDurationMs: 180,
  reducedMotionQuery: '(prefers-reduced-motion: reduce)',
} as const;

function readReducedMotionPreference() {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia(APP_MOTION.reducedMotionQuery).matches
  );
}

export function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(
    readReducedMotionPreference,
  );

  useEffect(() => {
    if (
      typeof window === 'undefined' ||
      typeof window.matchMedia !== 'function'
    ) {
      return undefined;
    }

    const mediaQuery = window.matchMedia(APP_MOTION.reducedMotionQuery);
    const handleChange = (event: MediaQueryListEvent) => {
      setReducedMotion(event.matches);
    };

    setReducedMotion(mediaQuery.matches);
    mediaQuery.addEventListener?.('change', handleChange);
    return () => mediaQuery.removeEventListener?.('change', handleChange);
  }, []);

  return reducedMotion;
}

export function useMotionPresence(
  open: boolean,
  exitDurationMs = APP_MOTION.exitDurationMs,
) {
  const reducedMotion = useReducedMotion();
  const [retained, setRetained] = useState(open);

  useEffect(() => {
    if (open) {
      setRetained(true);
      return undefined;
    }
    if (!retained) {
      return undefined;
    }

    const timeout = window.setTimeout(
      () => setRetained(false),
      reducedMotion ? 0 : exitDurationMs,
    );
    return () => window.clearTimeout(timeout);
  }, [exitDurationMs, open, reducedMotion, retained]);

  return {
    mounted: open || retained,
    state: open ? ('open' as const) : ('closing' as const),
  };
}
