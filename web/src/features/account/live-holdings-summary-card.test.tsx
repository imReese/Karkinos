import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { PreferencesProvider } from "../../app/preferences";
import { LiveHoldingsSummaryCard } from "./components/live-holdings-summary-card";

function renderCard(locale: "en" | "zh" = "en", onSelectAssetClass?: (value: string) => void) {
  window.localStorage.clear();
  window.localStorage.setItem("myquant.locale", locale);
  document.documentElement.lang = locale === "zh" ? "zh-CN" : "en-US";
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: query.includes("light"),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
    }),
  });

  render(
    <PreferencesProvider>
      <LiveHoldingsSummaryCard
        onSelectAssetClass={onSelectAssetClass}
        groups={[
          {
            asset_class: "stock",
            label: locale === "zh" ? "股票" : "Stock",
            total_market_value: 2000,
            total_today_change: 120,
            total_since_buy_pnl: 300,
            items: [],
          },
        ]}
      />
    </PreferencesProvider>,
  );
}

test("renders overview live holdings summary in english", () => {
  renderCard("en");
  expect(screen.getByText("Live asset pulse")).toBeTruthy();
  expect(screen.getByText("Stock")).toBeTruthy();
  expect(screen.getByText("Market value")).toBeTruthy();
  expect(screen.getByText("Today move")).toBeTruthy();
});

test("renders overview live holdings summary in chinese", () => {
  renderCard("zh");
  expect(screen.getByText("实时资产脉冲")).toBeTruthy();
  expect(screen.getByText("股票")).toBeTruthy();
  expect(screen.getByText("持仓市值")).toBeTruthy();
  expect(screen.getByText("今日涨跌")).toBeTruthy();
});

test("emits selected asset class when a summary card is clicked", () => {
  const observed: string[] = [];
  renderCard("en", (value) => observed.push(value));

  fireEvent.click(screen.getByRole("button", { name: /stock/i }));

  expect(observed).toEqual(["stock"]);
});
