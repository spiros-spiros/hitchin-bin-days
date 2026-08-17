"""Calendar platform for North Herts Bins.

Shows each bin's next collection as an all-day event, so upcoming bin days are
visible on a dashboard calendar card.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import NorthHertsBinsCoordinator, NorthHertsConfigEntry
from .entity import NorthHertsBinsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NorthHertsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([BinCalendar(entry.runtime_data)])


class BinCalendar(NorthHertsBinsEntity, CalendarEntity):
    """A calendar of upcoming bin collections."""

    _attr_name = "Bin collections"
    _attr_icon = "mdi:calendar"

    def __init__(self, coordinator: NorthHertsBinsCoordinator) -> None:
        """Initialise the calendar."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_calendar"

    def _events(self) -> list[CalendarEvent]:
        """Build all-day events from the known collections."""
        events = [
            CalendarEvent(
                summary=(
                    f"{c.name} ({c.container})" if c.container else c.name
                ),
                start=c.next_collection,
                end=c.next_collection + timedelta(days=1),
                description=c.cycle or "",
            )
            for c in self._collections()
        ]
        return sorted(events, key=lambda event: event.start)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming collection."""
        today = dt_util.now().date()
        return next((e for e in self._events() if e.end > today), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events within the requested window."""
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date()
        return [e for e in self._events() if e.start < end and e.end > start]
