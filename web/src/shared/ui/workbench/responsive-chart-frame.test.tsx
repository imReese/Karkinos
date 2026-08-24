import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ResponsiveChartFrame } from './responsive-chart-frame';

let resizeCallback: ResizeObserverCallback | null = null;
let frameWidth = 0;
let frameHeight = 0;
const originalResizeObserver = window.ResizeObserver;

function rect(width: number, height: number): DOMRect {
  return {
    bottom: height,
    height,
    left: 0,
    right: width,
    top: 0,
    width,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
}

function reportSize(width: number, height: number) {
  frameWidth = width;
  frameHeight = height;
  const target = screen.getByTestId('chart-frame');
  act(() => {
    resizeCallback?.(
      [
        {
          target,
          contentRect: rect(width, height),
        } as unknown as ResizeObserverEntry,
      ],
      {} as ResizeObserver,
    );
  });
}

beforeEach(() => {
  frameWidth = 0;
  frameHeight = 0;
  resizeCallback = null;
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    () => rect(frameWidth, frameHeight),
  );
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0);
    return 1;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
  window.ResizeObserver = class ResizeObserver {
    constructor(callback: ResizeObserverCallback) {
      resizeCallback = callback;
    }

    observe() {}

    unobserve() {}

    disconnect() {}
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, 'ResizeObserver', {
    configurable: true,
    value: originalResizeObserver,
  });
});

test('mounts chart content only while the frame has a positive size', () => {
  render(
    <ResponsiveChartFrame
      ariaLabel="Persisted equity series"
      className="h-[320px]"
      testId="chart-frame"
    >
      {({ height, width }) => (
        <span data-testid="chart-content">
          {width}×{height}
        </span>
      )}
    </ResponsiveChartFrame>,
  );

  const frame = screen.getByTestId('chart-frame');
  expect(frame.getAttribute('aria-label')).toBe('Persisted equity series');
  expect(frame.getAttribute('data-workbench-primitive')).toBe(
    'responsive-chart-frame',
  );
  expect(screen.queryByTestId('chart-content')).toBeNull();

  reportSize(640, 320);
  expect(screen.getByTestId('chart-content').textContent).toBe('640×320');

  reportSize(0, 0);
  expect(screen.queryByTestId('chart-content')).toBeNull();

  reportSize(390, 150);
  expect(screen.getByTestId('chart-content').textContent).toBe('390×150');
});
