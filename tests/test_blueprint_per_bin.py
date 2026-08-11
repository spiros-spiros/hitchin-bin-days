"""Tests for the per-bin notification blueprint."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import automation
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import RESULTS_URL

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "north_herts_bins"
    / "bin_day_per_bin_notification.yaml"
)

TOMORROW_SENSOR = "binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_tomorrow"


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Automations keep their time triggers armed until Home Assistant stops."""
    return True


@pytest.fixture(autouse=True)
def install_blueprint(hass) -> None:
    """Copy the blueprint into the test config directory."""
    dest = Path(hass.config.path("blueprints/automation/north_herts_bins"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest / BLUEPRINT.name)


async def _setup(hass, aioclient_mock, page_fragment, mock_entry, services):
    await hass.config.async_set_time_zone("Europe/London")
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "use_blueprint": {
                    "path": "north_herts_bins/bin_day_per_bin_notification.yaml",
                    "input": {
                        "bin_day_tomorrow": TOMORROW_SENSOR,
                        "notify_services": services,
                        "alert_time": "17:00:00",
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()


async def test_one_notification_per_bin(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """Two bins due tomorrow produce two separate messages per service."""
    freezer.move_to("2026-08-11 16:59:50+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry, ["persistent_notification"])
    assert hass.states.get(TOMORROW_SENSOR).state == "on"
    service_calls.clear()

    freezer.move_to("2026-08-11 17:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    sent = [c for c in service_calls if c.domain == "notify"]
    assert len(sent) == 2

    messages = sorted(c.data["message"] for c in sent)
    assert messages == [
        "Cardboard & Paper (Blue lid bin) goes out tomorrow",
        "Food Waste (Brown caddy) goes out tomorrow",
    ]
    assert all(c.data["title"] == "Bin day" for c in sent)


async def test_fans_out_to_every_service(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """Each bin is sent to each configured notify service."""
    freezer.move_to("2026-08-11 16:59:50+01:00")
    await _setup(
        hass,
        aioclient_mock,
        page_fragment,
        mock_entry,
        ["mobile_app_a", "mobile_app_b", "persistent_notification"],
    )
    service_calls.clear()

    freezer.move_to("2026-08-11 17:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    sent = [c for c in service_calls if c.domain == "notify"]
    # 2 bins x 3 services
    assert len(sent) == 6
    assert {c.service for c in sent} == {
        "mobile_app_a",
        "mobile_app_b",
        "persistent_notification",
    }
    for service in ("mobile_app_a", "mobile_app_b", "persistent_notification"):
        per = sorted(c.data["message"] for c in sent if c.service == service)
        assert per == [
            "Cardboard & Paper (Blue lid bin) goes out tomorrow",
            "Food Waste (Brown caddy) goes out tomorrow",
        ]


async def test_silent_when_nothing_due_tomorrow(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """No bins tomorrow means no notifications at all."""
    freezer.move_to("2026-08-09 16:59:50+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry, ["persistent_notification"])
    assert hass.states.get(TOMORROW_SENSOR).state == "off"
    service_calls.clear()

    freezer.move_to("2026-08-09 17:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    assert [c for c in service_calls if c.domain == "notify"] == []


async def test_single_bin_day_sends_one_message(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """A day with one bin due sends exactly one message."""
    # Garden Waste alone is due on 2026-08-21.
    freezer.move_to("2026-08-20 16:59:50+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry, ["persistent_notification"])
    service_calls.clear()

    freezer.move_to("2026-08-20 17:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    sent = [c for c in service_calls if c.domain == "notify"]
    assert len(sent) == 1
    assert sent[0].data["message"] == "Garden Waste (Brown lid bin) goes out tomorrow"
