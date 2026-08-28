"""Constants for the Dispatcharr Sensor integration."""

DOMAIN = "dispatcharr_sensor"

# List of platforms to support. In this case, just the "sensor" platform.
PLATFORMS = ["sensor"]

CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_ENABLE_EPG = "enable_epg"
DEFAULT_ENABLE_EPG = True

CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 10
MIN_UPDATE_INTERVAL = 2
MAX_UPDATE_INTERVAL = 300

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

CONF_ENABLE_REALTIME = "enable_realtime"
DEFAULT_ENABLE_REALTIME = True

# M3U account status is polled far less often than stream status; it rarely changes.
M3U_UPDATE_INTERVAL = 300