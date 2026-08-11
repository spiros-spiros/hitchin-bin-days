"""Constants for the North Herts Bins integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "north_herts_bins"

CONF_URL = "url"
CONF_ADDRESS = "address"

DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

# The council's Netcall Liberty Create site only returns its page content to
# requests that look like the in-page AJAX call.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE_HOST = "waste.nc.north-herts.gov.uk"
DETAILS_PATH = "/w/webpage/find-bin-collection-day-show-details"

LOOKUP_PAGE = (
    "https://www.north-herts.gov.uk/find-your-bin-collection-day"
)
