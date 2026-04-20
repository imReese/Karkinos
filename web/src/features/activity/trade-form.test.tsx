import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { TradeForm } from "./components/trade-form";
import { CashFlowForm } from "./components/cash-flow-form";
import { DividendForm } from "./components/dividend-form";
import { ManualAdjustmentForm } from "./components/manual-adjustment-form";

test("submits a manual trade payload", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<TradeForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText("Symbol"), {
    target: { value: "600519" },
  });
  fireEvent.change(screen.getByLabelText("Quantity"), {
    target: { value: "100" },
  });
  fireEvent.change(screen.getByLabelText("Unit Price"), {
    target: { value: "1500" },
  });
  fireEvent.click(screen.getByText("Save Trade"));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: "600519",
      quantity: 100,
      unit_price: 1500,
    }),
  );
});

test("submits a dividend payload", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<DividendForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText("Dividend Symbol"), {
    target: { value: "600519" },
  });
  fireEvent.change(screen.getByLabelText("Dividend Amount"), {
    target: { value: "88.8" },
  });
  fireEvent.click(screen.getByText("Save Dividend"));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: "600519",
      amount: 88.8,
    }),
  );
});

test("submits a manual adjustment payload", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<ManualAdjustmentForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText("Adjustment Symbol"), {
    target: { value: "600519" },
  });
  fireEvent.change(screen.getByLabelText("Adjustment Amount"), {
    target: { value: "1000" },
  });
  fireEvent.change(screen.getByLabelText("Adjustment Quantity"), {
    target: { value: "5" },
  });
  fireEvent.click(screen.getByText("Save Adjustment"));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      symbol: "600519",
      amount: 1000,
      quantity: 5,
    }),
  );
});

test("submits a cash flow payload", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);

  render(<CashFlowForm onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText("Amount"), {
    target: { value: "5000" },
  });
  fireEvent.click(screen.getByText("Save Cash Flow"));

  await waitFor(() => {
    expect(onSubmit).toHaveBeenCalled();
  });

  expect(onSubmit.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      amount: 5000,
      flow_type: "deposit",
    }),
  );
});
