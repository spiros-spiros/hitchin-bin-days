"""Data update coordinator for North Herts Bins."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BinData,
    CannotConnectError,
    InvalidUrlError,
    NoDataError,
    async_fetch,
)
from .const import CONF_URL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

type NorthHertsConfigEntry = ConfigEntry[NorthHertsBinsCoordinator]


class NorthHertsBinsCoordinator(DataUpdateCoordinator[BinData]):
    """Fetch bin collection data from the council website."""

    config_entry: NorthHertsConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: NorthHertsConfigEntry
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=config_entry,
        )
        self._url: str = config_entry.data[CONF_URL]

    async def _async_update_data(self) -> BinData:
        """Fetch the latest collection data."""
        session = async_get_clientsession(self.hass)
        try:
            return await async_fetch(session, self._url)
        except InvalidUrlError as err:
            # The saved link is no longer usable - ask the user to re-add it.
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CannotConnectError, NoDataError) as err:
            raise UpdateFailed(str(err)) from err
