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

test('does not mark an auto-prefilled trade fee as a manual fee override', async () => {
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

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '600002' },
  });
  fireEvent.change(screen.getByLabelText('Quantity'), {
    target: { value: '200' },
  });
  fireEvent.change(screen.getByLabelText('Unit Price'), {
    target: { value: '28.82' },
  });
  fireEvent.click(screen.getByText('Save Trade'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0].fee).toBe(3);
  expect(onSubmit.mock.calls[0][0].fee_is_manual).toBe(false);
});

test('marks an edited trade fee as a manual fee override', async () => {
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

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '600002' },
  });
  fireEvent.change(screen.getByLabelText('Quantity'), {
    target: { value: '200' },
  });
  fireEvent.change(screen.getByLabelText('Unit Price'), {
    target: { value: '28.82' },
  });
  fireEvent.change(screen.getByLabelText('Fee'), {
    target: { value: '8.5' },
  });
  fireEvent.click(screen.getByText('Save Trade'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0].fee).toBe(8.5);
  expect(onSubmit.mock.calls[0][0].fee_is_manual).toBe(true);
});

test('shows structured manual trade preview before saving', () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(
    <TradeForm
      onSubmit={onSubmit}
      tradePreview={{
        symbol: '600002',
        direction: 'buy',
        quantity: 200,
        price: 28.82,
        gross_amount: 5764,
        commission: 3,
        total_fee: 3.05764,
        net_cash_impact: -5767.05764,
        fee_breakdown: {
          commission: '3.00',
          stamp_tax: '0.000000',
          transfer_fee: '0.057640',
          other_fees: '0.000000',
          total_fee: '3.057640',
        },
        fee_rule_id: 'manual_configured_commission',
        fee_rule_version: 'account_commission_rate',
        cost_basis_method: 'moving_average_buy_cost',
        note: '账户佣金配置：佣金率万2.5，最低3元',
      }}
    />,
  );

  expect(screen.getByText('Trade preview')).toBeTruthy();
  expect(screen.getByText('Gross amount')).toBeTruthy();
  expect(screen.getByText('CN¥5,764.00')).toBeTruthy();
  expect(screen.getByText('Commission')).toBeTruthy();
  expect(screen.getByText('CN¥3.00')).toBeTruthy();
  expect(screen.getByText('Stamp tax')).toBeTruthy();
  expect(screen.getByText('CN¥0.00')).toBeTruthy();
  expect(screen.getByText('Transfer fee')).toBeTruthy();
  expect(screen.getByText('CN¥0.06')).toBeTruthy();
  expect(screen.getByText('Total fee')).toBeTruthy();
  expect(screen.getByText('CN¥3.06')).toBeTruthy();
  expect(screen.getByText('Net cash impact')).toBeTruthy();
  expect(screen.getByText('-CN¥5,767.06')).toBeTruthy();
  expect(screen.getByText('Configured account fee rule')).toBeTruthy();
  expect(screen.getByText('Moving average buy cost')).toBeTruthy();
  expect(screen.queryByText('账户佣金配置：佣金率万2.5，最低3元')).toBeNull();
});

test('submits a fund buy by subscription amount', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<TradeForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '012999' },
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
      symbol: '012999',
      asset_class: 'fund',
      amount: 200,
    }),
  );
});

test('does not render hard-coded fund candidates in the initial state', () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<FundBatchForm onSubmit={onSubmit} />);

  expect(screen.queryByText('示例成长混合C')).toBeNull();
  expect(screen.queryByText('示例科技混合C')).toBeNull();
  expect(screen.queryByText('示例稳健混合C')).toBeNull();
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
        { symbol: '019999', display_name: 'Configured Fund A' },
        { symbol: '012999', display_name: 'Configured Fund C' },
      ]}
    />,
  );

  fireEvent.change(screen.getByLabelText('019999 Amount'), {
    target: { value: '200' },
  });
  fireEvent.change(screen.getByLabelText('012999 Amount'), {
    target: { value: '300' },
  });
  fireEvent.click(screen.getByText('Save Batch'));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0].orders).toEqual([
    expect.objectContaining({ symbol: '019999', amount: 200 }),
    expect.objectContaining({ symbol: '012999', amount: 300 }),
  ]);
});

