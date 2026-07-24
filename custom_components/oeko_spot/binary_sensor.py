"""Binary sensors for Ökostrom Spot Price."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OekoSpotConfigEntry
from .api import find_price_plateaus, plateau_to_dict
from .const import (
    CONF_HIGH_PLATEAU_PERCENTILE,
    CONF_LOW_PLATEAU_PERCENTILE,
    CONF_MIN_PLATEAU_MINUTES,
    DEFAULT_HIGH_PLATEAU_PERCENTILE,
    DEFAULT_LOW_PLATEAU_PERCENTILE,
    DEFAULT_MIN_PLATEAU_MINUTES,
)
from .entity import OekoSpotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OekoSpotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up availability sensor."""
    async_add_entities(
        [
            OekoSpotTomorrowSensor(entry.runtime_data.coordinator, entry),
            OekoSpotPlateauActiveSensor(
                entry.runtime_data.coordinator, entry, "low"
            ),
            OekoSpotPlateauActiveSensor(
                entry.runtime_data.coordinator, entry, "high"
            ),
        ]
    )


class OekoSpotTomorrowSensor(OekoSpotEntity, BinarySensorEntity):
    """Whether a complete next-day price set is available."""

    _attr_translation_key = "tomorrow_available"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tomorrow_available"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.tomorrow_complete


class OekoSpotPlateauActiveSensor(OekoSpotEntity, BinarySensorEntity):
    """Whether a configured low- or high-price plateau is active."""

    def __init__(self, coordinator, entry, kind: str) -> None:
        super().__init__(coordinator, entry)
        self._kind = kind
        self._attr_translation_key = f"{kind}_plateau_active"
        self._attr_unique_id = f"{entry.entry_id}_{kind}_plateau_active"

    def _active_plateau(self):
        now = datetime.now(UTC)
        timezone = ZoneInfo(self.hass.config.time_zone)
        percentile_key = (
            CONF_LOW_PLATEAU_PERCENTILE
            if self._kind == "low"
            else CONF_HIGH_PLATEAU_PERCENTILE
        )
        percentile_default = (
            DEFAULT_LOW_PLATEAU_PERCENTILE
            if self._kind == "low"
            else DEFAULT_HIGH_PLATEAU_PERCENTILE
        )
        plateaus = find_price_plateaus(
            self.coordinator.data,
            now.astimezone(timezone).date(),
            timezone,
            kind=self._kind,
            percentile=self._entry.options.get(
                percentile_key, percentile_default
            )
            / 100,
            minimum_minutes=self._entry.options.get(
                CONF_MIN_PLATEAU_MINUTES, DEFAULT_MIN_PLATEAU_MINUTES
            ),
        )
        return next(
            (
                item
                for item in plateaus
                if item.start.astimezone(UTC)
                <= now
                < item.end.astimezone(UTC)
            ),
            None,
        )

    @property
    def is_on(self) -> bool:
        return self._active_plateau() is not None

    @property
    def extra_state_attributes(self):
        plateau = self._active_plateau()
        return plateau_to_dict(plateau) if plateau else None
