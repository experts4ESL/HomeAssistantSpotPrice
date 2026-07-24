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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OekoSpotConfigEntry
from .api import (
    PriceDataset,
    PricePlateau,
    best_price_cycle,
    chart_points,
    cheapest_window,
    day_statistics,
    find_price_plateaus,
    plateau_to_dict,
    price_level,
)
from .const import (
    CONF_HANDLING_FEE,
    CONF_HIGH_PLATEAU_PERCENTILE,
    CONF_LOW_PLATEAU_PERCENTILE,
    CONF_MIN_PLATEAU_MINUTES,
    DEFAULT_HANDLING_FEE,
    DEFAULT_HIGH_PLATEAU_PERCENTILE,
    DEFAULT_LOW_PLATEAU_PERCENTILE,
    DEFAULT_MIN_PLATEAU_MINUTES,
    DOMAIN,
)
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
        key="next_low_plateau",
        translation_key="next_low_plateau",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, now, tz: None,
    ),
    OekoSpotSensorDescription(
        key="next_high_plateau",
        translation_key="next_high_plateau",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, now, tz: None,
    ),
    OekoSpotSensorDescription(
        key="best_price_cycle",
        translation_key="best_price_cycle",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda data, now, tz: None,
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

    @property
    def native_value(self):
        """Return the calculated state."""
        now = datetime.now(UTC)
        timezone = ZoneInfo(self.hass.config.time_zone)
        if self.entity_description.key in {
            "next_low_plateau",
            "next_high_plateau",
        }:
            kind = (
                "low"
                if self.entity_description.key == "next_low_plateau"
                else "high"
            )
            plateau = self._next_plateau(kind, now, timezone)
            return plateau.start if plateau else None
        if self.entity_description.key == "best_price_cycle":
            cycle = self._best_cycle(now, timezone)
            return round(cycle.gross_spread, 4) if cycle else None
        return self.entity_description.value_fn(self.coordinator.data, now, timezone)

    def _plateaus(
        self, kind: str, day, timezone: ZoneInfo
    ) -> tuple[PricePlateau, ...]:
        percentile_key = (
            CONF_LOW_PLATEAU_PERCENTILE
            if kind == "low"
            else CONF_HIGH_PLATEAU_PERCENTILE
        )
        percentile_default = (
            DEFAULT_LOW_PLATEAU_PERCENTILE
            if kind == "low"
            else DEFAULT_HIGH_PLATEAU_PERCENTILE
        )
        return find_price_plateaus(
            self.coordinator.data,
            day,
            timezone,
            kind=kind,
            percentile=self._entry.options.get(
                percentile_key, percentile_default
            )
            / 100,
            minimum_minutes=self._entry.options.get(
                CONF_MIN_PLATEAU_MINUTES, DEFAULT_MIN_PLATEAU_MINUTES
            ),
        )

    def _next_plateau(
        self, kind: str, now: datetime, timezone: ZoneInfo
    ) -> PricePlateau | None:
        today = now.astimezone(timezone).date()
        candidates = (
            *self._plateaus(kind, today, timezone),
            *self._plateaus(kind, today + timedelta(days=1), timezone),
        )
        future = [
            item for item in candidates if item.end.astimezone(UTC) > now
        ]
        return min(future, key=lambda item: item.start.astimezone(UTC), default=None)

    def _best_cycle(self, now: datetime, timezone: ZoneInfo):
        today = now.astimezone(timezone).date()
        low = (
            *self._plateaus("low", today, timezone),
            *self._plateaus("low", today + timedelta(days=1), timezone),
        )
        high = (
            *self._plateaus("high", today, timezone),
            *self._plateaus("high", today + timedelta(days=1), timezone),
        )
        return best_price_cycle(low, high)

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
            low_today = self._plateaus("low", today, timezone)
            high_today = self._plateaus("high", today, timezone)
            low_tomorrow = self._plateaus("low", tomorrow, timezone)
            high_tomorrow = self._plateaus("high", tomorrow, timezone)
            cycle = best_price_cycle(
                (*low_today, *low_tomorrow),
                (*high_today, *high_tomorrow),
            )
            return {
                "unit": "ct/kWh",
                "source": "smartENERGY",
                "prices_today": chart_points(data, today, timezone),
                "prices_tomorrow": chart_points(data, tomorrow, timezone),
                "low_plateaus_today": [
                    plateau_to_dict(item) for item in low_today
                ],
                "high_plateaus_today": [
                    plateau_to_dict(item) for item in high_today
                ],
                "low_plateaus_tomorrow": [
                    plateau_to_dict(item) for item in low_tomorrow
                ],
                "high_plateaus_tomorrow": [
                    plateau_to_dict(item) for item in high_tomorrow
                ],
                "best_price_cycle": (
                    {
                        "charge": plateau_to_dict(cycle.charge),
                        "discharge": plateau_to_dict(cycle.discharge),
                        "gross_spread": round(cycle.gross_spread, 4),
                    }
                    if cycle
                    else None
                ),
                "tomorrow_available": data.tomorrow_complete,
            }
        if self.entity_description.key in {
            "next_low_plateau",
            "next_high_plateau",
        }:
            kind = (
                "low"
                if self.entity_description.key == "next_low_plateau"
                else "high"
            )
            plateau = self._next_plateau(kind, now, timezone)
            if plateau is None:
                return None
            attributes = plateau_to_dict(plateau)
            attributes["active"] = (
                plateau.start.astimezone(UTC)
                <= now
                < plateau.end.astimezone(UTC)
            )
            return attributes
        if self.entity_description.key == "best_price_cycle":
            cycle = self._best_cycle(now, timezone)
            if cycle is None:
                return None
            return {
                "charge": plateau_to_dict(cycle.charge),
                "discharge": plateau_to_dict(cycle.discharge),
                "gross_spread": round(cycle.gross_spread, 4),
                "price_only": True,
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
