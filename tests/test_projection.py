"""Tests for rolling stale council dates forward.

The council's page keeps serving a collection date for days after it has
passed. Left alone that reports a negative "days until" and, far worse, never
matches today or tomorrow, so the reminder for the real collection never fires.
"""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.north_herts_bins.api import (
    BinCollection,
    BinData,
    cycle_to_days,
    parse,
    project_collection,
    project_collections,
    stale_collections,
)


@pytest.mark.parametrize(
    ("cycle", "expected"),
    [
        # Cycles the council actually uses.
        ("Every Wednesday", 7),
        ("Every 3rd Wednesday", 21),
        ("Every Friday fortnightly", 14),
        # Plausible variants.
        ("Every Monday", 7),
        ("every 2nd Tuesday", 14),
        ("Every other Thursday", 14),
        ("Every fourth Friday", 28),
        ("Weekly", 7),
        ("Every week", 7),
        ("Fortnightly", 14),
        ("Every 14 days", 14),
        # Not understood: must return None rather than guess.
        (None, None),
        ("", None),
        ("On request", None),
        ("Twice a month", None),
    ],
)
def test_cycle_to_days(cycle: str | None, expected: int | None) -> None:
    """Cycle text maps to an interval, or to None when unclear."""
    assert cycle_to_days(cycle) == expected


def test_third_wednesday_means_every_three_weeks() -> None:
    """"Every 3rd Wednesday" is a 21 day rota, not the 3rd Wednesday of a month.

    All three wheeled bins share the phrase while falling on 12, 19 and 26
    August, so it can only mean every three weeks, offset by a week each.
    """
    assert cycle_to_days("Every 3rd Wednesday") == 21


def test_future_date_is_left_alone() -> None:
    """A date that has not passed is returned untouched."""
    c = BinCollection("Food Waste", "Brown caddy", date(2026, 8, 19), "Every Wednesday")
    assert project_collection(c, date(2026, 8, 17)) is c


def test_today_is_not_projected() -> None:
    """Collection day itself must not roll forward."""
    c = BinCollection("Food Waste", "Brown caddy", date(2026, 8, 19), "Every Wednesday")
    out = project_collection(c, date(2026, 8, 19))
    assert out.next_collection == date(2026, 8, 19)
    assert out.projected is False


def test_weekly_bin_rolls_to_the_next_week() -> None:
    """The reported screenshot case: weekly food waste stuck on 12 August."""
    c = BinCollection("Food Waste", "Brown caddy", date(2026, 8, 12), "Every Wednesday")
    out = project_collection(c, date(2026, 8, 17))
    assert out.next_collection == date(2026, 8, 19)
    assert out.projected is True
    assert out.reported_collection == date(2026, 8, 12)


def test_three_weekly_bin_rolls_a_full_cycle() -> None:
    """Cardboard on a 21 day rota jumps to 2 September, not 19 August."""
    c = BinCollection(
        "Cardboard & Paper", "Blue lid bin", date(2026, 8, 12), "Every 3rd Wednesday"
    )
    out = project_collection(c, date(2026, 8, 17))
    assert out.next_collection == date(2026, 9, 2)
    assert out.reported_collection == date(2026, 8, 12)


def test_projection_preserves_weekday() -> None:
    """Projecting in whole weeks keeps the collection on the same weekday."""
    c = BinCollection("Garden Waste", "Brown lid bin", date(2026, 7, 10), "Every Friday fortnightly")
    out = project_collection(c, date(2026, 8, 17))
    assert out.next_collection.strftime("%A") == "Friday"
    assert out.next_collection >= date(2026, 8, 17)


def test_projection_skips_many_missed_cycles() -> None:
    """A long outage still lands on the next future date, not the next cycle."""
    c = BinCollection("Food Waste", "Brown caddy", date(2026, 1, 7), "Every Wednesday")
    out = project_collection(c, date(2026, 8, 17))
    assert out.next_collection == date(2026, 8, 19)


def test_unparseable_cycle_is_not_invented() -> None:
    """Without a usable cycle the date is left as reported."""
    c = BinCollection("Mystery Bin", None, date(2026, 8, 12), "On request")
    out = project_collection(c, date(2026, 8, 17))
    assert out.next_collection == date(2026, 8, 12)
    assert out.projected is False


def test_project_collections_reorders_by_new_dates() -> None:
    """Projection can change which bin is due soonest, so order is rebuilt."""
    collections = [
        BinCollection("Cardboard & Paper", "Blue", date(2026, 8, 12), "Every 3rd Wednesday"),
        BinCollection("Food Waste", "Brown caddy", date(2026, 8, 12), "Every Wednesday"),
        BinCollection("Non-Recyclable Waste", "Purple", date(2026, 8, 19), "Every 3rd Wednesday"),
        BinCollection("Garden Waste", "Brown lid", date(2026, 8, 21), "Every Friday fortnightly"),
        BinCollection("Mixed Recycling", "Black", date(2026, 8, 26), "Every 3rd Wednesday"),
    ]
    out = project_collections(collections, date(2026, 8, 17))

    assert [(c.name, c.next_collection) for c in out] == [
        ("Food Waste", date(2026, 8, 19)),
        ("Non-Recyclable Waste", date(2026, 8, 19)),
        ("Garden Waste", date(2026, 8, 21)),
        ("Mixed Recycling", date(2026, 8, 26)),
        ("Cardboard & Paper", date(2026, 9, 2)),
    ]
    # No date may remain in the past.
    assert all(c.next_collection >= date(2026, 8, 17) for c in out)


def test_stale_collections_reports_only_past_dates(page_fragment: str) -> None:
    """Staleness detection drives the warning logged on refresh."""
    data = parse(page_fragment)
    assert [c.name for c in stale_collections(data, date(2026, 8, 17))] == [
        "Cardboard & Paper",
        "Food Waste",
    ]
    assert stale_collections(data, date(2026, 8, 1)) == []


def test_parse_does_not_project(page_fragment: str) -> None:
    """Parsing stays faithful to the page; projection is a separate step."""
    data = parse(page_fragment)
    by_name = {c.name: c for c in data.collections}
    assert by_name["Food Waste"].next_collection == date(2026, 8, 12)
    assert by_name["Food Waste"].projected is False


def test_end_to_end_from_the_reported_page(page_fragment: str) -> None:
    """The full screenshot scenario, from real page to corrected dates."""
    data = parse(page_fragment)
    out = project_collections(data.collections, date(2026, 8, 17))
    by_name = {c.name: c for c in out}

    assert by_name["Food Waste"].next_collection == date(2026, 8, 19)
    assert by_name["Cardboard & Paper"].next_collection == date(2026, 9, 2)
    # Untouched bins keep exactly what the council said.
    assert by_name["Non-Recyclable Waste"].next_collection == date(2026, 8, 19)
    assert by_name["Non-Recyclable Waste"].projected is False
    assert by_name["Garden Waste"].next_collection == date(2026, 8, 21)
    assert by_name["Mixed Recycling"].next_collection == date(2026, 8, 26)
