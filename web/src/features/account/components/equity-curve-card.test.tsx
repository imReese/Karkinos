import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { PreferencesProvider } from "../../../app/preferences";
import { EquityCurveCard } from "./equity-curve-card";
import type { EquitySeriesPoint } from "../api";

const points: EquitySeriesPoint[] = [
  {
    timestamp: "2026-04-18T09:00:00+00:00",
    total: 100000,
    stocks: 0,
    funds: 0,
    others: 0,
    cash: 100000,
  },
  {
    timestamp: "2026-04-18T10:00:00+00:00",
    total: 101550,
    stocks: 11000,
    funds: 5300,
    others: 9250,
    cash: 76000,
  },
];

function renderCard() {
  const originalWarn = console.warn;
  vi.spyOn(console, "warn").mockImplementation((message?: unknown) => {
    if (
      typeof message === "string" &&
      message.includes("The width(-1) and height(-1) of chart should be greater than 0")
    ) {
      return;
    }
    originalWarn(message);
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    value: 800,
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    value: 380,
  });
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      bottom: 380,
      height: 380,
      left: 0,
      right: 800,
      top: 0,
      width: 800,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }),
  });
  window.ResizeObserver = class ResizeObserver {
    private readonly callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }

    observe(target: Element) {
      this.callback(
        [
          {
            target,
            contentRect: {
              bottom: 380,
              height: 380,
              left: 0,
              right: 800,
              top: 0,
              width: 800,
              x: 0,
              y: 0,
              toJSON: () => ({}),
            },
          } as ResizeObserverEntry,
        ],
        this,
      );
    }

    unobserve() {}

    disconnect() {}
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  render(
    <PreferencesProvider>
      <EquityCurveCard points={points} />
    </PreferencesProvider>,
  );
}

test("renders premium performance dashboard controls", async () => {
  renderCard();

  expect(await screen.findByText("Performance Analysis")).toBeTruthy();
  for (const label of ["Total", "Stocks", "Funds", "Others", "Cash"]) {
    const chip = await screen.findByRole("button", { name: label });
    expect(chip.className).toContain("rounded-full");
    expect(chip.getAttribute("aria-pressed")).toBe("true");
  }

  for (const label of ["1D", "5D", "1M", "6M", "1Y", "ALL"]) {
    expect(await screen.findByRole("button", { name: `Range: ${label}` })).toBeTruthy();
  }
});

test("toggles category chips without removing the control", async () => {
  renderCard();
  const user = userEvent.setup();

  const stocks = await screen.findByRole("button", { name: "Stocks" });
  await user.click(stocks);

  expect(stocks.getAttribute("aria-pressed")).toBe("false");
});
