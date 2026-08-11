"""Tests that the notification blueprint loads and fires correctly."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.components import automation
from homeassistant.setup import async_setup_component
from freezegun.api import FrozenDateTimeFactory
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import RESULTS_URL

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "north_herts_bins"
    / "bin_day_notification.yaml"
)

TODAY_SENSOR = "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today"
TOMORROW_SENSOR = "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_tomorrow"


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Automations keep their time triggers armed until Home Assistant stops."""
    return True


@pytest.fixture
def install_blueprint(hass) -> None:
    """Copy the blueprint into the test config directory."""
    dest = Path(hass.config.path("blueprints/automation/north_herts_bins"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest / BLUEPRINT.name)


async def _setup_integration(hass, aioclient_mock, page_fragment, mock_entry):
    await hass.config.async_set_time_zone("Europe/London")
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()


async def _setup_automation(hass) -> None:
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "use_blueprint": {
                    "path": "north_herts_bins/bin_day_notification.yaml",
                    "input": {
                        "bin_day_today": TODAY_SENSOR,
                        "bin_day_tomorrow": TOMORROW_SENSOR,
                        "notify_service": "persistent_notification",
                        "morning_time": "07:00:00",
                        "evening_time": "19:30:00",
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_blueprint_loads(
    hass, aioclient_mock, page_fragment, mock_entry, install_blueprint
) -> None:
    """The blueprint is valid and produces a working automation."""
    await _setup_integration(hass, aioclient_mock, page_fragment, mock_entry)
    await _setup_automation(hass)

    states = hass.states.async_entity_ids("automation")
    assert len(states) == 1
    assert hass.states.get(states[0]).state == "on"


async def test_morning_notification_on_bin_day(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    install_blueprint,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """At the morning time on collection day, a notification is sent."""
    freezer.move_to("2026-08-12 06:59:50+01:00")
    await _setup_integration(hass, aioclient_mock, page_fragment, mock_entry)
    await _setup_automation(hass)
    assert hass.states.get(TODAY_SENSOR).state == "on"
    service_calls.clear()

    freezer.move_to("2026-08-12 07:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    notifications = [c for c in service_calls if c.domain == "notify"]
    assert len(notifications) == 1
    message = notifications[0].data["message"]
    assert "today" in message
    assert "Food Waste" in message
    assert "Brown caddy" in message


async def test_evening_notification_the_night_before(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    install_blueprint,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """The evening before collection, a "tomorrow" notification is sent."""
    freezer.move_to("2026-08-11 19:29:50+01:00")
    await _setup_integration(hass, aioclient_mock, page_fragment, mock_entry)
    await _setup_automation(hass)
    assert hass.states.get(TOMORROW_SENSOR).state == "on"
    service_calls.clear()

    freezer.move_to("2026-08-11 19:30:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    notifications = [c for c in service_calls if c.domain == "notify"]
    assert len(notifications) == 1
    assert "tomorrow" in notifications[0].data["message"]


async def test_no_notification_when_no_bins_due(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    install_blueprint,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """On a day with no collection, nothing is sent."""
    freezer.move_to("2026-08-10 06:59:50+01:00")
    await _setup_integration(hass, aioclient_mock, page_fragment, mock_entry)
    await _setup_automation(hass)
    assert hass.states.get(TODAY_SENSOR).state == "off"
    service_calls.clear()

    freezer.move_to("2026-08-10 07:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    assert [c for c in service_calls if c.domain == "notify"] == []
