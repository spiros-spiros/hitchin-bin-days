"""Fixtures for the North Herts Bins tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.north_herts_bins.const import (
    CONF_ADDRESS,
    CONF_URL,
    DOMAIN,
)

RESULTS_URL = (
    "https://waste.nc.north-herts.gov.uk/w/webpage/find-bin-collection-day-show-details"
    "?webpage_token=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    "&auth=VEVTVEFVVEg=&id=99999999"
)

ADDRESS = "1 EXAMPLE STREET, HITCHIN, SG4 0AA"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    return


@pytest.fixture(autouse=True, scope="session")
def _warm_dns_resolver():
    """Start the aiodns/pycares daemon thread before tests snapshot threads.

    Home Assistant's shared aiohttp session spins up a pycares resolver thread
    the first time it is used. It is a session-lifetime daemon thread, but the
    test harness flags it as "lingering" for whichever test happened to trigger
    it. Creating it up front keeps that noise out of the results.
    """
    try:
        import pycares
    except ImportError:
        return

    channel = pycares.Channel()
    try:
        yield
    finally:
        del channel


@pytest.fixture
def page_fragment() -> str:
    """The rendered HTML fragment captured from the live council site."""
    path = Path(__file__).parent / "fixtures" / "show_details.json"
    return json.loads(path.read_text())["data"]


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """A config entry pointing at the captured address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=ADDRESS,
        data={CONF_URL: RESULTS_URL, CONF_ADDRESS: ADDRESS},
        unique_id="north_herts_bins_99999999",
    )
