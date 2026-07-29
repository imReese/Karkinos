import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { APP_MOTION, useReducedMotion } from './motion';

afterEach(() => {
  vi.restoreAllMocks();
});

test('tracks the system reduced-motion preference for data visualizations', () => {
  let changeListener: ((event: MediaQueryListEvent) => void) | undefined;
  const mediaQuery = {
    matches: false,
    media: APP_MOTION.reducedMotionQuery,
    onchange: null,
    addEventListener: vi.fn(
      (_event: string, listener: (event: MediaQueryListEvent) => void) => {
        changeListener = listener;
      },
    ),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => mediaQuery),
  });

  const { result } = renderHook(() => useReducedMotion());
  expect(result.current).toBe(false);
  expect(window.matchMedia).toHaveBeenCalledWith(APP_MOTION.reducedMotionQuery);

  act(() => {
    changeListener?.({ matches: true } as MediaQueryListEvent);
  });
  expect(result.current).toBe(true);
});
