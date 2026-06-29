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
  expect(screen.getByText('¥1,640.00')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: 'Show 1M K-line range' }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole('button', { name: 'Show All K-line range' })
      .getAttribute('aria-pressed'),
  ).toBe('true');
  expect(screen.getByText('Price axis')).toBeTruthy();
  expect(screen.getByText('Date axis')).toBeTruthy();
  expect(screen.getByText('2025-04-19')).toBeTruthy();
  expect(screen.getByText('2026-04-20')).toBeTruthy();
  expect(
    container.querySelectorAll('[data-testid="kline-candle"]').length,
  ).toBe(2);
  expect(
    container.querySelector('[data-testid="close-price-trend"]'),
  ).toBeNull();
  const chartScroll = screen.getByTestId('price-structure-chart-scroll');
  const chartCanvas = screen.getByTestId('price-structure-chart-canvas');
  expect(chartScroll.className).toContain('overflow-x-auto');
  expect(chartScroll.className).toContain('pb-2');
  expect(chartCanvas.className).toContain('min-w-[640px]');

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
  render(
    <PriceStructureChart
      titleLabel="Price range / K-line"
      priceLabel="Price"
      emptyLabel="No chart"
      bars={[]}
    />,
  );

  expect(screen.getByText('No chart')).toBeTruthy();
  expect(screen.getByText('Price range / K-line')).toBeTruthy();
});
