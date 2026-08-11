"""Client for North Herts Council's bin collection lookup.

The council's public "find your bin collection day" tool is a Netcall Liberty
Create app.  A plain GET returns only a JavaScript shell, but the page fills
itself in with a single AJAX POST back to the same URL, which returns JSON with
the rendered HTML in its ``data`` key.  We do exactly that one POST.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import BASE_HOST, DETAILS_PATH, USER_AGENT

_LOGGER = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_RECORD_SPLIT_RE = re.compile(r'<div[^>]*class="[^"]*listing_template_record[^"]*"[^>]*>')
_DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
)
_ADDRESS_RE = re.compile(
    r"Next bin collection days for:\s*\n(.+)", re.IGNORECASE
)

_LABEL_NEXT = "next collection"
_LABEL_CYCLE = "collection cycle"
_SKIP_LINES = {_LABEL_NEXT, _LABEL_CYCLE, "change address", ""}


class NorthHertsBinsError(Exception):
    """Base error."""


class InvalidUrlError(NorthHertsBinsError):
    """The configured URL is not a North Herts bin collection results URL."""


class CannotConnectError(NorthHertsBinsError):
    """The council site could not be reached."""


class NoDataError(NorthHertsBinsError):
    """The page loaded but contained no collection data."""


@dataclass(frozen=True)
class BinCollection:
    """A single bin type and when it is next collected."""

    name: str
    container: str | None
    next_collection: date
    cycle: str | None

    @property
    def slug(self) -> str:
        """A stable key for entity ids."""
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")


@dataclass(frozen=True)
class BinData:
    """Everything scraped for one address."""

    address: str | None
    collections: list[BinCollection]


def validate_url(url: str) -> str:
    """Check the URL is a results URL for this council, and normalise it."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc != BASE_HOST:
        raise InvalidUrlError(f"URL must be on https://{BASE_HOST}")
    if not parsed.path.startswith(DETAILS_PATH):
        raise InvalidUrlError(
            "URL must be the results page "
            "(.../find-bin-collection-day-show-details?...)"
        )
    query = parse_qs(parsed.query)
    missing = [k for k in ("webpage_token", "auth", "id") if k not in query]
    if missing:
        raise InvalidUrlError(
            f"URL is missing required parameter(s): {', '.join(missing)}"
        )
    return url


def _to_text(fragment: str) -> str:
    """Strip HTML down to newline-separated text."""
    text = _SCRIPT_RE.sub("", fragment)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = _TAG_RE.sub("\n", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _parse_date(value: str) -> date | None:
    match = _DATE_RE.search(value)
    if not match:
        return None
    day, month, year = match.groups()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(f"{day} {month} {year}", fmt).date()
        except ValueError:
            continue
    return None


def parse(fragment: str) -> BinData:
    """Parse the rendered HTML fragment into bin collections."""
    address = None
    if match := _ADDRESS_RE.search(_to_text(fragment)):
        candidate = match.group(1).strip()
        if candidate.lower() not in _SKIP_LINES:
            address = candidate

    collections: dict[str, BinCollection] = {}

    # The page renders the same list twice (a desktop and a small-screen
    # variant), so keep the first occurrence of each bin name.
    for block in _RECORD_SPLIT_RE.split(fragment)[1:]:
        lines = [line for line in _to_text(block).split("\n") if line]
        lowered = [line.lower() for line in lines]

        if _LABEL_NEXT not in lowered:
            continue

        next_date = None
        cycle = None
        consumed: set[int] = set()

        idx = lowered.index(_LABEL_NEXT)
        consumed.add(idx)
        if idx + 1 < len(lines):
            next_date = _parse_date(lines[idx + 1])
            consumed.add(idx + 1)

        if _LABEL_CYCLE in lowered:
            idx = lowered.index(_LABEL_CYCLE)
            consumed.add(idx)
            if idx + 1 < len(lines):
                cycle = lines[idx + 1]
                consumed.add(idx + 1)

        if next_date is None:
            continue

        # The bin name is the first line of the block; the container
        # ("Blue lid bin", "Brown caddy") is the next unconsumed line.
        name = lines[0]
        consumed.add(0)
        container = next(
            (
                line
                for i, line in enumerate(lines)
                if i not in consumed and line.lower() not in _SKIP_LINES
            ),
            None,
        )

        collection = BinCollection(
            name=name, container=container, next_collection=next_date, cycle=cycle
        )
        collections.setdefault(collection.slug, collection)

    if not collections:
        raise NoDataError("No bin collections found on the page")

    ordered = sorted(collections.values(), key=lambda c: (c.next_collection, c.name))
    return BinData(address=address, collections=ordered)


async def async_fetch(session: aiohttp.ClientSession, url: str) -> BinData:
    """Fetch and parse the collection data for a configured address URL."""
    validate_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    try:
        async with session.post(
            url, data={"_dummy": "1"}, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except aiohttp.ClientError as err:
        raise CannotConnectError(str(err)) from err
    except (TimeoutError, ValueError) as err:
        raise CannotConnectError(str(err)) from err

    if not isinstance(payload, dict) or "data" not in payload:
        raise NoDataError("Unexpected response from the council website")

    return parse(payload["data"])
