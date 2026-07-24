"""Diagnostics support for Ökostrom Spot Price."""

from homeassistant.core import HomeAssistant

from . import OekoSpotConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OekoSpotConfigEntry
) -> dict:
    """Return non-sensitive metadata without the complete price list."""
    data = entry.runtime_data.coordinator.data
    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "dataset": {
            "tariff": data.tariff,
            "unit": data.unit,
            "interval_minutes": data.interval_minutes,
            "interval_count": len(data.intervals),
            "first_interval": data.intervals[0].start.isoformat(),
            "last_interval": data.intervals[-1].end.isoformat(),
            "fetched_at": data.fetched_at.isoformat(),
            "today_complete": data.today_complete,
            "tomorrow_complete": data.tomorrow_complete,
        },
    }

