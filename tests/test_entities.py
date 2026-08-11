"""Tests for the sensor, binary sensor and calendar platforms."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import RESULTS_URL

# The fixture's soonest collection (Cardboard & Paper, Food Waste).
COLLECTION_DAY = "2026-08-12"


async def _setup(hass, aioclient_mock, page_fragment, mock_entry):
    # Collection days are local dates, so pin the timezone the council uses.
    await hass.config.async_set_time_zone("Europe/London")
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry


async def test_setup_creates_expected_entities(
    hass, aioclient_mock, page_fragment, mock_entry
) -> None:
    """The entry loads and creates entities for all five bins."""
    entry = await _setup(hass, aioclient_mock, page_fragment, mock_entry)
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.1_example_street_hitchin_sg4_0aa_food_waste")
    assert hass.states.get("binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today")
    assert hass.states.get("calendar.1_example_street_hitchin_sg4_0aa_bin_collections")

    bin_sensors = [
        s for s in hass.states.async_all("sensor") if s.attributes.get("cycle")
    ]
    assert len(bin_sensors) == 5


async def test_bin_date_sensor_values(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """A bin sensor reports its date, container and days remaining."""
    freezer.move_to("2026-08-10 09:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    state = hass.states.get("sensor.1_example_street_hitchin_sg4_0aa_food_waste")
    assert state.state == COLLECTION_DAY
    assert state.attributes["container"] == "Brown caddy"
    assert state.attributes["cycle"] == "Every Wednesday"
    assert state.attributes["days_until"] == 2
    assert state.attributes["is_today"] is False


async def test_bin_day_today_false_before_the_day(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """Bin day sensors are off when nothing is due."""
    freezer.move_to("2026-08-10 09:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    assert (
        hass.states.get(
            "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today"
        ).state
        == "off"
    )
    assert (
        hass.states.get(
            "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_tomorrow"
        ).state
        == "off"
    )


async def test_bin_day_today_true_on_the_day(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """On collection day the sensor is on and lists the right bins."""
    freezer.move_to("2026-08-12 07:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    state = hass.states.get(
        "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today"
    )
    assert state.state == "on"
    assert set(state.attributes["bins"]) == {"Cardboard & Paper", "Food Waste"}
    assert "Brown caddy" in state.attributes["message"]

    assert (
        hass.states.get(
            "binary_sensor.1_example_street_hitchin_sg4_0aa_food_waste_today"
        ).state
        == "on"
    )
    assert (
        hass.states.get(
            "binary_sensor.1_example_street_hitchin_sg4_0aa_garden_waste_today"
        ).state
        == "off"
    )


async def test_bin_day_tomorrow_on_the_eve(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The night-before sensor fires on the eve of collection."""
    freezer.move_to("2026-08-11 20:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    assert (
        hass.states.get(
            "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_tomorrow"
        ).state
        == "on"
    )


async def test_state_flips_at_midnight_without_a_poll(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """Crossing midnight updates the sensors even though data is unchanged.

    This is the case that matters for notifications: the coordinator only polls
    every few hours, so the date rollover has to drive the state itself.
    """
    freezer.move_to("2026-08-11 23:50:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    today = "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today"
    assert hass.states.get(today).state == "off"

    freezer.move_to("2026-08-12 00:00:30+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    assert hass.states.get(today).state == "on"


async def test_calendar_next_event(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The calendar surfaces the next collection as an all-day event."""
    freezer.move_to("2026-08-10 09:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    state = hass.states.get("calendar.1_example_street_hitchin_sg4_0aa_bin_collections")
    assert state.state == "off"
    assert state.attributes["start_time"].startswith("2026-08-12")
    assert "Blue lid bin" in state.attributes["message"]


async def test_unload_entry(hass, aioclient_mock, page_fragment, mock_entry) -> None:
    """The entry unloads cleanly."""
    entry = await _setup(hass, aioclient_mock, page_fragment, mock_entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
