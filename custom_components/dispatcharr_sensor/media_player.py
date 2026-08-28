"""Media Player platform for Dispatcharr."""
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import PlatformNotReady

from .const import DOMAIN
from . import DispatcharrDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media_player platform from a ConfigEntry."""
    try:
        coordinator = hass.data[DOMAIN][config_entry.entry_id]
    except KeyError:
        raise PlatformNotReady(f"Coordinator not found for entry {config_entry.entry_id}")

    _cleanup_stale_entities(hass, coordinator)
    DispatcharrStreamManager(coordinator, async_add_entities)


@callback
def _cleanup_stale_entities(
    hass: HomeAssistant, coordinator: DispatcharrDataUpdateCoordinator
) -> None:
    """Drop media players left behind by streams that are no longer running.

    The manager only tracks streams it saw during this session, so leftovers
    from a previous run (or from before entity removal was implemented) would
    otherwise sit in the UI as "unavailable" indefinitely.
    """
    registry = er.async_get(hass)
    entry_id = coordinator.config_entry.entry_id
    active_unique_ids = {f"{entry_id}_{stream_id}" for stream_id in (coordinator.data or {})}

    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.domain != "media_player":
            continue
        if entity.unique_id not in active_unique_ids:
            _LOGGER.debug("Removing stale media player %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


class DispatcharrStreamManager:
    """Manages the creation and removal of media_player entities."""
    def __init__(self, coordinator: DispatcharrDataUpdateCoordinator, async_add_entities: AddEntitiesCallback):
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._known_stream_ids = set()
        self._coordinator.async_add_listener(self._update_entities)
        self._update_entities()

    @callback
    def _update_entities(self) -> None:
        """Add entities for new streams and drop the ones that have stopped."""
        # A failed refresh leaves coordinator.data untouched, so entities are
        # never torn down just because Dispatcharr was briefly unreachable.
        current_stream_ids = set(self._coordinator.data or {})

        new_stream_ids = current_stream_ids - self._known_stream_ids
        if new_stream_ids:
            new_entities = [DispatcharrStreamMediaPlayer(self._coordinator, stream_id) for stream_id in new_stream_ids]
            self._async_add_entities(new_entities)
            self._known_stream_ids |= new_stream_ids

        stopped_stream_ids = self._known_stream_ids - current_stream_ids
        if stopped_stream_ids:
            self._remove_entities(stopped_stream_ids)
            self._known_stream_ids -= stopped_stream_ids

    @callback
    def _remove_entities(self, stream_ids: set) -> None:
        """Delete the registry entries for streams that are no longer running.

        Without this the entities linger forever as "unavailable"; removing the
        registry entry is what actually takes them out of the UI.
        """
        registry = er.async_get(self._coordinator.hass)
        entry_id = self._coordinator.config_entry.entry_id

        for stream_id in stream_ids:
            entity_id = registry.async_get_entity_id(
                "media_player", DOMAIN, f"{entry_id}_{stream_id}"
            )
            if entity_id:
                _LOGGER.debug("Stream %s stopped, removing %s", stream_id, entity_id)
                registry.async_remove(entity_id)


class DispatcharrStreamMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a single Dispatcharr stream as a Media Player."""
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = MediaPlayerEntityFeature.STOP
    _attr_media_content_type = MediaType.TVSHOW
    _attr_app_name = "Dispatcharr"

    def __init__(self, coordinator: DispatcharrDataUpdateCoordinator, stream_id: str):
        super().__init__(coordinator)
        self._stream_id = stream_id

        stream_data = (coordinator.data or {}).get(stream_id) or {}
        name = (
            stream_data.get("channel_name")
            or stream_data.get("stream_name")
            or f"Stream {stream_id[-6:]}"
        )

        self._attr_name = name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{stream_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def _stream_data(self) -> dict:
        """This stream's current data, or an empty dict once it has stopped."""
        return (self.coordinator.data or {}).get(self._stream_id) or {}

    @property
    def _program_data(self) -> dict:
        return self._stream_data.get("program") or {}

    @property
    def available(self) -> bool:
        """Return True if the stream is still in the coordinator's data."""
        return super().available and bool(self._stream_data)

    # Prevents a TypeError from the media_player grouping helpers.
    @property
    def support_grouping(self) -> bool:
        """Flag if grouping is supported."""
        return False

    @property
    def state(self) -> MediaPlayerState | None:
        return MediaPlayerState.PLAYING if self._stream_data else None

    @property
    def entity_picture(self) -> str | None:
        return self._stream_data.get("logo_url")

    @property
    def media_content_id(self) -> str | None:
        return self._stream_data.get("tvg_id")

    @property
    def media_series_title(self) -> str | None:
        """The channel name, shown as the 'series' line in media cards."""
        return self._stream_data.get("channel_name")

    @property
    def media_title(self) -> str | None:
        program = self._program_data
        return program.get("subtitle") or program.get("title")

    @property
    def extra_state_attributes(self) -> dict:
        stream_data = self._stream_data
        program_data = self._program_data
        clients = stream_data.get("clients") or []
        return {
            "channel_number": stream_data.get("channel_number"),
            "channel_name": stream_data.get("channel_name"),
            "tvg_id": stream_data.get("tvg_id"),
            "program_title": program_data.get("title"),
            "program_description": program_data.get("description"),
            "program_start": program_data.get("start_time"),
            "program_stop": program_data.get("end_time"),
            "clients": stream_data.get("client_count"),
            "client_ips": [c["ip_address"] for c in clients if c.get("ip_address")],
            "client_details": clients,
            "resolution": stream_data.get("resolution"),
            "fps": stream_data.get("source_fps"),
            "video_codec": stream_data.get("video_codec"),
            "audio_codec": stream_data.get("audio_codec"),
            "audio_channels": stream_data.get("audio_channels"),
            "avg_bitrate": stream_data.get("avg_bitrate"),
            "uptime": stream_data.get("uptime"),
            "stream_profile": stream_data.get("stream_profile"),
        }

    async def async_media_stop(self) -> None:
        """Stop this channel's stream for all viewers via the Dispatcharr API."""
        await self.coordinator.async_stop_channel(self._stream_id)
        await self.coordinator.async_request_refresh()
