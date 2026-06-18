# Karkinos Strategy Primer

[中文](README.zh.md) | [Back to English docs](../README.en.md)

This page explains the built-in Karkinos backtest strategies, their current
implementation semantics, and how to read their evidence boundaries. These
strategies are research baselines and auditable templates. They are not investment advice,
return guarantees, or authorization for automatic trading.

## How to Read a Strategy

A Karkinos strategy usually has four layers:

- **Market hypothesis**: what market behavior the strategy is trying to test.
- **Signal rule**: the condition under which the strategy emits a target weight.
- **Parameters**: lookback windows, thresholds, or target allocation settings.
- **Evidence requirements**: after-cost, out-of-sample, risk, paper/shadow, and
  account-truth evidence required before treating a result seriously.

Karkinos strategies emit target weights. For example, `1.0` means the strategy
wants exposure to the instrument, while `0.0` means it wants no exposure. Share
count conversion, fees, slippage, T+1 constraints, risk gates, and manual
confirmation are handled downstream.

## Dual Moving Average

Internal ID: `dual_ma`

### Core Idea

Dual moving average is a transparent trend-following baseline. A short moving
average represents recent price behavior, while a longer moving average
represents the slower background trend.

When the short average crosses above the long average, the strategy treats the
recent trend as strengthening. When the short average crosses below the long
average, the strategy treats the trend as weakening.

### Current Implementation

Karkinos currently implements it as follows:

- Collect close prices per instrument.
- Wait until at least `long_period` bars are available.
- Compute short and long simple moving averages.
- If the short average crosses from below to above the long average, emit a
  target weight of `1.0`.
- If the short average crosses from above to below the long average, emit a
  target weight of `0.0`.

### Main Parameters

| Parameter | Meaning | Default |
| --- | --- | --- |
| `short_period` | Short moving-average window in trading bars | 5 |
| `long_period` | Long moving-average window in trading bars | 20 |

### Questions It Can Test

- Whether an instrument has persistent enough trend behavior.
- Whether trend signals survive fees, slippage, and turnover.
- Whether parameter changes remain stable instead of working only for one
  fitted configuration.

### Common Failure Modes

- Choppy markets can create repeated crossovers and cost drag.
- Sudden selloffs or gaps can make moving-average signals lag.
- Single-instrument trend strategies can be sensitive to event risk and
  liquidity shocks.

### Karkinos Evidence Focus

Read dual moving average together with after-cost performance, OOS evidence,
drawdown, trade count, fees, slippage, and risk-gate blocks. It is a
trend-following baseline, not proof of live readiness.

## Monthly Rebalance

Internal ID: `monthly_rebalance`

### Core Idea

Monthly rebalance is not a prediction of tomorrow's return. It is an allocation
discipline that periodically brings a portfolio back toward configured target
weights.

When one asset rises more than others, its portfolio weight may drift above the
target. When one asset falls, it may drift below target. Rebalancing tests
whether periodically correcting that drift improves portfolio behavior after
costs.

### Current Implementation

Karkinos currently implements it as follows:

- Track the last month in which each instrument emitted a rebalance signal.
- When a new trading bar belongs to a new month, read that instrument's target
  weight.
- Emit the configured target-weight signal.
- If no target weight is configured for an instrument, the target defaults to
  `0.0`.

### Main Parameters

| Parameter | Meaning | Default |
| --- | --- | --- |
| `target_weights` | Target weights by symbol, expressed as 0-1 decimals | Empty |

### Questions It Can Test

- Drawdown, volatility, and turnover of a fixed allocation rule.
- Whether rebalancing reduces concentration or portfolio drift.
- Whether target weights are robust across different market regimes.

### Common Failure Modes

- If target weights are poor, rebalancing only executes a poor allocation more
  consistently.
- Mixed data calendars, frequencies, or cost models can contaminate results.
- Rebalancing too frequently increases cost; rebalancing too rarely may lose
  discipline.

### Karkinos Evidence Focus

Monthly rebalance should be read through asset-class coverage, target weights,
transaction cost, turnover, drawdown, and drift. It is an allocation rule, not a
price-prediction signal.

## Bollinger Mean Reversion

Internal ID: `bollinger`

### Core Idea

