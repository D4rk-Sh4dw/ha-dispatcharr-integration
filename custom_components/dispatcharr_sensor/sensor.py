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

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = len(self.coordinator.data or {})
        self.async_write_ha_state()


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

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        self._attr_native_value = data.get("unread_notifications", 0)
        self._attr_extra_state_attributes = {
            "notifications": [
                {
                    "title": n.get("title"),
                    "message": n.get("message"),
                    "priority": n.get("priority"),
                    "notification_type": n.get("notification_type"),
                    "created_at": n.get("created_at"),
                }
                for n in data.get("notifications", [])
                if not n.get("is_dismissed")
            ]
        }
        self.async_write_ha_state()


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

        account = (coordinator.data or {}).get("m3u_accounts", {}).get(account_id) or {}
        name = account.get("name") or f"M3U Account {account_id}"

        self._attr_name = f"{name} Status"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_m3u_{account_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.config_entry.entry_id)}, name="Dispatcharr")

    @property
    def available(self) -> bool:
        accounts = (self.coordinator.data or {}).get("m3u_accounts", {})
        return super().available and self._account_id in accounts

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.available:
            self.async_write_ha_state()
            return

        account = self.coordinator.data["m3u_accounts"][self._account_id]
        self._attr_native_value = account.get("status")
        self._attr_extra_state_attributes = {
            "name": account.get("name"),
            "is_active": account.get("is_active"),
            "last_message": account.get("last_message"),
            "max_streams": account.get("max_streams"),
            "earliest_expiration": account.get("earliest_expiration"),
            "all_expirations": account.get("all_expirations"),
            "exp_date": account.get("exp_date"),
        }
        self.async_write_ha_state()
