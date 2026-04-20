import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { PositionsTable } from "./components/positions-table";

test("renders active positions", () => {
  render(
    <PositionsTable
      positions={[
        {
          symbol: "600519",
          quantity: 60,
          available_qty: 60,
          frozen_qty: 0,
          avg_cost: 1500,
          market_value: 96000,
          unrealized_pnl: 6000,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getByText("600519")).toBeTruthy();
  expect(screen.getByText("60")).toBeTruthy();
});
