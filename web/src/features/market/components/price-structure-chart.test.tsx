import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { PriceStructureChart } from './price-structure-chart';

test('renders OHLC price range as a K-line chart', () => {
  const { container } = render(
    <PriceStructureChart
      titleLabel="Price range / K-line"
      priceLabel="Price"
      emptyLabel="No chart"
      bars={[
        {
          timestamp: '2026-04-19',
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
  expect(screen.getByText('CN¥1,640.00')).toBeTruthy();
  expect(container.querySelectorAll('rect').length).toBe(2);
  expect(container.querySelector('polyline')).not.toBeNull();
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
