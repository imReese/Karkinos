import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { TradeForm } from './components/trade-form';
import { FundBatchForm } from './components/fund-batch-form';
import { CashFlowForm } from './components/cash-flow-form';
import { DividendForm } from './components/dividend-form';
import { ManualAdjustmentForm } from './components/manual-adjustment-form';
import { ActivityFeed } from './components/activity-feed';

test('submits a manual trade payload', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<TradeForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '600519' },
  });
  fireEvent.change(screen.getByLabelText('Quantity'), {
    target: { value: '100' },
  });
  fireEvent.change(screen.getByLabelText('Unit Price'), {
    target: { value: '1500' },
  });
  fireEvent.click(screen.getByText('Save Trade'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: '600519',
      quantity: 100,
      unit_price: 1500,
    }),
  );
});

test('prefills manual trade fee from account commission settings', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(
    <TradeForm
      onSubmit={onSubmit}
      commissionSettings={{
        stock_rate: 0.00025,
        stock_min_commission: 3,
      }}
    />,
  );

  fireEvent.change(screen.getByLabelText('Quantity'), {
    target: { value: '200' },
  });
  fireEvent.change(screen.getByLabelText('Unit Price'), {
    target: { value: '28.82' },
  });

  const feeInput = screen.getByLabelText('Fee') as HTMLInputElement;
  expect(feeInput.value).toBe('3');
  expect(
    screen.getByText('Commission rate 2.5 bp, minimum CN¥3.00'),
  ).toBeTruthy();
});

test('submits a fund buy by subscription amount', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<TradeForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '012710' },
  });
  fireEvent.change(screen.getByLabelText('Asset Class'), {
    target: { value: 'fund' },
  });
  fireEvent.change(screen.getByLabelText('Subscription Amount'), {
    target: { value: '200' },
  });
  fireEvent.click(screen.getByText('Save Trade'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: '012710',
      asset_class: 'fund',
      amount: 200,
    }),
  );
});

test('does not render hard-coded fund candidates in the initial state', () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<FundBatchForm onSubmit={onSubmit} />);

  expect(screen.queryByText('永赢先进制造智选混合C')).toBeNull();
  expect(screen.queryByText('融通科技臻选混合C')).toBeNull();
  expect(screen.queryByText('华夏核心成长混合C')).toBeNull();
  expect(
    screen.getByText('No held funds available for batch add.'),
  ).toBeTruthy();
});

test('submits a batch fund add payload with positive candidate rows only', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(
    <FundBatchForm
      onSubmit={onSubmit}
      candidates={[
        { symbol: '018125', display_name: 'Configured Fund A' },
        { symbol: '012710', display_name: 'Configured Fund C' },
      ]}
    />,
  );

  fireEvent.change(screen.getByLabelText('018125 Amount'), {
    target: { value: '200' },
  });
  fireEvent.change(screen.getByLabelText('012710 Amount'), {
    target: { value: '300' },
  });
  fireEvent.click(screen.getByText('Save Batch'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0].orders).toEqual([
    expect.objectContaining({ symbol: '018125', amount: 200 }),
    expect.objectContaining({ symbol: '012710', amount: 300 }),
  ]);
});

test('keeps batch fund rows shrinkable for responsive activity layouts', () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  const { container } = render(
    <FundBatchForm
      onSubmit={onSubmit}
      candidates={[
        {
          symbol: '018125',
          display_name:
            '永赢先进制造智选混合发起C超长中文名称用于响应式布局验证',
        },
      ]}
    />,
  );

  const form = container.querySelector('form') as HTMLFormElement | null;
  const amountInput = screen.getByLabelText('018125 Amount');

  expect(form?.className).toContain('min-w-0');
  expect(form?.className).toContain('max-w-full');
  expect(amountInput.className).toContain('min-w-0');
  expect(amountInput.className).toContain('w-full');
  expect(screen.getByText(/超长中文名称/).className).toContain('break-words');
});

test('submits a dividend payload', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<DividendForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Dividend Symbol'), {
    target: { value: '600519' },
  });
  fireEvent.change(screen.getByLabelText('Dividend Amount'), {
    target: { value: '88.8' },
  });
  fireEvent.click(screen.getByText('Save Dividend'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: '600519',
      amount: 88.8,
    }),
  );
});

test('submits a manual adjustment payload', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<ManualAdjustmentForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Adjustment Symbol'), {
    target: { value: '600519' },
  });
  fireEvent.change(screen.getByLabelText('Adjustment Amount'), {
    target: { value: '1000' },
  });
  fireEvent.change(screen.getByLabelText('Adjustment Quantity'), {
    target: { value: '5' },
  });
  fireEvent.click(screen.getByText('Save Adjustment'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: '600519',
      amount: 1000,
      quantity: 5,
    }),
  );
});

