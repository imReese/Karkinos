"""Stock daily receipt identity and read compatibility for signed historical receipts."""

from collections.abc import Mapping

CANONICAL_STOCK_BAR_UNITS = {"volume": "shares", "amount": "CNY"}
MARKET_DAILY_RECEIPT = "karkinos.market_daily_ingestion_receipt"
STOCK_BAR_STORAGE = "sqlite_market_bars:stock"
# Exact labels in previously signed receipts. Writers use the stable identity above.
_UNTYPED_RECEIPT = "karkinos.market_daily_ingestion_receipt.v1"
_PROVIDER_UNIT_RECEIPT = "karkinos.market_daily_ingestion_receipt.v2"
_SHARE_RECEIPT = "karkinos.market_daily_ingestion_receipt.v3"
_SOURCE_VOLUME_RECEIPT = "karkinos.market_daily_ingestion_receipt.v4"
_STORAGE_BY_RECEIPT = {
    MARKET_DAILY_RECEIPT: STOCK_BAR_STORAGE,
    _UNTYPED_RECEIPT: "sqlite_market_bars",
    _PROVIDER_UNIT_RECEIPT: "sqlite_market_bars_v2:stock",
    _SHARE_RECEIPT: "sqlite_market_bars_v2:stock",
    _SOURCE_VOLUME_RECEIPT: "sqlite_market_bars_v2:stock+reported_volume",
}


def stock_receipt_uses_provider_units(receipt: Mapping[str, object]) -> bool:
    return receipt.get("schema_version") in (_UNTYPED_RECEIPT, _PROVIDER_UNIT_RECEIPT)


def is_supported_stock_receipt_identity(receipt: Mapping[str, object]) -> bool:
    identity = str(receipt.get("schema_version") or "")
    authority = _STORAGE_BY_RECEIPT.get(identity)
    if authority is None or receipt.get("storage_authority") != authority:
        return False
    with_volume = "source_volumes" in receipt
    if with_volume != ("scoped_receipt_fingerprints" in receipt):
        return False
    if with_volume and (
        identity not in (MARKET_DAILY_RECEIPT, _SOURCE_VOLUME_RECEIPT)
        or receipt.get("provider_name") != "tushare"
        or "scope_type" in receipt
    ):
        return False
    if identity == _SOURCE_VOLUME_RECEIPT and not with_volume:
        return False
    return stock_receipt_uses_provider_units(receipt) or (
        receipt.get("units") == CANONICAL_STOCK_BAR_UNITS
        and receipt.get("price_basis") == "unadjusted"
    )
