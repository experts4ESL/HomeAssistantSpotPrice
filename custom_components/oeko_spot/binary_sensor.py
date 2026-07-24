"""Binary sensors for Ökostrom Spot Price."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OekoSpotConfigEntry
from .entity import OekoSpotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OekoSpotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up availability sensor."""
    async_add_entities(
        [OekoSpotTomorrowSensor(entry.runtime_data.coordinator, entry)]
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

