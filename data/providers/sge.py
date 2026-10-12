"""Shanghai Gold Exchange calls used by the legacy multi-asset adapter."""

from __future__ import annotations


def fetch_sge_gold_daily(ak, retry, *, symbol: str):
    return retry(ak.spot_hist_sge, symbol=symbol)


legacy_gold_daily = fetch_sge_gold_daily


def fetch_sge_gold_spot(ak, retry, *, symbol: str):
    return retry(ak.spot_quotations_sge, symbol=symbol)


legacy_gold_spot = fetch_sge_gold_spot
