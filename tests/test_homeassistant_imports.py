"""Smoke tests against the installed Home Assistant release."""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.oeko_spot import (
    binary_sensor,
    config_flow,
    coordinator,
    diagnostics,
    sensor,
)


def test_all_homeassistant_modules_import() -> None:
    """Importing every platform must succeed against current Home Assistant."""
    assert config_flow.OekoSpotConfigFlow.VERSION == 1
    assert coordinator.OekoSpotCoordinator
    assert binary_sensor.OekoSpotTomorrowSensor
    assert diagnostics.async_get_config_entry_diagnostics


def test_price_sensor_metadata_is_valid() -> None:
    """Price-per-energy sensors must not claim to be currency amounts."""
    price_descriptions = sensor.SENSORS[:6]
    assert all(
        description.device_class is not SensorDeviceClass.MONETARY
        for description in price_descriptions
    )
    assert all(
        description.state_class is SensorStateClass.MEASUREMENT
        for description in price_descriptions
    )

