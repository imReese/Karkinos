import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { PriceStructureChart } from './price-structure-chart';

test('renders OHLC price range as a K-line chart', () => {
  const { container } = render(
    <PriceStructureChart
      titleLabel="Price range / K-line"
      priceLabel="Price"
      emptyLabel="No chart"
      rangeLabels={{
        oneMonth: '1M',
        threeMonths: '3M',
        sixMonths: '6M',
        oneYear: '1Y',
        all: 'All',
      }}
      bars={[
        {
          timestamp: '2025-04-19',
          open: 1510,
          high: 1620,
          low: 1500,
          close: 1600,
          volume: 120000,
        },
        {
          timestamp: '2026-04-20',
          open: 1600,
          high: 1660,
          low: 1580,
          close: 1640,
          volume: 130000,
        },
      ]}
    />,
  );

  expect(screen.getByText('Price range / K-line')).toBeTruthy();
  expect(screen.queryByText('¥1,640.00')).toBeNull();
  expect(screen.queryByText('¥40.00')).toBeNull();
  expect(screen.queryByText('2.5%')).toBeNull();
  expect(
    screen.getByRole('button', { name: 'Show 1M K-line range' }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole('button', { name: 'Show All K-line range' })
      .getAttribute('aria-pressed'),
  ).toBe('true');
  expect(screen.queryByText('Price axis')).toBeNull();
  expect(screen.queryByText('Date axis')).toBeNull();
  expect(
    screen.getByRole('img', {
      name: 'Price range / K-line · Price axis · Date axis',
    }),
  ).toBeTruthy();
  expect(screen.getByText('Volume')).toBeTruthy();
  expect(screen.getByText('2025-04-19').getAttribute('text-anchor')).toBe(
    'start',
  );
  expect(screen.getByText('2026-04-20').getAttribute('text-anchor')).toBe(
    'end',
  );
  expect(
    container.querySelectorAll('[data-testid="kline-candle"]').length,
  ).toBe(2);
  expect(
    container.querySelectorAll('[data-testid="kline-volume-bar"]').length,
  ).toBe(2);
  expect(
    container.querySelector('[data-testid="close-price-trend"]'),
  ).toBeNull();
  const chartScroll = screen.getByTestId('price-structure-chart-scroll');
  const chartCanvas = screen.getByTestId('price-structure-chart-canvas');
  expect(chartScroll.className).toContain('overflow-x-auto');
  expect(chartScroll.className).toContain('pb-2');
  expect(chartScroll.className).toContain('app-horizontal-scroll-cue');
  expect(chartCanvas.className).toContain('min-w-[720px]');
  Object.defineProperties(chartScroll, {
    clientWidth: { configurable: true, value: 320 },
    scrollWidth: { configurable: true, value: 720 },
  });
  fireEvent(window, new Event('resize'));
  expect(chartScroll.scrollLeft).toBe(400);
  expect(container.querySelector('.rounded-2xl')).toBeNull();
  expect(container.querySelector('.rounded-3xl')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Show 1M K-line range' }));

  expect(
    screen
      .getByRole('button', { name: 'Show 1M K-line range' })
      .getAttribute('aria-pressed'),
  ).toBe('true');
  expect(
    container.querySelectorAll('[data-testid="kline-candle"]').length,
  ).toBe(1);
  expect(screen.queryByText('2025-04-19')).toBeNull();
});

test('renders an empty state when no bars are available', () => {
  const { container } = render(
    <PriceStructureChart
      titleLabel="Price range / K-line"
      priceLabel="Price"
      emptyLabel="No chart"
      bars={[]}
    />,
  );

  expect(screen.getByText('No chart')).toBeTruthy();
  expect(screen.getByText('Price range / K-line')).toBeTruthy();
  expect(container.querySelector('[data-evidence-kind="empty"]')).toBeTruthy();
  expect(container.querySelector('.rounded-2xl')).toBeNull();
});

test('excludes out-of-range trade markers from the selected range axis', () => {
  render(
    <PriceStructureChart
      titleLabel="Price range / K-line"
      priceLabel="Price"
      emptyLabel="No chart"
      rangeLabels={{
        oneMonth: '1M',
        threeMonths: '3M',
        sixMonths: '6M',
        oneYear: '1Y',
        all: 'All',
      }}
      bars={[
        {
          timestamp: '2025-04-19',
          open: 1000,
          high: 1100,
          low: 900,
          close: 1050,
          volume: 120000,
        },
        {
          timestamp: '2026-04-20',
          open: 10,
          high: 11,
          low: 9,
          close: 10.5,
          volume: 130000,
        },
      ]}
      markers={[
        {
          timestamp: '2025-04-19',
          kind: 'buy',
          price: 2000,
          label: 'Buy',
        },
      ]}
    />,
  );

  expect(screen.getByTestId('kline-trade-marker-buy')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Show 1M K-line range' }));

  expect(screen.queryByTestId('kline-trade-marker-buy')).toBeNull();
  expect(screen.getByText('¥9.00 - ¥11.00')).toBeTruthy();
});
