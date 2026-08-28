"""The Dispatcharr integration."""
import asyncio
import logging
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_ENABLE_EPG,
    CONF_ENABLE_REALTIME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_ENABLE_EPG,
    DEFAULT_ENABLE_REALTIME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    M3U_UPDATE_INTERVAL,
)
from .config_flow import _obtain_api_key

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.MEDIA_PLAYER]

# Websocket events that mean "active stream/channel state changed, refresh now".
STREAM_EVENT_TYPES = {"channel_stats", "vod_stats", "timeshift_stats"}
# Websocket events that mean "notifications or recordings changed, refresh the aux data".
AUX_EVENT_TYPES = {
    "system_notification",
    "notification_dismissed",
    "recording_started",
    "recording_ended",
    "recordings_refreshed",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dispatcharr from a config entry."""
    coordinator = DispatcharrDataUpdateCoordinator(hass, entry)
    aux_coordinator = DispatcharrAuxDataCoordinator(hass, entry, coordinator)
    coordinator.aux_coordinator = aux_coordinator

    if coordinator.epg_enabled:
        await coordinator.async_populate_channel_map()
    await coordinator.async_config_entry_first_refresh()
    await aux_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    coordinator.async_start_realtime()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_stop_realtime)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change (e.g. EPG toggled)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old host/port/username/password entry to url + API key."""
    if entry.version > 1:
        return True

    old_data = entry.data
    protocol = "https" if old_data.get("ssl", False) else "http"
    url = f"{protocol}://{old_data['host']}:{old_data['port']}"
    username = old_data["username"]
    password = old_data["password"]

    try:
        api_key = await _obtain_api_key(hass, url, username, password)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Migration failed, could not obtain an API key: %s", err)
        return False

    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_URL: url,
            CONF_API_KEY: api_key,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
        },
        version=2,
    )
    _LOGGER.info("Successfully migrated Dispatcharr entry to API key authentication")
    return True


def _is_dismissed(value) -> bool:
    """Normalize the `is_dismissed` field, which the API documents as a string.

    Treat missing/empty/"false"-ish values as not dismissed, anything else
    (True, or a populated timestamp string) as dismissed.
    """
    if isinstance(value, bool):
        return value
    if value in (None, "", "false", "False", "0", 0):
        return False
    return True


def _to_websocket_url(base_url: str, token: str) -> str:
    """Turn the http(s) base URL into a ws(s) URL for the realtime endpoint."""
    parts = urlsplit(base_url)
    ws_scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((ws_scheme, parts.netloc, "/ws/", f"token={token}", ""))


