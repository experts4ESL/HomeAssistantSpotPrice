"""Data update coordinator for Ökostrom Spot Price."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    OekoSpotError,
    PriceDataset,
    SmartEnergyApi,
    dataset_from_dict,
    dataset_to_dict,
)
from .const import (
    CONF_API_TARIFF,
    CONF_HANDLING_FEE,
    CONF_SCAN_INTERVAL,
    CONF_STALE_AFTER_HOURS,
    DEFAULT_API_TARIFF,
    DEFAULT_HANDLING_FEE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_AFTER_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class OekoSpotCoordinator(DataUpdateCoordinator[PriceDataset]):
    """Coordinate one API request for all entities."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: SmartEnergyApi
    ) -> None:
        interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
            always_update=False,
        )
        self.api = api
        self._entry = entry
        self._timezone = ZoneInfo(hass.config.time_zone)
        self._store: Store[dict] = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}"
        )
        self._stored_data: PriceDataset | None = None

    async def _async_setup(self) -> None:
        """Load the last successful response for offline startup."""
        stored = await self._store.async_load()
        if stored is None:
            return
        try:
            self._stored_data = dataset_from_dict(
                stored,
                expected_tariff=self._entry.data.get(
                    CONF_API_TARIFF, DEFAULT_API_TARIFF
                ),
                timezone=self._timezone,
                handling_fee=Decimal(
                    str(
                        self._entry.options.get(
                            CONF_HANDLING_FEE,
                            self._entry.data.get(
                                CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE
                            ),
                        )
                    )
                ),
                reference_time=datetime.now(UTC),
            )
        except OekoSpotError as err:
            _LOGGER.warning("Ignoring invalid stored smartENERGY data: %s", err)

    async def _async_update_data(self) -> PriceDataset:
        try:
            dataset = await self.api.async_get_prices()
        except OekoSpotError as err:
            if self.data is None and self._stored_data is not None:
                max_age = self._entry.options.get(
                    CONF_STALE_AFTER_HOURS, DEFAULT_STALE_AFTER_HOURS
                )
                age = datetime.now(UTC) - self._stored_data.fetched_at.astimezone(UTC)
                if age <= timedelta(hours=max_age):
                    _LOGGER.warning(
                        "Using stored smartENERGY prices because the API is unavailable"
                    )
                    return self._stored_data
            raise UpdateFailed(f"Error updating smartENERGY prices: {err}") from err
        await self._store.async_save(dataset_to_dict(dataset))
        self._stored_data = dataset
        return dataset
