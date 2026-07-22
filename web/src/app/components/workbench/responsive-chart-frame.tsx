import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';

export type ResponsiveChartSize = {
  width: number;
  height: number;
};

function readChartFrameSize(element: HTMLElement): ResponsiveChartSize | null {
  const rect = element.getBoundingClientRect();
  const width = Math.floor(rect.width);
  const height = Math.floor(rect.height);

  if (width <= 0 || height <= 0) {
    return null;
  }

  return { width, height };
}

export function ResponsiveChartFrame({
  ariaLabel,
  children,
  className,
  testId,
}: {
  ariaLabel: string;
  children: (size: ResponsiveChartSize) => ReactNode;
  className?: string;
  testId?: string;
}) {
  const frameRef = useRef<HTMLElement | null>(null);
  const [size, setSize] = useState<ResponsiveChartSize | null>(null);

  useLayoutEffect(() => {
    const element = frameRef.current;
    if (!element) {
      return undefined;
    }

    let animationFrame: number | null = null;

    const commitSize = () => {
      const nextSize = readChartFrameSize(element);
      setSize((currentSize) => {
        if (!nextSize) {
          return currentSize === null ? currentSize : null;
        }
        if (
          currentSize?.width === nextSize.width &&
          currentSize.height === nextSize.height
        ) {
          return currentSize;
        }
        return nextSize;
      });
    };

    const scheduleSizeCommit = () => {
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = null;
        commitSize();
      });
    };

    commitSize();

    const resizeObserver =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(scheduleSizeCommit);
    resizeObserver?.observe(element);
    window.addEventListener('resize', scheduleSizeCommit);

    return () => {
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
      resizeObserver?.disconnect();
      window.removeEventListener('resize', scheduleSizeCommit);
    };
  }, []);

  return (
    <figure
      ref={frameRef}
      aria-label={ariaLabel}
      className={cn('min-w-0', className)}
      data-testid={testId}
      data-workbench-primitive="responsive-chart-frame"
    >
      {size ? children(size) : null}
    </figure>
  );
}