class DispatcharrDataUpdateCoordinator(DataUpdateCoordinator):
    """Manages fetching and coordinating Dispatcharr active-stream data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize."""
        self.config_entry = config_entry
        self.websession = async_get_clientsession(hass)
        self.channel_map: dict = {}
        self.logo_map: dict = {}
        self.aux_coordinator: "DispatcharrAuxDataCoordinator | None" = None

        self._jwt_access_token: str | None = None
        self._jwt_refresh_token: str | None = None
        self._jwt_login_lock = asyncio.Lock()
        self._ws_task: asyncio.Task | None = None
        self.websocket_connected = False

        interval_seconds = config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval_seconds),
        )

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls."""
        return self.config_entry.data[CONF_URL]

    @property
    def epg_enabled(self) -> bool:
        """Whether EPG lookups (channel map + now-playing program) are enabled."""
        return self.config_entry.options.get(CONF_ENABLE_EPG, DEFAULT_ENABLE_EPG)

    @property
    def realtime_enabled(self) -> bool:
        """Whether the websocket realtime link should be used."""
        has_credentials = bool(
            self.config_entry.data.get(CONF_USERNAME)
            and self.config_entry.data.get(CONF_PASSWORD)
        )
        return has_credentials and self.config_entry.options.get(
            CONF_ENABLE_REALTIME, DEFAULT_ENABLE_REALTIME
        )

    async def _api_request(self, method: str, url: str, is_json: bool = True, **kwargs):
        """Make an authenticated API request using the stored API key."""
        headers = {"X-API-Key": self.config_entry.data[CONF_API_KEY]}

        try:
            response = await self.websession.request(method, url, headers=headers, **kwargs)
            if response.status == 401:
                raise ConfigEntryAuthFailed(
                    "Dispatcharr rejected the stored API key; it may have been revoked."
                )
            response.raise_for_status()
            return await response.json() if is_json else await response.text()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"API request to {url} failed: {err}") from err

    async def _api_request_paginated(self, url: str) -> list:
        """GET a list endpoint and return all of its items.

        Dispatcharr is inconsistent about pagination: some list endpoints return
        a bare JSON array, others a DRF {count, next, previous, results} page
        object. Handle both rather than trusting the OpenAPI schema, which
        describes several endpoints as paginated that in practice are not.
        """
        results = []
        base_parts = urlsplit(self.base_url)
        while url:
            page = await self._api_request("GET", url)

            if isinstance(page, list):
                results.extend(page)
                break

            results.extend(page.get("results", []))
            next_url = page.get("next")
            if next_url:
                next_parts = urlsplit(next_url)
                # Rebuild against our configured base_url instead of trusting the
                # scheme/host DRF reported, in case a reverse proxy rewrites it.
                next_url = urlunsplit(
                    (base_parts.scheme, base_parts.netloc, next_parts.path, next_parts.query, "")
                )
            url = next_url
        return results

    async def async_populate_channel_map(self):
        """Fetch channels + logos once to build a reliable channel/EPG map.

        Keyed by both the channel's numeric id and its uuid, since it isn't
        documented which one `/proxy/ts/status` reports as `channel_id`.
        """
        _LOGGER.info("Populating Dispatcharr channel map...")
        try:
            channels = await self._api_request_paginated(
                f"{self.base_url}/api/channels/channels/"
            )
            logos = await self._api_request_paginated(
                f"{self.base_url}/api/channels/logos/"
            )
        except UpdateFailed as err:
            raise ConfigEntryNotReady(f"Could not fetch channel list: {err}") from err

        self.logo_map = {
            str(logo["id"]): logo.get("cache_url") or logo.get("url")
            for logo in logos or []
            if logo.get("id") is not None
        }

        channel_map: dict = {}
        for channel in channels or []:
            tvg_id = channel.get("effective_tvg_id") or channel.get("tvg_id")
            details = {
                "uuid": channel.get("uuid"),
                "tvg_id": tvg_id,
                "name": channel.get("effective_name") or channel.get("name"),
                "logo_url": self.logo_map.get(
                    str(channel.get("effective_logo_id") or channel.get("logo_id"))
                ),
            }
            if channel.get("id") is not None:
                channel_map[str(channel["id"])] = details
            if channel.get("uuid"):
                channel_map[str(channel["uuid"])] = details

        self.channel_map = channel_map
        _LOGGER.info("Successfully built channel map with %d channels.", len(channels or []))

    async def async_stop_channel(self, channel_id: str) -> None:
        """Stop a channel's stream for all viewers via the official API."""
        await self._api_request(
            "POST", f"{self.base_url}/proxy/ts/stop/{channel_id}", is_json=False
        )

    async def _async_update_data(self):
        """Update data by fetching from authenticated endpoints."""
        status_data = await self._api_request("GET", f"{self.base_url}/proxy/ts/status")
        active_streams = status_data.get("channels", [])
        if not active_streams:
            return {}

        enriched_streams = {}
        channel_uuids_needed = []
        details_by_stream: dict = {}

        for stream in active_streams:
            stream_uuid = stream.get("channel_id")
            if not stream_uuid:
                continue

            enriched_stream = stream.copy()
            details = self.channel_map.get(str(stream_uuid)) if self.epg_enabled else None

            if details:
                enriched_stream["xmltv_id"] = details["tvg_id"]
                enriched_stream["channel_name"] = details["name"]
                enriched_stream["logo_url"] = details.get("logo_url")
                details_by_stream[stream_uuid] = details
                if details.get("uuid"):
                    channel_uuids_needed.append(details["uuid"])

            enriched_streams[stream_uuid] = enriched_stream

        if self.epg_enabled and channel_uuids_needed:
            try:
                programs = await self._api_request(
                    "POST",
                    f"{self.base_url}/api/epg/current-programs/",
                    json={"channel_uuids": channel_uuids_needed},
                )
            except UpdateFailed as err:
                _LOGGER.debug("Could not fetch current programs: %s", err)
                programs = []

            # Same defensive handling as the GET list endpoints: this may come
            # back as a bare array or wrapped in a DRF page object.
            if isinstance(programs, dict):
                programs = programs.get("results", [])

            programs_by_tvg_id = {
                program["tvg_id"]: program
                for program in (programs or [])
                if program.get("tvg_id")
            }

            for stream_uuid, details in details_by_stream.items():
                program = programs_by_tvg_id.get(details.get("tvg_id"))
                if program:
                    enriched_streams[stream_uuid]["program"] = {
                        "title": program.get("title"),
                        "description": program.get("description"),
                        "start_time": program.get("start_time"),
                        "end_time": program.get("end_time"),
                        "subtitle": program.get("sub_title"),
                    }

        return enriched_streams

    # -- Realtime (websocket) -------------------------------------------------

    def async_start_realtime(self) -> None:
        """Start the background websocket listener, if enabled."""
        if not self.realtime_enabled or self._ws_task is not None:
            return
        self._ws_task = self.hass.async_create_task(
            self._async_websocket_loop(), name=f"{DOMAIN}_websocket"
        )

    async def async_stop_realtime(self) -> None:
        """Stop the background websocket listener."""
        if self._ws_task is not None:
            self._ws_task.cancel()
            self._ws_task = None
        self.websocket_connected = False

    async def _async_ensure_jwt_token(self) -> str:
        """Return a JWT access token valid for a new websocket connection."""
        async with self._jwt_login_lock:
            if self._jwt_refresh_token:
                try:
                    await self._async_refresh_jwt()
                    return self._jwt_access_token
                except aiohttp.ClientError as err:
                    _LOGGER.debug("JWT refresh failed, logging in again: %s", err)

            await self._async_login_jwt()
            return self._jwt_access_token

    async def _async_login_jwt(self) -> None:
        data = self.config_entry.data
        async with self.websession.post(
            f"{self.base_url}/api/accounts/token/",
            json={"username": data[CONF_USERNAME], "password": data[CONF_PASSWORD]},
        ) as response:
            response.raise_for_status()
            tokens = await response.json()
            self._jwt_access_token = tokens["access"]
            self._jwt_refresh_token = tokens.get("refresh")

    async def _async_refresh_jwt(self) -> None:
        async with self.websession.post(
            f"{self.base_url}/api/accounts/token/refresh/",
            json={"refresh": self._jwt_refresh_token},
        ) as response:
            response.raise_for_status()
            tokens = await response.json()
            self._jwt_access_token = tokens["access"]

    async def _async_websocket_loop(self) -> None:
        """Keep a websocket connection open and trigger fast refreshes on events."""
        backoff = 5
        while True:
            try:
                token = await self._async_ensure_jwt_token()
                ws_url = _to_websocket_url(self.base_url, token)
                async with self.websession.ws_connect(ws_url, heartbeat=30) as ws:
                    _LOGGER.info("Dispatcharr websocket connected")
                    self.websocket_connected = True
                    backoff = 5
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_websocket_message(msg.json())
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                self.websocket_connected = False
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Dispatcharr websocket disconnected (%s), retrying in %ss", err, backoff
                )

            self.websocket_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _handle_websocket_message(self, message: dict) -> None:
        data = (message or {}).get("data") or {}
        event_type = data.get("type")
        if not event_type:
            return

        if event_type in STREAM_EVENT_TYPES:
            self.hass.async_create_task(self.async_request_refresh())
        elif event_type in AUX_EVENT_TYPES and self.aux_coordinator is not None:
            self.hass.async_create_task(self.aux_coordinator.async_request_refresh())