test('submits a cash flow payload', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<CashFlowForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Amount'), {
    target: { value: '5000' },
  });
  fireEvent.click(screen.getByText('Save Cash Flow'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      amount: 5000,
      flow_type: 'deposit',
    }),
  );
});

test('renders ledger entries as a user-facing audit table', () => {
  render(
    <ActivityFeed
      entries={[
        {
          id: 1,
          entry_type: 'trade_buy',
          timestamp: '2026-04-23T14:46:00+00:00',
          amount: 200,
          symbol: '012710',
          direction: 'buy',
          quantity: 204.102,
          price: 0.9799,
          commission: 0,
          asset_class: 'fund',
          note: '用户记录：华夏核心成长混合C 买入 200 元 | Auto-confirmed pending fund subscription: gross_amount=200.00 | confirmed_nav=0.979900',
          source: 'manual',
          source_ref: 'trade_buy-012710',
          created_at: null,
          display_name: null,
        },
        {
          id: 2,
          entry_type: 'trade_buy',
          timestamp: '2026-06-05T06:33:41+00:00',
          amount: 2755,
          symbol: '603659',
          direction: 'buy',
          quantity: 100,
          price: 27.55,
          commission: 5,
          asset_class: 'stock',
          note: '手工录入持仓：璞泰来 买入，佣金按万一最低5元计收',
          source: 'manual',
          source_ref: 'manual-603659-20260605-143341',
          created_at: null,
          display_name: null,
        },
        {
          id: 3,
          entry_type: 'trade_buy',
          timestamp: '2026-06-16T03:04:56+00:00',
          amount: 5270,
          symbol: '600066',
          direction: 'buy',
          quantity: 200,
          price: 26.35,
          commission: 5,
          asset_class: 'stock',
          note: '手工录入持仓：宇通客车 600066 买入，佣金按万1.5，最低5元计收',
          source: 'manual',
          source_ref: 'manual-600066-20260616-110456',
          created_at: null,
          display_name: '宇通客车',
          gross_amount: 5270,
          net_cash_impact: -5275.16,
          fee_breakdown: {
            commission: '5',
            stamp_tax: '0',
            transfer_fee: '0.16',
            other_fees: '0',
            total_fee: '5.16',
          },
          fee_rule_id: 'manual_configured_commission',
          fee_rule_version: 'account_commission_rate',
          cost_basis_method: 'moving_average_buy_cost',
        } as unknown as import('./api').LedgerEntry,
      ]}
    />,
  );

  expect(screen.getAllByText('Security buy').length).toBeGreaterThan(1);
  expect(screen.getByText('Fund')).toBeTruthy();
  expect(screen.getAllByText('Manual entry').length).toBeGreaterThan(1);
  expect(screen.getByText('-CN¥200.00')).toBeTruthy();
  expect(screen.getByText('华夏核心成长混合C')).toBeTruthy();
  expect(screen.getByText('Amount CN¥200.00')).toBeTruthy();
  expect(screen.getByText('Quantity 204.102')).toBeTruthy();
  expect(screen.getByText('Price CN¥0.98')).toBeTruthy();
  expect(screen.queryByText('Fee CN¥0.00')).toBeNull();
  expect(screen.getByText('璞泰来')).toBeTruthy();
  expect(screen.getByText('宇通客车')).toBeTruthy();
  expect(screen.getByText('-CN¥5,275.16')).toBeTruthy();
  expect(screen.getByText('Gross amount CN¥5,270.00')).toBeTruthy();
  expect(screen.queryByText('Net cash impact -CN¥5,275.16')).toBeNull();
  expect(screen.getByText('Commission CN¥5.00')).toBeTruthy();
  expect(screen.getByText('Stamp tax CN¥0.00')).toBeTruthy();
  expect(screen.getByText('Transfer fee CN¥0.16')).toBeTruthy();
  expect(screen.queryByText(/Cost basis/)).toBeNull();
  expect(screen.queryByText(/moving_average_buy_cost/)).toBeNull();
  expect(screen.queryByText('宇通客车 600066')).toBeNull();
  expect(screen.queryByText(/宇通客车 600066/)).toBeNull();
  expect(screen.getAllByText('Stock').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText('603659')).toBeTruthy();
  expect(screen.getByText('600066')).toBeTruthy();
  expect(screen.queryByText(/手工录入持仓/)).toBeNull();
  expect(screen.queryByText(/gross_amount/)).toBeNull();
  expect(screen.queryByText(/Auto-confirmed/)).toBeNull();
});
