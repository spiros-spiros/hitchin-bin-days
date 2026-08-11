"""Base entity for North Herts Bins."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BinCollection
from .const import CONF_ADDRESS, DOMAIN
from .coordinator import NorthHertsBinsCoordinator


class NorthHertsBinsEntity(CoordinatorEntity[NorthHertsBinsCoordinator]):
    """Common device info for all entities in this integration."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        address = entry.data.get(CONF_ADDRESS) or entry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=address,
            manufacturer="North Herts Council",
            model="Bin collections",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.north-herts.gov.uk/find-your-bin-collection-day",
        )

    async def async_added_to_hass(self) -> None:
        """Register a midnight refresh as well as coordinator updates.

        Everything here is derived by comparing stored dates against "today",
        so state has to be rewritten when the date rolls over - the coordinator
        only polls every few hours.
        """
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=5
            )
        )

    @callback
    def _handle_midnight(self, now: object) -> None:
        """Rewrite state when the date changes."""
        self.async_write_ha_state()

    def _collection(self, slug: str) -> BinCollection | None:
        """Return the current data for one bin type, if still present."""
        if self.coordinator.data is None:
            return None
        return next(
            (c for c in self.coordinator.data.collections if c.slug == slug), None
        )
