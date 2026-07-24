"""Data update coordinator for Ökostrom Spot Price."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OekoSpotError, PriceDataset, SmartEnergyApi
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

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

    async def _async_update_data(self) -> PriceDataset:
        try:
            return await self.api.async_get_prices()
        except OekoSpotError as err:
            raise UpdateFailed(f"Error updating smartENERGY prices: {err}") from err

