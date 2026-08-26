"""Reference Data database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.contracts.market_calendar import (
    MarketCalendarAutomationPublication,
    MarketCalendarVerificationCommand,
)
from server.persistence.facades.base import DatabaseRepositoryAccess


class ReferenceDataDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Market Calendar Snapshots ----------

    def upsert_market_calendar_snapshot_sync(self, snapshot: Any) -> dict[str, Any]:
        """Persist a provider-normalized market calendar snapshot."""
        return self._market_calendar.upsert_snapshot(snapshot)

    def get_market_calendar_snapshot_sync(
        self,
        *,
        exchange: str,
        year: int,
    ) -> dict[str, Any] | None:
        """Fetch the latest stored market calendar snapshot for an exchange/year."""
        return self._market_calendar.get_snapshot(exchange=exchange, year=year)

    def update_market_calendar_verification_sync(
        self,
        *,
        exchange: str,
        year: int,
        source_fingerprint: str,
        verification_status: str,
        official_source_url: str | None = None,
        official_source_fingerprint: str | None = None,
        verified_by: str | None = None,
        review_notes: str | None = None,
        day_labels: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Attach manual official-notice verification metadata to a snapshot."""
        return self._market_calendar.update_verification(
            MarketCalendarVerificationCommand(
                exchange=exchange,
                year=year,
                source_fingerprint=source_fingerprint,
                verification_status=verification_status,
                official_source_url=official_source_url,
                official_source_fingerprint=official_source_fingerprint,
                verified_by=verified_by,
                review_notes=review_notes,
                day_labels=day_labels or {},
            )
        )

    def publish_market_calendar_automation_sync(
        self,
        command: MarketCalendarAutomationPublication,
    ) -> dict[str, Any]:
        """Atomically publish calendar evidence and its terminal audit run."""

        return self._market_calendar_publication.publish_sync(command)

    # ---------- Watchlist Assets ----------

    def upsert_watchlist_asset_sync(
        self,
        *,
        symbol: str,
        asset_class: str = "stock",
        display_name: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any] | None:
        """Upsert a user-tracked asset into the persistent watchlist."""
        return self._watchlist.upsert_asset(
            symbol=symbol,
            asset_class=asset_class,
            display_name=display_name,
            source=source,
        )

    def list_watchlist_assets_sync(self) -> list[dict[str, Any]]:
        """List persistent watchlist assets in user insertion order."""
        return self._watchlist.list_assets()

    def delete_watchlist_asset_sync(self, symbol: str) -> bool:
        """Remove a user-tracked asset from the persistent watchlist."""
        return self._watchlist.delete_asset(symbol)

    def seed_watchlist_assets_from_config_sync(self, assets: Any) -> int:
        """Migrate legacy config assets into the persistent watchlist."""
        return self._watchlist.seed_from_config(assets)

    # ---------- Instrument Metadata ----------

    def upsert_instrument_metadata_sync(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        display_name: str,
        provider_symbol: str | None = None,
        exchange: str | None = None,
        market: str | None = None,
        provider_name: str | None = None,
        source: str = "provider",
        fetched_at: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert local instrument identity metadata."""
        return self._instrument_metadata.upsert_metadata(
            symbol=symbol,
            asset_type=asset_type,
            display_name=display_name,
            provider_symbol=provider_symbol,
            exchange=exchange,
            market=market,
            provider_name=provider_name,
            source=source,
            fetched_at=fetched_at,
            metadata=metadata,
        )

    def get_instrument_metadata_sync(
        self, symbol: str, asset_type: str | None = None
    ) -> dict[str, Any] | None:
        """Read local instrument identity metadata."""
        return self._instrument_metadata.get_metadata(symbol, asset_type)

    def list_instrument_metadata_sync(self) -> list[dict[str, Any]]:
        """List local instrument identities newest first."""
        return self._instrument_metadata.list_metadata()