class DispatcharrAuxDataCoordinator(DataUpdateCoordinator):
    """Slow-polled coordinator for M3U account status and notifications.

    Reuses the main coordinator's authenticated request helpers instead of
    duplicating the API-key logic.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        main_coordinator: DispatcharrDataUpdateCoordinator,
    ):
        self.config_entry = config_entry
        self._main = main_coordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_aux",
            update_interval=timedelta(seconds=M3U_UPDATE_INTERVAL),
        )

    async def _async_update_data(self):
        accounts = await self._main._api_request_paginated(
            f"{self._main.base_url}/api/m3u/accounts/"
        )

        try:
            notifications = await self._main._api_request_paginated(
                f"{self._main.base_url}/api/core/notifications/"
            )
        except UpdateFailed as err:
            _LOGGER.debug("Could not fetch notifications: %s", err)
            notifications = []

        normalized_notifications = [
            {**n, "is_dismissed": _is_dismissed(n.get("is_dismissed"))}
            for n in (notifications or [])
        ]
        unread = sum(1 for n in normalized_notifications if not n["is_dismissed"])

        return {
            "m3u_accounts": {str(a["id"]): a for a in accounts or [] if a.get("id") is not None},
            "notifications": normalized_notifications,
            "unread_notifications": unread,
        }
