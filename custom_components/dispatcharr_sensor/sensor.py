"""Sensor platform for Dispatcharr."""
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import PlatformNotReady

from .const import DOMAIN
from . import DispatcharrAuxDataCoordinator, DispatcharrDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from a ConfigEntry."""
    try:
        coordinator = hass.data[DOMAIN][config_entry.entry_id]
    except KeyError:
        raise PlatformNotReady(f"Coordinator not found for entry {config_entry.entry_id}")

    aux_coordinator = coordinator.aux_coordinator

    async_add_entities(
        [
            DispatcharrTotalStreamSensor(coordinator),
            DispatcharrActiveClientsSensor(coordinator),
            DispatcharrUnreadNotificationsSensor(aux_coordinator),
        ]
    )
    DispatcharrM3UAccountManager(aux_coordinator, async_add_entities)


class DispatcharrTotalStreamSensor(CoordinatorEntity, SensorEntity):
    """A sensor to show the total number of active Dispatcharr streams."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(self, coordinator: DispatcharrDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Total Active Streams"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_total_streams"
        self._attr_icon = "mdi:play-network"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or {})


class DispatcharrActiveClientsSensor(CoordinatorEntity, SensorEntity):
    """Total viewers across all active streams, with who is watching what."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(self, coordinator: DispatcharrDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Active Clients"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_active_clients"
        self._attr_icon = "mdi:account-multiple"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def native_value(self) -> int:
        """Total client count, taken from each channel's authoritative counter."""
        return sum(
            stream.get("client_count") or 0
            for stream in (self.coordinator.data or {}).values()
        )

    @property
    def extra_state_attributes(self) -> dict:
        clients = []
        per_channel = {}

        for stream in (self.coordinator.data or {}).values():
            channel = stream.get("channel_name") or stream.get("stream_name")
            per_channel[channel] = stream.get("client_count") or 0
            for client in stream.get("clients") or []:
                clients.append({**client, "channel_name": channel})

        return {
            "clients": clients,
            "clients_per_channel": per_channel,
            # The status API only lists the first 10 clients per channel, so the
            # detail list can be shorter than the counts above.
            "clients_listed": len(clients),
        }


class DispatcharrUnreadNotificationsSensor(CoordinatorEntity, SensorEntity):
    """A sensor showing the number of unread Dispatcharr system notifications."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(self, coordinator: DispatcharrAuxDataCoordinator):
        super().__init__(coordinator)
        self._attr_name = "Unread Notifications"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_unread_notifications"
        self._attr_icon = "mdi:bell-alert"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def native_value(self) -> int:
        return (self.coordinator.data or {}).get("unread_notifications", 0)

    @property
    def extra_state_attributes(self) -> dict:
        notifications = (self.coordinator.data or {}).get("notifications", [])
        return {
            "notifications": [
                {
                    "title": n.get("title"),
                    "message": n.get("message"),
                    "priority": n.get("priority"),
                    "notification_type": n.get("notification_type"),
                    "created_at": n.get("created_at"),
                }
                for n in notifications
                if not n.get("is_dismissed")
            ]
        }


class DispatcharrM3UAccountManager:
    """Manages the creation of one sensor per configured M3U account."""

    def __init__(self, coordinator: DispatcharrAuxDataCoordinator, async_add_entities: AddEntitiesCallback):
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._known_account_ids: set = set()
        self._coordinator.async_add_listener(self._update_entities)
        self._update_entities()

    @callback
    def _update_entities(self) -> None:
        accounts = (self._coordinator.data or {}).get("m3u_accounts", {})
        new_account_ids = set(accounts.keys()) - self._known_account_ids
        if new_account_ids:
            new_entities = [
                DispatcharrM3UAccountSensor(self._coordinator, account_id)
                for account_id in new_account_ids
            ]
            self._async_add_entities(new_entities)
            self._known_account_ids.update(new_account_ids)


class DispatcharrM3UAccountSensor(CoordinatorEntity, SensorEntity):
    """Represents the status of a single Dispatcharr M3U account."""
    _attr_has_entity_name = True
    _attr_icon = "mdi:playlist-play"

    def __init__(self, coordinator: DispatcharrAuxDataCoordinator, account_id: str):
        super().__init__(coordinator)
        self._account_id = account_id

        name = self._account_data.get("name") or f"M3U Account {account_id}"
        self._attr_name = f"{name} Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_m3u_{account_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def _account_data(self) -> dict:
        """The account's current data, or an empty dict if it's gone."""
        accounts = (self.coordinator.data or {}).get("m3u_accounts", {})
        return accounts.get(self._account_id) or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._account_data)

    @property
    def native_value(self) -> str | None:
        return self._account_data.get("status")

    @property
    def extra_state_attributes(self) -> dict:
        account = self._account_data
        return {
            "name": account.get("name"),
            "is_active": account.get("is_active"),
            "last_message": account.get("last_message"),
            "max_streams": account.get("max_streams"),
            "earliest_expiration": account.get("earliest_expiration"),
            "all_expirations": account.get("all_expirations"),
            "exp_date": account.get("exp_date"),
        }
