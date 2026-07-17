# Karkinos Goal

[中文](KARKINOS_GOAL.zh.md) | [Roadmap](ROADMAP.md) | [Architecture](ARCHITECTURE.md) | [Documentation](README.en.md)

## North Star

Karkinos is a China-market personal quant research and trading platform, not a
toy backtester and not an unattended profit robot.

It should help one serious investor make fewer emotional mistakes, validate
strategies before use, control downside first, and keep every material decision
auditable. The daily product question is:

> Given my portfolio, persisted market and account evidence, risk limits, and
> validated strategies, what should I do today — buy, sell, hold, rebalance, or
> do nothing — and why?

The long-term target is a human-supervised, capital-bounded operating system for
personal investing. Authority is explicit, expiring, observable, reversible,
and scalable only through reviewed evidence.

## Product Promise

Karkinos connects the full investment operating loop:

```text
research idea
-> reproducible backtest and after-cost/OOS evidence
-> human-reviewed research conclusion
-> daily decision and target portfolio
-> data, account, and risk gates
-> paper/shadow validation
-> human-confirmed controlled execution
-> broker and ledger reconciliation
-> post-decision review
-> strategy improvement
```

Each transition preserves identity, provenance, limitations, and the reason an
action is allowed, blocked, or requires review.

## Product Boundaries

### Financial facts

- Persisted canonical facts own portfolio, ledger, valuation, performance,
  account, order, fill, and reconciliation state.
- A financial concept has one calculation owner; Web, reports, and AI do not
  recreate it independently.
- Missing, unpublished, partial, stale, ambiguous, or conflicting evidence
  fails closed instead of being replaced by a plausible value.
- Broker evidence does not silently mutate the production ledger.

### Research and strategies

- Backtests bind frozen datasets, parameters, modeled costs, OOS evidence,
  limitations, and quality status.
- Strategy output is research evidence until it passes data, cost, risk,
  account, paper/shadow, and operator gates.
- Strategy code proposes signals or targets; it cannot import or call broker
  adapters and cannot grant itself authority.

### AI

- Provider, model, agent role, workflow, tool, evidence, and memory identities
  remain separate.
- AI tools are deny-by-default and read-only over persisted evidence.
- Post-decision AI review may read only explicitly selected canonical outcome
  projections bound to the same valuation snapshot and ledger cutoff; it never
  recalculates P/L or turns a reviewed observation into authority.
- Model output is a cited, non-authoritative research artifact. It is not an
  account fact, risk decision, capital authorization, OMS transition, broker
  instruction, or permission.
- In formula research, models may propose hypotheses, but only an allowlisted
  DSL and the canonical backtest engine calculate results. Human selection and
  final disposition remain mandatory; no formula draft registers a production
  strategy or gains trading authority.
- External evidence export requires a separate explicit human decision and
  excludes credentials and authority state.

### Execution

- Real-money execution is disabled by default.
- Manual per-order confirmation is the default live-like mode.
- Any future bounded session is explicit, short-lived, limited by account,
  strategy, symbol, capital, turnover, loss, drawdown, rate, time, data,
  gateway, and reconciliation gates.
- A session may pause or become narrower automatically; it cannot renew,
  resume, widen, or scale itself.
- Kill switch, stale data, account mismatch, connector degradation, unresolved
  reconciliation, policy expiry, or exhausted limits block new submissions.

## Success Criteria

Karkinos succeeds when it provides:

- reproducible and explainable research rather than headline backtest returns;
- a useful daily plan that includes no-action and review-required outcomes;
- a measurable share of daily decisions that are data-complete, risk-checked,
  benchmark-aware, journaled, and later reviewable;
- consistent portfolio and performance facts across every product surface;
- reliable paper/shadow and operator runbooks;
- explicit evidence and recovery for every live-like order state;
- bounded authority that can always be inspected, paused, reduced, expired, or
  revoked;
- a local development and operations experience a serious individual can run,
  understand, and audit.

Success does not mean guaranteed profit. The engineering objective is to
improve discipline, evidence quality, risk containment, execution fidelity, and
learning after costs.

## Non-Goals

- Investment-advice or guaranteed-return claims.
- Permanently authorized, unattended full-account trading.
- Strategy-direct or AI-directed broker access.
- Broker-password storage in Karkinos.
- Automatic capital expansion.
- High-frequency or low-latency trading.
- Institutional multi-account OMS or a community strategy marketplace as a
  near-term target.

## Documentation Ownership

This file owns only the North Star, product promise, durable boundaries, and
long-term success criteria. Current priorities belong in
[ROADMAP.md](ROADMAP.md), stable design in
[ARCHITECTURE.md](ARCHITECTURE.md), completed evidence in
[IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md), and operator or data contracts
in topic documents.
