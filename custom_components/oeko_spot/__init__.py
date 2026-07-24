"""Ökostrom Spot Price integration."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmartEnergyApi
from .const import (
    CONF_API_TARIFF,
    CONF_HANDLING_FEE,
    DEFAULT_API_TARIFF,
    DEFAULT_HANDLING_FEE,
    PLATFORMS,
)
from .coordinator import OekoSpotCoordinator


@dataclass
class OekoSpotRuntimeData:
    """Runtime objects associated with a config entry."""

    coordinator: OekoSpotCoordinator


type OekoSpotConfigEntry = ConfigEntry[OekoSpotRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: OekoSpotConfigEntry) -> bool:
    """Set up Ökostrom Spot Price from a config entry."""
    timezone = ZoneInfo(hass.config.time_zone)
    api = SmartEnergyApi(
        async_get_clientsession(hass),
        tariff=entry.data.get(CONF_API_TARIFF, DEFAULT_API_TARIFF),
        timezone=timezone,
        handling_fee=entry.options.get(
            CONF_HANDLING_FEE,
            entry.data.get(CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE),
        ),
    )
    coordinator = OekoSpotCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = OekoSpotRuntimeData(coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OekoSpotConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: OekoSpotConfigEntry
) -> None:
    """Reload after option changes."""
    await hass.config_entries.async_reload(entry.entry_id)

