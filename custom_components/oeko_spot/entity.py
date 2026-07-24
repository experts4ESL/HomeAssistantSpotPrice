"""Shared entity base for Ökostrom Spot Price."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OekoSpotConfigEntry
from .const import (
    CONF_STALE_AFTER_HOURS,
    DEFAULT_STALE_AFTER_HOURS,
    DOMAIN,
    NAME,
)
from .coordinator import OekoSpotCoordinator


class OekoSpotEntity(CoordinatorEntity[OekoSpotCoordinator]):
    """Base entity linked to the common virtual device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OekoSpotCoordinator, entry: OekoSpotConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Custom Integration",
            model="smartENERGY EPEX SPOT AT Data Source",
        )

    @property
    def available(self) -> bool:
        """Keep last valid values until the configured age limit."""
        if self.coordinator.data is None:
            return False
        max_age = self._entry.options.get(
            CONF_STALE_AFTER_HOURS, DEFAULT_STALE_AFTER_HOURS
        )
        age = datetime.now(UTC) - self.coordinator.data.fetched_at.astimezone(
            UTC
        )
        return age.total_seconds() <= max_age * 3600

