"""Binary sensor platform for North Herts Bins.

These are what automations key off: "is it bin day today", and per bin type
"is this bin going out today".
"""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import BinCollection
from .coordinator import NorthHertsBinsCoordinator, NorthHertsConfigEntry
from .entity import NorthHertsBinsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NorthHertsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        BinDayTodaySensor(coordinator),
        BinDayTomorrowSensor(coordinator),
    ]
    entities.extend(
        BinTodaySensor(coordinator, collection)
        for collection in coordinator.data.collections
    )
    async_add_entities(entities)


def _today() -> date:
    """Today's date in the user's configured timezone."""
    return dt_util.now().date()


class BinTodaySensor(NorthHertsBinsEntity, BinarySensorEntity):
    """Whether one specific bin is collected today."""

    _attr_icon = "mdi:trash-can"

    def __init__(
        self, coordinator: NorthHertsBinsCoordinator, collection: BinCollection
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self._slug = collection.slug
        self._attr_name = f"{collection.name} today"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{collection.slug}_today"
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if this bin is collected today."""
        collection = self._collection(self._slug)
        if collection is None:
            return None
        return collection.next_collection == _today()

    @property
    def available(self) -> bool:
        """Return whether this bin type is still in the council's data."""
        return super().available and self._collection(self._slug) is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return details useful in notification messages."""
        collection = self._collection(self._slug)
        if collection is None:
            return {}
        return {
            "bin": collection.name,
            "container": collection.container,
            "cycle": collection.cycle,
            "next_collection": collection.next_collection.isoformat(),
        }


class _AnyBinSensor(NorthHertsBinsEntity, BinarySensorEntity):
    """Shared logic for "any bin due on <offset>" sensors."""

    _offset = 0

    def _due(self) -> list[BinCollection]:
        """Return the bins due on the target day."""
        if not self.coordinator.data:
            return []
        target = _today() + timedelta(days=self._offset)
        return [
            c for c in self.coordinator.data.collections if c.next_collection == target
        ]

    @property
    def is_on(self) -> bool:
        """Return true if any bin is due."""
        return bool(self._due())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return which bins are due, ready to drop into a message."""
        due = self._due()
        return {
            "bins": [c.name for c in due],
            "containers": [c.container for c in due if c.container],
            "message": ", ".join(
                f"{c.name} ({c.container})" if c.container else c.name for c in due
            ),
        }


class BinDayTodaySensor(_AnyBinSensor):
    """Whether any bin is collected today."""

    _offset = 0
    _attr_name = "Bin day today"
    _attr_icon = "mdi:trash-can"

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_bin_day_today"


class BinDayTomorrowSensor(_AnyBinSensor):
    """Whether any bin is collected tomorrow."""

    _offset = 1
    _attr_name = "Bin day tomorrow"
    _attr_icon = "mdi:trash-can-outline"

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_bin_day_tomorrow"
