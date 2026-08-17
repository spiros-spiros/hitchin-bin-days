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
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
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
    # What the council actually printed, kept when next_collection had to be
    # rolled forward. None means next_collection is exactly what they said.
    reported_collection: date | None = None

    @property
    def slug(self) -> str:
        """A stable key for entity ids."""
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_")

    @property
    def projected(self) -> bool:
        """True when this date was rolled forward rather than read verbatim."""
        return self.reported_collection is not None

    @property
    def cycle_days(self) -> int | None:
        """How often this bin is collected, in days, from the cycle text."""
        return cycle_to_days(self.cycle)


@dataclass(frozen=True)
class BinData:
    """Everything scraped for one address."""

    address: str | None
    collections: list[BinCollection]


_ORDINALS = {
    "2nd": 2, "second": 2, "other": 2,
    "3rd": 3, "third": 3,
    "4th": 4, "fourth": 4,
    "5th": 5, "fifth": 5,
}


def cycle_to_days(cycle: str | None) -> int | None:
    """Turn a collection cycle description into an interval in days.

    The council writes these as free text, e.g. "Every Wednesday" (7),
    "Every 3rd Wednesday" (21), "Every Friday fortnightly" (14). Returns None
    when the text cannot be understood, in which case callers must not guess.
    """
    if not cycle:
        return None
    text = cycle.lower()

    # "Every 14 days" style, if it ever appears.
    if match := re.search(r"\bevery\s+(\d+)\s+days?\b", text):
        days = int(match.group(1))
        return days if days > 0 else None

    # "fortnightly" wins over any weekday, as in "Every Friday fortnightly".
    if "fortnight" in text or "biweekly" in text:
        return 14

    weeks: int | None = None
    if match := re.search(r"\bevery\s+(\d+)(?:st|nd|rd|th)\b", text):
        weeks = int(match.group(1))
    else:
        for word, value in _ORDINALS.items():
            if re.search(rf"\bevery\s+{word}\b", text):
                weeks = value
                break

    names_a_weekday = bool(
        re.search(
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text
        )
    )

    if weeks is not None:
        # "Every 3rd Wednesday" means every three weeks, not the third
        # Wednesday of the month: the three wheeled bins share one Wednesday
        # rota, each offset by a week.
        return weeks * 7 if names_a_weekday or "week" in text else None

    if names_a_weekday or "weekly" in text or re.search(r"\bevery\s+week\b", text):
        return 7

    return None


def project_collection(collection: BinCollection, today: date) -> BinCollection:
    """Roll a past collection date forward to the next one that is due.

    The council's page keeps serving a date for days after it has passed, which
    would otherwise report a negative "days until" and, worse, never match
    today or tomorrow - so the reminder for the real collection never fires.
    """
    if collection.next_collection >= today:
        return collection

    interval = collection.cycle_days
    if not interval:
        # Nothing reliable to extrapolate from; leave it alone rather than
        # inventing a date.
        return collection

    reported = collection.reported_collection or collection.next_collection
    gap = (today - collection.next_collection).days
    steps = -(-gap // interval)  # ceiling division
    return replace(
        collection,
        next_collection=collection.next_collection + timedelta(days=steps * interval),
        reported_collection=reported,
    )


def project_collections(
    collections: Iterable[BinCollection], today: date
) -> list[BinCollection]:
    """Project every collection forward, keeping the soonest-first order."""
    projected = [project_collection(c, today) for c in collections]
    return sorted(projected, key=lambda c: (c.next_collection, c.name))


def stale_collections(data: BinData, today: date) -> list[BinCollection]:
    """Collections whose council-reported date has already passed."""
    return [c for c in data.collections if c.next_collection < today]


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
