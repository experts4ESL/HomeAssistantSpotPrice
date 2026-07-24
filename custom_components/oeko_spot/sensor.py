"""Sensor entities for Ökostrom Spot Price."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time

from . import OekoSpotConfigEntry
from .api import (
    PriceDataset,
    chart_points,
    cheapest_window,
    day_statistics,
    price_level,
)
from .const import CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE, DOMAIN
from .entity import OekoSpotEntity

PriceValue = Callable[[PriceDataset, datetime, ZoneInfo], Any]


@dataclass(frozen=True, kw_only=True)
class OekoSpotSensorDescription(SensorEntityDescription):
    """Sensor description with a value function."""

    value_fn: PriceValue


def _current(data: PriceDataset, now: datetime, _: ZoneInfo):
    item = data.current(now)
    return float(item.tariff_price_ct_kwh) if item else None


def _epex(data: PriceDataset, now: datetime, _: ZoneInfo):
    item = data.current(now)
    return float(item.market_price_ct_kwh) if item else None


def _next(data: PriceDataset, now: datetime, _: ZoneInfo):
    item = data.next_after(now)
    return float(item.tariff_price_ct_kwh) if item else None


def _stat(index: int) -> PriceValue:
    return lambda data, now, tz: day_statistics(
        data, now.astimezone(tz).date(), tz
    )[index]


def _window(minutes: int) -> PriceValue:
    return lambda data, now, tz: (
        result.start
        if (
            result := cheapest_window(
                data, now.astimezone(tz).date(), tz, minutes
            )
        )
        else None
    )


SENSORS = (
    OekoSpotSensorDescription(
        key="current_price",
        translation_key="current_price",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_current,
    ),
    OekoSpotSensorDescription(
        key="epex_price",
        translation_key="epex_price",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_epex,
    ),
    OekoSpotSensorDescription(
        key="next_price",
        translation_key="next_price",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_next,
    ),
    *(
        OekoSpotSensorDescription(
            key=key,
            translation_key=key,
            native_unit_of_measurement="ct/kWh",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=3,
            value_fn=_stat(index),
        )
        for index, key in enumerate(("daily_min", "daily_max", "daily_average"))
    ),
    OekoSpotSensorDescription(
        key="cheapest_1_hour",
        translation_key="cheapest_1_hour",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window(60),
    ),
    OekoSpotSensorDescription(
        key="cheapest_2_hours",
        translation_key="cheapest_2_hours",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window(120),
    ),
    OekoSpotSensorDescription(
        key="price_chart",
        translation_key="price_chart",
        value_fn=lambda data, now, tz: now.astimezone(tz).date().isoformat(),
    ),
    OekoSpotSensorDescription(
        key="price_level",
        translation_key="price_level",
        device_class=SensorDeviceClass.ENUM,
        options=["very_low", "low", "normal", "high", "very_high"],
        value_fn=price_level,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OekoSpotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    async_add_entities(
        OekoSpotSensor(entry.runtime_data.coordinator, entry, description)
        for description in SENSORS
    )


class OekoSpotSensor(OekoSpotEntity, SensorEntity):
    """A calculated spot-price sensor."""

    entity_description: OekoSpotSensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        if description.key == "price_chart":
            self._attr_suggested_object_id = f"{DOMAIN}_price_chart"
        self._unsub_interval = None

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
    def native_value(self):
        """Return the calculated state."""
        now = datetime.now(UTC)
        timezone = ZoneInfo(self.hass.config.time_zone)
        return self.entity_description.value_fn(self.coordinator.data, now, timezone)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return compact metadata or window details."""
        data = self.coordinator.data
        timezone = ZoneInfo(self.hass.config.time_zone)
        now = datetime.now(UTC)
        if self.entity_description.key == "current_price":
            current = data.current(now)
            if current is None:
                return None
            return {
                "epex_price": float(current.market_price_ct_kwh),
                "handling_fee": self._entry.options.get(
                    CONF_HANDLING_FEE,
                    self._entry.data.get(CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE),
                ),
                "interval_start": current.start.isoformat(),
                "interval_end": current.end.isoformat(),
                "currency": "EUR",
                "source": "smartENERGY",
                "data_timestamp": data.fetched_at.isoformat(),
                "tomorrow_available": data.tomorrow_complete,
                "data_age_minutes": round(
                    (
                        now - data.fetched_at.astimezone(UTC)
                    ).total_seconds()
                    / 60,
                    1,
                ),
            }
        if self.entity_description.key == "price_chart":
            today = now.astimezone(timezone).date()
            tomorrow = today + timedelta(days=1)
            return {
                "unit": "ct/kWh",
                "source": "smartENERGY",
                "prices_today": chart_points(data, today, timezone),
                "prices_tomorrow": chart_points(data, tomorrow, timezone),
                "tomorrow_available": data.tomorrow_complete,
            }
        minutes = {"cheapest_1_hour": 60, "cheapest_2_hours": 120}.get(
            self.entity_description.key
        )
        if minutes:
            window = cheapest_window(
                data, now.astimezone(timezone).date(), timezone, minutes
            )
            if window:
                return {
                    "end": window.end.isoformat(),
                    "average_price": round(window.average, 4),
                    "sum": round(window.total, 4),
                    "rank": window.rank,
                }
        return None
