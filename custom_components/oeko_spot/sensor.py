"""Sensor entities for Ökostrom Spot Price."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OekoSpotConfigEntry
from .api import PriceDataset, cheapest_window, day_statistics, price_level
from .const import CONF_HANDLING_FEE, DEFAULT_HANDLING_FEE
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
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_current,
    ),
    OekoSpotSensorDescription(
        key="epex_price",
        translation_key="epex_price",
        native_unit_of_measurement="ct/kWh",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_epex,
    ),
    OekoSpotSensorDescription(
        key="next_price",
        translation_key="next_price",
        native_unit_of_measurement="ct/kWh",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_next,
    ),
    *(
        OekoSpotSensorDescription(
            key=key,
            translation_key=key,
            native_unit_of_measurement="ct/kWh",
            device_class=SensorDeviceClass.MONETARY,
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

    @property
    def native_value(self):
        """Return the calculated state."""
        now = datetime.now(self.coordinator.data.fetched_at.tzinfo)
        timezone = ZoneInfo(self.hass.config.time_zone)
        return self.entity_description.value_fn(self.coordinator.data, now, timezone)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return compact metadata or window details."""
        data = self.coordinator.data
        timezone = ZoneInfo(self.hass.config.time_zone)
        now = datetime.now(data.fetched_at.tzinfo)
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
                    (now - data.fetched_at).total_seconds() / 60, 1
                ),
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
