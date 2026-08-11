"""Sensor platform for North Herts Bins."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
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
    """Set up the sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        NextCollectionSensor(coordinator),
        NextCollectionBinsSensor(coordinator),
    ]
    for collection in coordinator.data.collections:
        entities.append(BinDateSensor(coordinator, collection))
        entities.append(BinDaysSensor(coordinator, collection))

    async_add_entities(entities)


def _today(hass: HomeAssistant) -> date:
    """Today's date in the user's configured timezone."""
    return dt_util.now().date()


class BinDateSensor(NorthHertsBinsEntity, SensorEntity):
    """Next collection date for one bin type."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self, coordinator: NorthHertsBinsCoordinator, collection: BinCollection
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._slug = collection.slug
        self._attr_name = collection.name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{collection.slug}"

    @property
    def native_value(self) -> date | None:
        """Return the next collection date."""
        collection = self._collection(self._slug)
        return collection.next_collection if collection else None

    @property
    def available(self) -> bool:
        """Return whether this bin type is still in the council's data."""
        return super().available and self._collection(self._slug) is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return extra details about this bin."""
        collection = self._collection(self._slug)
        if collection is None:
            return {}
        days = (collection.next_collection - _today(self.hass)).days
        return {
            "container": collection.container,
            "cycle": collection.cycle,
            "days_until": days,
            "is_today": days == 0,
            "is_tomorrow": days == 1,
        }


class BinDaysSensor(NorthHertsBinsEntity, SensorEntity):
    """Days until the next collection for one bin type."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: NorthHertsBinsCoordinator, collection: BinCollection
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._slug = collection.slug
        self._attr_name = f"{collection.name} in"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{collection.slug}_days"
        )

    @property
    def native_value(self) -> int | None:
        """Return the number of days until collection."""
        collection = self._collection(self._slug)
        if collection is None:
            return None
        return (collection.next_collection - _today(self.hass)).days

    @property
    def available(self) -> bool:
        """Return whether this bin type is still in the council's data."""
        return super().available and self._collection(self._slug) is not None


class NextCollectionSensor(NorthHertsBinsEntity, SensorEntity):
    """The soonest collection date across all bin types."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_name = "Next collection"

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_next_collection"

    @property
    def native_value(self) -> date | None:
        """Return the soonest collection date."""
        if not self.coordinator.data or not self.coordinator.data.collections:
            return None
        return min(c.next_collection for c in self.coordinator.data.collections)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return which bins go out on that date."""
        value = self.native_value
        if value is None:
            return {}
        due = [c for c in self.coordinator.data.collections if c.next_collection == value]
        return {
            "bins": [c.name for c in due],
            "containers": [c.container for c in due if c.container],
            "days_until": (value - _today(self.hass)).days,
        }


class NextCollectionBinsSensor(NorthHertsBinsEntity, SensorEntity):
    """Which bins go out at the next collection, as readable text."""

    _attr_name = "Next collection bins"
    _attr_icon = "mdi:trash-can-outline"

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_next_bins"

    @property
    def native_value(self) -> str | None:
        """Return a comma separated list of the bins due next."""
        if not self.coordinator.data or not self.coordinator.data.collections:
            return None
        soonest = min(c.next_collection for c in self.coordinator.data.collections)
        names = [
            c.name
            for c in self.coordinator.data.collections
            if c.next_collection == soonest
        ]
        return ", ".join(names)
