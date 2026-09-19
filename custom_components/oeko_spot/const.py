"""Constants for the Ökostrom Spot Price integration."""

from datetime import timedelta

DOMAIN = "oeko_spot"
NAME = "Ökostrom Spot Price"

API_URL = "https://apis.smartenergy.at/market/v1/price"
DEFAULT_TARIFF_NAME = "oeko Spot+"
DEFAULT_API_TARIFF = "EPEXSPOTAT"
DEFAULT_HANDLING_FEE = 1.8
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_STALE_AFTER_HOURS = 30
DEFAULT_LOW_PLATEAU_PERCENTILE = 25
DEFAULT_HIGH_PLATEAU_PERCENTILE = 25
DEFAULT_MIN_PLATEAU_MINUTES = 60
DEFAULT_FAST_CHARGE_WINDOW_MINUTES = 120
DEFAULT_SLOW_CHARGE_WINDOW_MINUTES = 300
DEFAULT_DISCHARGE_WINDOW_MINUTES = 180
DEFAULT_ROUND_TRIP_EFFICIENCY = 85
DEFAULT_MINIMUM_NET_SAVINGS = 3.0

CONF_TARIFF_NAME = "tariff_name"
CONF_API_TARIFF = "api_tariff"
CONF_HANDLING_FEE = "handling_fee"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_AFTER_HOURS = "stale_after_hours"
CONF_LOW_PLATEAU_PERCENTILE = "low_plateau_percentile"
CONF_HIGH_PLATEAU_PERCENTILE = "high_plateau_percentile"
CONF_MIN_PLATEAU_MINUTES = "minimum_plateau_minutes"
CONF_FAST_CHARGE_WINDOW_MINUTES = "fast_charge_window_minutes"
CONF_SLOW_CHARGE_WINDOW_MINUTES = "slow_charge_window_minutes"
CONF_DISCHARGE_WINDOW_MINUTES = "discharge_window_minutes"
CONF_ROUND_TRIP_EFFICIENCY = "round_trip_efficiency"
CONF_MINIMUM_NET_SAVINGS = "minimum_net_savings"

PLATFORMS = ["sensor", "binary_sensor"]
REQUEST_TIMEOUT = 15
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL)
