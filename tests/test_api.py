"""Tests for parsing and price calculations."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.oeko_spot.api import (
    OekoSpotInvalidDataError,
    best_price_cycle,
    chart_points,
    cheapest_window,
    dataset_from_dict,
    dataset_to_dict,
    day_statistics,
    find_price_plateaus,
    parse_payload,
    plateau_to_dict,
    price_level,
)

VIENNA = ZoneInfo("Europe/Vienna")


def payload(start: datetime, values: list[float], interval: int = 15) -> dict:
    """Build a representative API payload."""
    return {
        "tariff": "EPEXSPOTAT",
        "unit": "ct/kWh",
        "interval": interval,
        "data": [
            {
                "date": (start + timedelta(minutes=index * interval)).isoformat(),
                "value": value,
            }
            for index, value in enumerate(values)
        ],
    }


def parse(raw: dict, fetched_at: datetime):
    return parse_payload(
        raw,
        expected_tariff="EPEXSPOTAT",
        timezone=VIENNA,
        handling_fee=Decimal("1.8"),
        fetched_at=fetched_at,
    )


def test_fee_current_and_next_interval() -> None:
    start = datetime(2026, 7, 24, 0, 0, tzinfo=VIENNA)
    dataset = parse(payload(start, [10, 20, 30, 40]), start)
    current = dataset.current(start + timedelta(minutes=29))
    following = dataset.next_after(start + timedelta(minutes=29))
    assert current is not None
    assert current.market_price_ct_kwh == Decimal("20")
    assert current.tariff_price_ct_kwh == Decimal("21.8")
    assert following is not None
    assert following.tariff_price_ct_kwh == Decimal("31.8")


def test_daily_statistics_and_cheapest_window() -> None:
    start = datetime(2026, 7, 24, 0, 0, tzinfo=VIENNA)
    dataset = parse(payload(start, [4, 1, 1, 1, 1, 9, 9, 9]), start)
    minimum, maximum, average = day_statistics(dataset, start.date(), VIENNA)
    assert minimum == pytest.approx(2.8)
    assert maximum == pytest.approx(10.8)
    assert average == pytest.approx(6.175)
    window = cheapest_window(dataset, start.date(), VIENNA, 60)
    assert window is not None
    assert window.start == start + timedelta(minutes=15)
    assert window.average == pytest.approx(2.8)


def test_price_level_uses_daily_rank() -> None:
    start = datetime(2026, 7, 24, 0, 0, tzinfo=VIENNA)
    dataset = parse(payload(start, list(range(1, 11))), start)
    assert price_level(dataset, start, VIENNA) == "very_low"
    assert (
        price_level(dataset, start + timedelta(minutes=9 * 15), VIENNA)
        == "very_high"
    )


def test_equal_prices_have_normal_level() -> None:
    start = datetime(2026, 7, 24, 0, 0, tzinfo=VIENNA)
    dataset = parse(payload(start, [5] * 8), start)
    assert price_level(dataset, start, VIENNA) == "normal"


@pytest.mark.parametrize(
    ("day", "count"),
    [
        (datetime(2026, 3, 29, 0, 0, tzinfo=VIENNA), 92),
        (datetime(2026, 7, 24, 0, 0, tzinfo=VIENNA), 96),
    ],
)
def test_complete_day_including_dst(day: datetime, count: int) -> None:
    # Generate elapsed-time intervals in UTC so the nonexistent DST hour is skipped.
    utc_start = day.astimezone(ZoneInfo("UTC"))
    dates = [
        (utc_start + timedelta(minutes=15 * index)).astimezone(VIENNA)
        for index in range(count)
    ]
    raw = {
        "tariff": "EPEXSPOTAT",
        "unit": "ct/kWh",
        "interval": 15,
        "data": [{"date": item.isoformat(), "value": 1} for item in dates],
    }
    assert parse(raw, day).today_complete is True


def test_complete_100_interval_winter_day() -> None:
    day = datetime(2026, 10, 25, 0, 0, tzinfo=VIENNA)
    utc_start = day.astimezone(ZoneInfo("UTC"))
    raw = {
        "tariff": "EPEXSPOTAT",
        "unit": "ct/kWh",
        "interval": 15,
        "data": [
            {
                "date": (
                    utc_start + timedelta(minutes=15 * index)
                ).astimezone(VIENNA).isoformat(),
                "value": 1,
            }
            for index in range(100)
        ],
    }
    assert parse(raw, day).today_complete is True


@pytest.mark.parametrize(
    "change",
    [
        {"tariff": "WRONG"},
        {"unit": "EUR/MWh"},
        {"interval": 0},
        {"data": "not-a-list"},
    ],
)
def test_invalid_metadata(change: dict) -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    raw = payload(start, [1])
    raw.update(change)
    with pytest.raises(OekoSpotInvalidDataError):
        parse(raw, start)


def test_non_quarter_hour_interval_is_rejected() -> None:
    start = datetime(2026, 7, 24, 0, 7, tzinfo=VIENNA)
    with pytest.raises(OekoSpotInvalidDataError):
        parse(payload(start, [1]), start)


def test_non_15_minute_resolution_is_rejected() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    with pytest.raises(OekoSpotInvalidDataError):
        parse(payload(start, [1], interval=30), start)


def test_conflicting_duplicate_is_rejected() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    raw = payload(start, [1])
    raw["data"].append({"date": start.isoformat(), "value": 2})
    with pytest.raises(OekoSpotInvalidDataError):
        parse(raw, start)


def test_stored_dataset_round_trip_recalculates_fee() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    original = parse(payload(start, [1, 2]), start)
    restored = dataset_from_dict(
        dataset_to_dict(original),
        expected_tariff="EPEXSPOTAT",
        timezone=VIENNA,
        handling_fee=Decimal("2.5"),
        reference_time=start,
    )
    assert restored.fetched_at == original.fetched_at
    assert restored.intervals[0].tariff_price_ct_kwh == Decimal("3.5")


def test_chart_points_are_json_safe() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    dataset = parse(payload(start, [1, 2]), start)
    points = chart_points(dataset, start.date(), VIENNA)
    assert points == [
        {
            "start": "2026-07-24T00:00:00+02:00",
            "epex_price": 1.0,
            "tariff_price": 2.8,
        },
        {
            "start": "2026-07-24T00:15:00+02:00",
            "epex_price": 2.0,
            "tariff_price": 3.8,
        },
    ]


def test_low_and_high_price_plateaus_and_cycle() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    values = [10, 10, 1, 1, 1, 1, 10, 10, 20, 20, 20, 20, 10, 10, 10, 10]
    dataset = parse(payload(start, values), start)
    low = find_price_plateaus(
        dataset,
        start.date(),
        VIENNA,
        kind="low",
        percentile=0.25,
        minimum_minutes=60,
    )
    high = find_price_plateaus(
        dataset,
        start.date(),
        VIENNA,
        kind="high",
        percentile=0.25,
        minimum_minutes=60,
    )
    assert len(low) == 1
    assert low[0].start == start + timedelta(minutes=30)
    assert low[0].duration_minutes == 60
    assert low[0].average == pytest.approx(2.8)
    assert len(high) == 1
    assert high[0].start == start + timedelta(hours=2)
    assert high[0].average == pytest.approx(21.8)
    cycle = best_price_cycle(low, high)
    assert cycle is not None
    assert cycle.gross_spread == pytest.approx(19.0)
    assert plateau_to_dict(low[0])["rank"] == 1


def test_price_cycle_requires_low_before_high() -> None:
    start = datetime(2026, 7, 24, tzinfo=VIENNA)
    values = [20, 20, 20, 20, 10, 10, 1, 1, 1, 1, 10, 10]
    dataset = parse(payload(start, values), start)
    low = find_price_plateaus(
        dataset,
        start.date(),
        VIENNA,
        kind="low",
        percentile=0.34,
        minimum_minutes=60,
    )
    high = find_price_plateaus(
        dataset,
        start.date(),
        VIENNA,
        kind="high",
        percentile=0.34,
        minimum_minutes=60,
    )
    assert best_price_cycle(low, high) is None


def test_shifted_full_count_is_not_complete() -> None:
    day = datetime(2026, 7, 24, tzinfo=VIENNA)
    raw = payload(day, [1] * 96)
    raw["data"].pop(4)
    raw["data"].append(
        {
            "date": datetime(2026, 7, 25, 0, 0, tzinfo=VIENNA).isoformat(),
            "value": 1,
        }
    )
    assert parse(raw, day).today_complete is False
