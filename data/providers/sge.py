"""Shanghai Gold Exchange calls used by the legacy multi-asset adapter."""

from __future__ import annotations


def fetch_sge_gold_daily(ak, retry, *, symbol: str):
    return retry(ak.spot_hist_sge, symbol=symbol)


def fetch_sge_gold_spot(ak, retry, *, symbol: str):
    return retry(ak.spot_quotations_sge, symbol=symbol)
