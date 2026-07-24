"""Shared entity base for Ökostrom Spot Price."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
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
        self._unsub_interval = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Custom Integration",
            model="smartENERGY EPEX SPOT AT Data Source",
        )

    async def async_added_to_hass(self) -> None:
        """Schedule state recalculation exactly at each interval boundary."""
        await super().async_added_to_hass()
        self._schedule_next_interval()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the interval-boundary listener."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        await super().async_will_remove_from_hass()

    @callback
    def _schedule_next_interval(self) -> None:
        """Schedule the next quarter-hour state update."""
        now = datetime.now(UTC)
        seconds = self.coordinator.data.interval_minutes * 60
        next_timestamp = (int(now.timestamp()) // seconds + 1) * seconds
        next_boundary = datetime.fromtimestamp(next_timestamp, UTC)
        self._unsub_interval = async_track_point_in_utc_time(
            self.hass, self._handle_interval_boundary, next_boundary
        )

    @callback
    def _handle_interval_boundary(self, now: datetime) -> None:
        """Write a new state without performing another API request."""
        self._unsub_interval = None
        self.async_write_ha_state()
        self._schedule_next_interval()

    @property
    def available(self) -> bool:
        """Keep last valid values until the configured age limit."""
        if self.coordinator.data is None:
            return False
        max_age = self._entry.options.get(
            CONF_STALE_AFTER_HOURS, DEFAULT_STALE_AFTER_HOURS
        )
        age = datetime.now(UTC) - self.coordinator.data.fetched_at.astimezone(UTC)
        return age.total_seconds() <= max_age * 3600
