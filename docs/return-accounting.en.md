# Karkinos return and cost conventions

[中文](return-accounting.zh.md) | [Documentation](README.en.md)

This document defines the basic return, cost, and reference-price conventions
used by the Karkinos Web product and backend API. Portfolio totals, individual
asset views, the return calendar, and holding details should all use the same
explainable rules.

Karkinos does not provide investment advice or guarantee perfect agreement
with market-data or broker accounting. These conventions support traceable
local portfolio calculations and diagnostics.

## Core classifications

### Today's profit and loss

Today's P/L answers:

> How much did today's market-price movement change the value of the positions
> I currently hold?

For a regular holding:

```text
today P/L = current quantity * (current market price - daily reference price)
today return = current market price / daily reference price - 1
```

This normally does not use the holding cost basis. Cost basis answers “how much
has this position gained or lost since purchase,” not “how much did its price
move today.”

Daily reference-price priority:

1. previous trading-day `close` from local OHLC `market_bars`;
2. previous trading-day close from `daily_close_snapshots`;
3. `previous_close` reported by the current quote;
4. an older cached quote as a last resort.

If local OHLC and a live quote disagree on previous close, local OHLC wins so
the return calendar, candlestick view, and today's P/L share one reviewable
historical convention.

### Positions bought today

A stock or fund first bought today cannot simply use yesterday's close; that
would assign pre-purchase price movement to the account. For the quantity
bought and still held on the same day:

```text
today P/L for today's purchase = current market value - today's total purchase cost
```

Total purchase cost includes trade value and determinable fees such as
commission and transfer fee. A broker may use different rounding, minimum
commission, regulatory fees, or tax treatment. Prefer imported broker
settlement evidence when available.

### Return since purchase / unrealized P&L

This answers:

> From my actual holding cost to the current price, what is the unrealized gain
> or loss?

```text
unrealized P/L = current market value - position cost amount
position cost amount = current quantity * cost basis
return = unrealized P/L / position cost amount
```

Cost basis should track the broker-account convention as closely as possible.
For A-shares it may depend on:

- commission rate and minimum commission;
- transfer fees;
- regulatory or handling fees combined in the broker display;
- sell-side stamp tax;
- remaining-position basis after partial buys and sells;
- rounding and internal broker precision.

Karkinos displays a local-ledger cost view. Correct a disagreement using a
statement or richer fee rule, never by inferring basis from the market price.

### Realized P&L

Realized P/L comes from confirmed sales, dividends, redemptions, and other
completed events. It does not belong in today's market movement and does not
replace the current position's unrealized result.

```text
total return = realized P/L + unrealized P/L
```

Product surfaces should explicitly distinguish realized, unrealized, and
today's figures rather than mixing time dimensions.

### Cash

Cash has no market-price movement and therefore no unrealized P/L. Its changes
are cash-flow events:

- deposit;
- withdrawal;
- cash consumed by a buy;
- cash released by a sell;
- dividend receipt;
- fee deduction.

Cash participates in the equity curve and asset allocation, but tooltips and
return cards should not show “cash unrealized P/L.”

## Portfolio aggregation

The Overview “today's P/L” aggregates priced asset classes:

```text
stock today P/L = sum of stock today P/L
fund today P/L = sum of fund today P/L
total today P/L = stock + fund + other priced-asset today P/L
```

Deposits, withdrawals, buys, sells, dividends, and fees are event flows, not
market returns. A return calendar may display them as explanation context, but
market P/L and event inflow/outflow remain separate.

## Traceability

When an instrument has multiple price sources, the product should expose or be
able to diagnose:

- current market price and timestamp;
- current source;
- daily reference price and source;
- whether cache was used;
- the cache or missing-price reason.

If historical bars or fund NAV are missing, Karkinos reports missing/cached
status instead of fabricating a return.

## Example

For a synthetic position of 200 shares of `SYNTH001`:

```text
cost basis = 10.2500
current price = 10.7800
previous trading-day OHLC close = 10.6000
```

Today's P/L:

```text
200 * (10.7800 - 10.6000) = +36.00
```

Unrealized P/L since purchase:

```text
200 * (10.7800 - 10.2500) = +106.00
```

The values differ because they answer different questions.
