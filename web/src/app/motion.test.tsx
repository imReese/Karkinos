import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { APP_MOTION, useMotionPresence, useReducedMotion } from './motion';

afterEach(() => {
  vi.useRealTimers();
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

test('retains closing surfaces for the semantic exit duration', () => {
  vi.useFakeTimers();
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      media: APP_MOTION.reducedMotionQuery,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  const { result, rerender } = renderHook(
    ({ open }) => useMotionPresence(open),
    { initialProps: { open: false } },
  );
  expect(result.current).toEqual({ mounted: false, state: 'closing' });

  rerender({ open: true });
  expect(result.current).toEqual({ mounted: true, state: 'open' });

  rerender({ open: false });
  expect(result.current).toEqual({ mounted: true, state: 'closing' });
  act(() => vi.advanceTimersByTime(APP_MOTION.exitDurationMs - 1));
  expect(result.current.mounted).toBe(true);
  act(() => vi.advanceTimersByTime(1));
  expect(result.current.mounted).toBe(false);
});

test('does not retain closing surfaces when reduced motion is requested', () => {
  vi.useFakeTimers();
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: true,
      media: APP_MOTION.reducedMotionQuery,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  const { result, rerender } = renderHook(
    ({ open }) => useMotionPresence(open),
    { initialProps: { open: true } },
  );
  rerender({ open: false });
  expect(result.current).toEqual({ mounted: true, state: 'closing' });
  act(() => vi.runOnlyPendingTimers());
  expect(result.current.mounted).toBe(false);
});
