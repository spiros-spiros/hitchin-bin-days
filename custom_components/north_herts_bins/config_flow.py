"""Config flow for North Herts Bins."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CannotConnectError,
    InvalidUrlError,
    NoDataError,
    async_fetch,
    validate_url,
)
from .const import CONF_ADDRESS, CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_URL): str})


class NorthHertsBinsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for North Herts Bins."""

    VERSION = 1

    async def _async_validate(self, url: str) -> tuple[str | None, dict[str, str]]:
        """Validate the URL by fetching it. Returns (address, errors)."""
        try:
            validate_url(url)
            data = await async_fetch(async_get_clientsession(self.hass), url)
        except InvalidUrlError as err:
            _LOGGER.debug("Invalid URL supplied: %s", err)
            return None, {CONF_URL: "invalid_url"}
        except CannotConnectError as err:
            _LOGGER.debug("Cannot connect: %s", err)
            return None, {"base": "cannot_connect"}
        except NoDataError as err:
            _LOGGER.debug("No data found: %s", err)
            return None, {"base": "no_data"}
        return data.address, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            address, errors = await self._async_validate(url)

            if not errors:
                await self.async_set_unique_id(_unique_id(url))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=address or "North Herts Bins",
                    data={CONF_URL: url, CONF_ADDRESS: address},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the saved link stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for a fresh results URL."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            address, errors = await self._async_validate(url)

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_URL: url,
                        CONF_ADDRESS: address or entry.data.get(CONF_ADDRESS),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "address": entry.data.get(CONF_ADDRESS) or entry.title
            },
        )


def _unique_id(url: str) -> str:
    """Derive a stable unique id from the property id in the URL."""
    query = parse_qs(urlparse(url).query)
    property_id = query.get("id", [""])[0]
    return f"{DOMAIN}_{property_id}"