test('keeps batch fund rows shrinkable for responsive activity layouts', () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  const { container } = render(
    <FundBatchForm
      onSubmit={onSubmit}
      candidates={[
        {
          symbol: '019999',
          display_name: '示例成长混合C超长中文名称用于响应式布局验证',
        },
      ]}
    />,
  );

  const form = container.querySelector('form') as HTMLFormElement | null;
  const amountInput = screen.getByLabelText('019999 Amount');

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
          symbol: '012999',
          direction: 'buy',
          quantity: 204.102,
          price: 0.9799,
          commission: 0,
          asset_class: 'fund',
          note: '用户记录：示例稳健混合C 买入 200 元 | Auto-confirmed pending fund subscription: gross_amount=200.00 | confirmed_nav=0.979900',
          source: 'manual',
          source_ref: 'trade_buy-012999',
          created_at: null,
          display_name: null,
        },
        {
          id: 2,
          entry_type: 'trade_buy',
          timestamp: '2026-01-12T06:33:41+00:00',
          amount: 1850,
          symbol: '600002',
          direction: 'buy',
          quantity: 100,
          price: 18.5,
          commission: 5,
          asset_class: 'stock',
          note: '合成测试流水：示例材料 买入，按本地费率规则计费',
          source: 'manual',
          source_ref: 'manual-stock-b-20260112-103000',
          created_at: null,
          display_name: null,
        },
        {
          id: 3,
          entry_type: 'trade_buy',
          timestamp: '2026-01-15T03:04:56+00:00',
          amount: 3250,
          symbol: '600003',
          direction: 'buy',
          quantity: 200,
          price: 16.25,
          commission: 5,
          asset_class: 'stock',
          note: '合成测试流水：示例制造 600003 买入，按本地费率规则计费',
          source: 'manual',
          source_ref: 'manual-stock-a-20260115-100000',
          created_at: null,
          display_name: '示例制造',
          gross_amount: 3250,
          net_cash_impact: -3255.16,
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
  expect(screen.getByText('示例稳健混合C 012999')).toBeTruthy();
  expect(screen.getByText('Amount CN¥200.00')).toBeTruthy();
  expect(screen.getByText('Quantity 204.102')).toBeTruthy();
  expect(screen.getByText('Price CN¥0.98')).toBeTruthy();
  expect(screen.queryByText('Fee CN¥0.00')).toBeNull();
  expect(screen.getByText('示例材料 600002')).toBeTruthy();
  expect(screen.getByText('示例制造 600003')).toBeTruthy();
  expect(screen.getByText('-CN¥3,255.16')).toBeTruthy();
  expect(screen.getByText('Gross amount CN¥3,250.00')).toBeTruthy();
  expect(screen.getByText('Net cash impact -CN¥3,255.16')).toBeTruthy();
  expect(screen.getByText('Commission CN¥5.00')).toBeTruthy();
  expect(screen.getByText('Stamp tax CN¥0.00')).toBeTruthy();
  expect(screen.getByText('Transfer fee CN¥0.16')).toBeTruthy();
  expect(screen.queryByText(/Cost basis/)).toBeNull();
  expect(screen.queryByText(/moving_average_buy_cost/)).toBeNull();
  expect(screen.getAllByText('Stock').length).toBeGreaterThanOrEqual(2);
  expect(screen.queryByText('600002')).toBeNull();
  expect(screen.queryByText('600003')).toBeNull();
  expect(screen.queryByText(/手工录入持仓/)).toBeNull();
  expect(screen.queryByText(/gross_amount/)).toBeNull();
  expect(screen.queryByText(/Auto-confirmed/)).toBeNull();
});
