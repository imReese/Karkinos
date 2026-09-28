"""Sina upstream calls used by the legacy multi-asset adapter."""

from __future__ import annotations

from data.providers.akshare_sdk import provider_network_env


def legacy_index_spot(ak):
    with provider_network_env():
        return ak.stock_zh_index_spot_sina()


def legacy_bond_daily(ak, retry, *, symbol: str):
    return retry(ak.bond_zh_hs_daily, symbol=symbol)


def legacy_bond_spot(ak, retry):
    return retry(ak.bond_zh_hs_spot)


def legacy_fund_estimate(*, fund_code: str):
    import requests

    url = (
        "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/"
        "FdFundService.getEstimateNetworthPic"
    )
    with provider_network_env():
        response = requests.get(url, params={"symbol": fund_code}, timeout=3)
    response.raise_for_status()
    return response.json()
