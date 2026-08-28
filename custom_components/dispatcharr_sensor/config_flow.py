"""Config flow for Dispatcharr Sensor integration."""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import (
    DOMAIN,
    CONF_URL,
    CONF_API_KEY,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ENABLE_EPG,
    DEFAULT_ENABLE_EPG,
    CONF_ENABLE_REALTIME,
    DEFAULT_ENABLE_REALTIME,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _obtain_api_key(hass, url: str, username: str, password: str) -> str:
    """Log in with username/password and mint a permanent API key for REST calls."""
    session = async_get_clientsession(hass)

    async with session.post(
        f"{url}/api/accounts/token/",
        json={"username": username, "password": password},
    ) as response:
        response.raise_for_status()
        tokens = await response.json()
        access_token = tokens.get("access")
        if not access_token:
            raise ValueError("no_access_token")

    async with session.post(
        f"{url}/api/accounts/api-keys/generate/",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as response:
        response.raise_for_status()
        data = await response.json()
        api_key = data.get("key")
        if not api_key:
            raise ValueError("no_api_key")
        return api_key


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Dispatcharr Sensor."""

    VERSION = 2

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                api_key = await _obtain_api_key(self.hass, url, username, password)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to obtain a Dispatcharr API key")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="Dispatcharr",
                    data={
                        CONF_URL: url,
                        CONF_API_KEY: api_key,
                        # Kept (HA-encrypted) so the websocket link can silently
                        # re-authenticate; Dispatcharr's websocket only accepts
                        # short-lived JWTs, not the permanent API key above.
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication when the stored API key stops working."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for fresh credentials and mint a new API key."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        url = self._reauth_entry.data[CONF_URL]

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                api_key = await _obtain_api_key(self.hass, url, username, password)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to obtain a Dispatcharr API key")
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_API_KEY: api_key,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "OptionsFlow":
        """Get the options flow for this handler."""
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Dispatcharr Sensor integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_EPG,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_EPG, DEFAULT_ENABLE_EPG
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_ENABLE_REALTIME,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_REALTIME, DEFAULT_ENABLE_REALTIME
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    ),
                }
            ),
        )
