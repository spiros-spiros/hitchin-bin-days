"""Tests for the parsing and fetching logic."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.north_herts_bins.api import (
    InvalidUrlError,
    NoDataError,
    async_fetch,
    parse,
    validate_url,
)

from .conftest import RESULTS_URL

EXPECTED = {
    "cardboard_paper": ("Cardboard & Paper", "Blue lid bin", date(2026, 8, 12)),
    "food_waste": ("Food Waste", "Brown caddy", date(2026, 8, 12)),
    "non_recyclable_waste": ("Non-Recyclable Waste", "Purple lid bin", date(2026, 8, 19)),
    "garden_waste": ("Garden Waste", "Brown lid bin", date(2026, 8, 21)),
    "mixed_recycling": ("Mixed Recycling", "Black lid bin", date(2026, 8, 26)),
}


def test_parses_all_five_bins(page_fragment: str) -> None:
    """All five bin types are found, with container and cycle."""
    data = parse(page_fragment)
    assert len(data.collections) == 5

    by_slug = {c.slug: c for c in data.collections}
    assert set(by_slug) == set(EXPECTED)

    for slug, (name, container, when) in EXPECTED.items():
        collection = by_slug[slug]
        assert collection.name == name
        assert collection.container == container
        assert collection.next_collection == when
        assert collection.cycle


def test_collections_sorted_by_date(page_fragment: str) -> None:
    """Collections come back soonest first."""
    dates = [c.next_collection for c in parse(page_fragment).collections]
    assert dates == sorted(dates)


def test_parses_address(page_fragment: str) -> None:
    """The property address is extracted for the entry title."""
    assert parse(page_fragment).address == "1 EXAMPLE STREET, HITCHIN, SG4 0AA"


def test_deduplicates_repeated_layouts(page_fragment: str) -> None:
    """The page renders the list twice; each bin appears once."""
    names = [c.name for c in parse(page_fragment).collections]
    assert len(names) == len(set(names))


def test_parse_rejects_empty_page() -> None:
    """A page with no collections raises rather than silently returning none."""
    with pytest.raises(NoDataError):
        parse("<html><body>Nothing to see</body></html>")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/bins",
        "https://waste.nc.north-herts.gov.uk/w/webpage/find-bin-collection-day-input-address",
        "https://waste.nc.north-herts.gov.uk/w/webpage/find-bin-collection-day-show-details?id=1",
        "not-a-url",
        "",
    ],
)
def test_validate_url_rejects_bad_urls(url: str) -> None:
    """Only full results URLs on the council host are accepted."""
    with pytest.raises(InvalidUrlError):
        validate_url(url)


def test_validate_url_accepts_and_strips() -> None:
    """A valid URL is accepted, with surrounding whitespace removed."""
    assert validate_url(f"  {RESULTS_URL}  ") == RESULTS_URL


async def test_async_fetch_sends_the_ajax_post(page_fragment: str) -> None:
    """The fetch posts as the page's own AJAX call does.

    The council site returns a bare JavaScript shell to anything that does not
    look like the in-page request, so these headers are load-bearing.
    """
    seen: dict[str, object] = {}

    class _Response:
        status = 200

        def raise_for_status(self) -> None:
            return None

        async def json(self, content_type=None):
            return {"status": "success", "data": page_fragment}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Session:
        def post(self, url, data=None, headers=None, timeout=None):
            seen.update(url=url, data=data, headers=headers)
            return _Response()

    data = await async_fetch(_Session(), RESULTS_URL)

    assert len(data.collections) == 5
    assert seen["url"] == RESULTS_URL
    assert seen["data"] == {"_dummy": "1"}
    assert seen["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert "Mozilla" in seen["headers"]["User-Agent"]


async def test_async_fetch_rejects_bad_url() -> None:
    """The URL is validated before any request is made."""
    with pytest.raises(InvalidUrlError):
        await async_fetch(object(), "https://example.com/bins")


async def test_async_fetch_raises_on_unexpected_payload() -> None:
    """A response without the data key surfaces as NoDataError."""

    class _Response:
        def raise_for_status(self) -> None:
            return None

        async def json(self, content_type=None):
            return {"status": "success"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Session:
        def post(self, *args, **kwargs):
            return _Response()

    with pytest.raises(NoDataError):
        await async_fetch(_Session(), RESULTS_URL)
