"""Config and options flows for Ökostrom Spot Price."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OekoSpotConnectionError, OekoSpotError, SmartEnergyApi
from .const import (
    CONF_API_TARIFF,
    CONF_HANDLING_FEE,
    CONF_HIGH_PLATEAU_PERCENTILE,
    CONF_LOW_PLATEAU_PERCENTILE,
    CONF_MIN_PLATEAU_MINUTES,
    CONF_SCAN_INTERVAL,
    CONF_STALE_AFTER_HOURS,
    CONF_TARIFF_NAME,
    DEFAULT_API_TARIFF,
    DEFAULT_HANDLING_FEE,
    DEFAULT_HIGH_PLATEAU_PERCENTILE,
    DEFAULT_LOW_PLATEAU_PERCENTILE,
    DEFAULT_MIN_PLATEAU_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_AFTER_HOURS,
    DEFAULT_TARIFF_NAME,
    DOMAIN,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_TARIFF_NAME,
                default=defaults.get(CONF_TARIFF_NAME, DEFAULT_TARIFF_NAME),
            ): str,
            vol.Required(
                CONF_API_TARIFF,
                default=defaults.get(CONF_API_TARIFF, DEFAULT_API_TARIFF),
            ): str,
            vol.Required(
                CONF_HANDLING_FEE,
                default=defaults.get(CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE),
            ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
        }
    )


def _multiple_of_15(value: int) -> int:
    """Validate quarter-hour based durations."""
    if value % 15:
        raise vol.Invalid("Must be a multiple of 15")
    return value


class OekoSpotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Create the single supported config entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            api = SmartEnergyApi(
                async_get_clientsession(self.hass),
                tariff=user_input[CONF_API_TARIFF],
                timezone=ZoneInfo(self.hass.config.time_zone),
                handling_fee=user_input[CONF_HANDLING_FEE],
            )
            try:
                await api.async_get_prices()
            except OekoSpotConnectionError:
                errors["base"] = "cannot_connect"
            except OekoSpotError:
                errors["base"] = "invalid_data"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_TARIFF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return OekoSpotOptionsFlow()


class OekoSpotOptionsFlow(config_entries.OptionsFlow):
    """Manage mutable integration options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Update settings and reload the entry."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HANDLING_FEE,
                    default=current.get(CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE),
                ): vol.All(vol.Coerce(float), vol.Range(min=-100, max=100)),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
                vol.Required(
                    CONF_STALE_AFTER_HOURS,
                    default=current.get(
                        CONF_STALE_AFTER_HOURS, DEFAULT_STALE_AFTER_HOURS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
                vol.Required(
                    CONF_LOW_PLATEAU_PERCENTILE,
                    default=current.get(
                        CONF_LOW_PLATEAU_PERCENTILE,
                        DEFAULT_LOW_PLATEAU_PERCENTILE,
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=50)),
                vol.Required(
                    CONF_HIGH_PLATEAU_PERCENTILE,
                    default=current.get(
                        CONF_HIGH_PLATEAU_PERCENTILE,
                        DEFAULT_HIGH_PLATEAU_PERCENTILE,
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=50)),
                vol.Required(
                    CONF_MIN_PLATEAU_MINUTES,
                    default=current.get(
                        CONF_MIN_PLATEAU_MINUTES,
                        DEFAULT_MIN_PLATEAU_MINUTES,
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=15, max=360),
                    _multiple_of_15,
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
