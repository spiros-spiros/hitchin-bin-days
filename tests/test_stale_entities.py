"""Entity behaviour when the council serves a date that has already passed."""

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

PREFIX = "1_example_street_hitchin_sg4_0aa"
FOOD_DATE = f"sensor.{PREFIX}_food_waste"
FOOD_DAYS = f"sensor.{PREFIX}_food_waste_in"
CARD_DATE = f"sensor.{PREFIX}_cardboard_paper"
CARD_DAYS = f"sensor.{PREFIX}_cardboard_paper_in"
NEXT_DATE = f"sensor.{PREFIX}_next_collection"
NEXT_BINS = f"sensor.{PREFIX}_next_collection_bins"
TOMORROW = f"binary_sensor.{PREFIX}_bin_day_tomorrow"
TODAY = f"binary_sensor.{PREFIX}_bin_day_today"

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "north_herts_bins"
    / "bin_day_per_bin_notification.yaml"
)


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Automations keep their time triggers armed until Home Assistant stops."""
    return True


async def _setup(hass, aioclient_mock, page_fragment, mock_entry):
    await hass.config.async_set_time_zone("Europe/London")
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()


async def test_days_until_is_never_negative(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The reported symptom: "-5 d" against a date five days gone."""
    freezer.move_to("2026-08-17 10:33:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    assert hass.states.get(FOOD_DAYS).state == "2"
    assert hass.states.get(CARD_DAYS).state == "16"

    for entity in (FOOD_DAYS, CARD_DAYS, f"sensor.{PREFIX}_garden_waste_in"):
        assert int(hass.states.get(entity).state) >= 0


async def test_stale_dates_roll_forward(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """Passed dates advance by their cycle; sound ones stay verbatim."""
    freezer.move_to("2026-08-17 10:33:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    food = hass.states.get(FOOD_DATE)
    assert food.state == "2026-08-19"
    assert food.attributes["projected"] is True
    assert food.attributes["council_reported"] == "2026-08-12"

    card = hass.states.get(CARD_DATE)
    assert card.state == "2026-09-02"
    assert card.attributes["projected"] is True

    # Untouched by projection.
    purple = hass.states.get(f"sensor.{PREFIX}_non_recyclable_waste")
    assert purple.state == "2026-08-19"
    assert purple.attributes["projected"] is False
    assert purple.attributes["council_reported"] is None


async def test_next_collection_follows_the_corrected_dates(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The summary sensors must not still point at the stale date."""
    freezer.move_to("2026-08-17 10:33:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    assert hass.states.get(NEXT_DATE).state == "2026-08-19"
    bins = hass.states.get(NEXT_BINS).state
    assert "Food Waste" in bins
    assert "Non-Recyclable Waste" in bins
    # Cardboard moved to September, so it is no longer next.
    assert "Cardboard" not in bins


async def test_bin_day_tomorrow_fires_for_the_stale_bin(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The consequential bug: the eve of the real collection.

    Before projection, Food Waste sat on 12 August, so nothing matched
    18 August and the reminder stayed silent while the caddy was due.
    """
    freezer.move_to("2026-08-18 16:00:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)

    state = hass.states.get(TOMORROW)
    assert state.state == "on"
    assert set(state.attributes["bins"]) == {"Food Waste", "Non-Recyclable Waste"}
    assert "Brown caddy" in state.attributes["message"]


async def test_per_bin_alert_fires_at_1700_for_the_stale_bin(
    hass,
    aioclient_mock,
    page_fragment,
    mock_entry,
    freezer: FrozenDateTimeFactory,
    service_calls,
) -> None:
    """End to end: the live 17:00 automation sends for the recovered bin."""
    dest = Path(hass.config.path("blueprints/automation/north_herts_bins"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, dest / BLUEPRINT.name)

    freezer.move_to("2026-08-18 16:59:50+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "use_blueprint": {
                    "path": "north_herts_bins/bin_day_per_bin_notification.yaml",
                    "input": {
                        "bin_day_tomorrow": TOMORROW,
                        "notify_services": ["persistent_notification"],
                        "alert_time": "17:00:00",
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    service_calls.clear()

    freezer.move_to("2026-08-18 17:00:01+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    sent = sorted(
        c.data["message"] for c in service_calls if c.domain == "notify"
    )
    assert sent == [
        "Food Waste (Brown caddy) goes out tomorrow",
        "Non-Recyclable Waste (Purple lid bin) goes out tomorrow",
    ]


async def test_projection_tracks_the_date_without_a_poll(
    hass, aioclient_mock, page_fragment, mock_entry, freezer: FrozenDateTimeFactory
) -> None:
    """Projection is applied on read, so it stays right between polls.

    The coordinator only refreshes every six hours. If projection were done at
    fetch time, a date could go stale again after midnight and sit wrong until
    the next poll.
    """
    freezer.move_to("2026-08-18 23:50:00+01:00")
    await _setup(hass, aioclient_mock, page_fragment, mock_entry)
    assert hass.states.get(FOOD_DATE).state == "2026-08-19"
    assert hass.states.get(TODAY).state == "off"

    # Cross midnight into collection day, with no new fetch.
    freezer.move_to("2026-08-19 00:00:30+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    assert hass.states.get(TODAY).state == "on"
    assert hass.states.get(FOOD_DAYS).state == "0"

    # And the day after, it must advance again rather than go negative.
    freezer.move_to("2026-08-20 00:00:30+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    assert hass.states.get(FOOD_DATE).state == "2026-08-26"
    assert int(hass.states.get(FOOD_DAYS).state) >= 0