Bollinger Bands use a moving average as the middle band, with upper and lower
bands based on standard deviation. The mean-reversion hypothesis is that a
short-term move far below the recent mean may revert toward the middle band.

In the current Karkinos implementation, a move below the lower band creates an
entry signal, and a return to the middle band exits.

### Current Implementation

Karkinos currently implements it as follows:

- Collect close prices per instrument.
- Wait until at least `bb_period` bars are available.
- Compute the mean and standard deviation of the latest `bb_period` closes.
- The middle band is the moving average.
- The upper band is `mean + num_std * standard deviation`.
- The lower band is `mean - num_std * standard deviation`.
- If not holding and price is at or below the lower band, emit a target weight
  of `1.0`.
- If holding and price reaches or exceeds the middle band, emit a target weight
  of `0.0`.

### Main Parameters

| Parameter | Meaning | Default |
| --- | --- | --- |
| `bb_period` | Bollinger lookback window in trading bars | 20 |
| `num_std` | Standard-deviation multiplier for the upper/lower bands | 2.0 |

### Questions It Can Test

- Whether an instrument tends to rebound after short-term overreaction.
- Whether lower-band entries and middle-band exits survive cost and slippage.
- Whether the strategy breaks during persistent downtrends.

### Common Failure Modes

- In strong downtrends, price can continue falling along the lower band.
- Sudden volatility regime shifts can make historical standard deviation
  misleading.
- Illiquid instruments can create false band touches through jumpy prices.

### Karkinos Evidence Focus

Bollinger results need drawdown, losing streak, holding-period, execution-cost,
and risk-block review. The key question is not whether one rebound worked, but
how the rule behaves when mean reversion fails.

## RSI Momentum / Reversal

Internal ID: `rsi`

Current registry label: RSI Mean Reversion

### Core Idea

RSI, or Relative Strength Index, compares smoothed recent gains and losses. A
low RSI is often interpreted as oversold; a high RSI is often interpreted as
overbought.

The current Karkinos implementation is closer to RSI reversal / mean reversion:
it buys when RSI recovers out of oversold territory and exits when RSI falls
back from overbought territory.

### Current Implementation

Karkinos currently implements it as follows:

- Compute RSI with Wilder smoothing.
- Wait until at least `rsi_period + 1` prices are available.
- If RSI crosses upward from below `oversold` to at least `oversold`, emit a
  target weight of `1.0`.
- If RSI crosses downward from above `overbought` to at most `overbought`, emit
  a target weight of `0.0`.

### Main Parameters

| Parameter | Meaning | Default |
| --- | --- | --- |
| `rsi_period` | RSI smoothing window in trading bars | 14 |
| `oversold` | Buy threshold crossed upward | 30 |
| `overbought` | Sell threshold crossed downward | 70 |

### Questions It Can Test

- Whether an instrument tends to rebound after short-term weakness.
- Whether RSI thresholds are stable or fitted to one historical window.
- Whether combining RSI with trend filters and risk gates improves robustness.

### Common Failure Modes

- In strong trends, RSI can remain high or low for long periods.
- A short period can be noisy; a long period can be late.
- RSI alone ignores liquidity, fundamentals, and event risk.

### Karkinos Evidence Focus

RSI should be reviewed through OOS behavior, parameter sensitivity, drawdown,
P/L distribution beyond win rate, and whether risk gates block bad signals in
persistent selloffs.

## Strategy Comparison

| Strategy | Primary hypothesis | Signal style | Best used to test |
| --- | --- | --- | --- |
| Dual Moving Average | Trends can persist | Trend following | Trend persistence and after-cost viability |
| Monthly Rebalance | Allocation needs discipline | Periodic target weights | Portfolio drift, drawdown, turnover cost |
| Bollinger | Short-term extremes may mean-revert | Mean reversion | Overreaction, rebound behavior, downtrend risk |
| RSI | Oversold/overbought moves may reverse | Reversal / mean reversion | Threshold stability and reversal quality |

## Safety Boundary

- These strategies are research and audit examples, not investment advice.
- Backtest returns do not predict future returns.
- A single backtest cannot prove a strategy is valid.
- Karkinos does not enable automatic order submission just because a strategy
  passed a backtest.
- Live-like workflows must keep manual confirmation and risk gates.
- Real account facts, broker evidence, and private ledger exports should not be
  committed to the repository.
