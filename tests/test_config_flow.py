"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.north_herts_bins.const import CONF_ADDRESS, CONF_URL, DOMAIN

from .conftest import RESULTS_URL


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Don't run the full integration setup during config flow tests."""
    with patch(
        "custom_components.north_herts_bins.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def test_user_flow_creates_entry(hass, aioclient_mock, page_fragment) -> None:
    """Pasting a valid URL creates an entry titled with the address."""
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: RESULTS_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "1 EXAMPLE STREET, HITCHIN, SG4 0AA"
    assert result["data"][CONF_URL] == RESULTS_URL
    assert result["data"][CONF_ADDRESS] == "1 EXAMPLE STREET, HITCHIN, SG4 0AA"


async def test_user_flow_rejects_invalid_url(hass, aioclient_mock, page_fragment) -> None:
    """A bad URL shows an error, and the flow can then be completed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "https://example.com/nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}

    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: RESULTS_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_handles_connection_error(hass, aioclient_mock) -> None:
    """A site outage shows a retryable error."""
    aioclient_mock.post(RESULTS_URL, status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: RESULTS_URL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_handles_empty_page(hass, aioclient_mock) -> None:
    """A page with no bins shows the no_data error."""
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": "<p>none</p>"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: RESULTS_URL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_data"}


async def test_duplicate_address_aborts(
    hass, aioclient_mock, page_fragment, mock_entry
) -> None:
    """Adding the same property twice is rejected."""
    mock_entry.add_to_hass(hass)
    aioclient_mock.post(RESULTS_URL, json={"status": "success", "data": page_fragment})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: RESULTS_URL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_url(
    hass, aioclient_mock, page_fragment, mock_entry
) -> None:
    """Re-auth swaps in a fresh link without losing the entry."""
    mock_entry.add_to_hass(hass)
    new_url = RESULTS_URL.replace("id=99999999", "id=99999999&refreshed=1")
    aioclient_mock.post(new_url, json={"status": "success", "data": page_fragment})

    result = await mock_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: new_url}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_URL] == new_url
