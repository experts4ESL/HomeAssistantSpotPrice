"""Asynchronous client and data model for the smartENERGY market API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession

from .const import API_URL, DEFAULT_API_TARIFF, REQUEST_TIMEOUT


class OekoSpotError(Exception):
    """Base exception."""


class OekoSpotConnectionError(OekoSpotError):
    """The API could not be reached."""


class OekoSpotInvalidDataError(OekoSpotError):
    """The API returned invalid or unexpected data."""


class OekoSpotPriceUnavailableError(OekoSpotError):
    """No usable price intervals were returned."""


@dataclass(frozen=True, slots=True)
class PriceInterval:
    """One market-price interval."""

    start: datetime
    end: datetime
    market_price_ct_kwh: Decimal
    tariff_price_ct_kwh: Decimal


@dataclass(frozen=True, slots=True)
class PriceWindow:
    """A contiguous window of price intervals."""

    start: datetime
    end: datetime
    average: float
    total: float
    rank: int = 1


@dataclass(frozen=True, slots=True)
class PriceDataset:
    """Validated price data returned by smartENERGY."""

    tariff: str
    unit: str
    interval_minutes: int
    intervals: tuple[PriceInterval, ...]
    fetched_at: datetime
    today_complete: bool
    tomorrow_complete: bool

    def current(self, now: datetime) -> PriceInterval | None:
        """Return the interval containing now."""
        instant = now.astimezone(UTC)
        return next(
            (
                item
                for item in self.intervals
                if item.start.astimezone(UTC) <= instant < item.end.astimezone(UTC)
            ),
            None,
        )

    def next_after(self, now: datetime) -> PriceInterval | None:
        """Return the first interval starting after the current instant."""
        instant = now.astimezone(UTC)
        return next(
            (item for item in self.intervals if item.start.astimezone(UTC) > instant),
            None,
        )

    def for_date(self, day: date, timezone: ZoneInfo) -> tuple[PriceInterval, ...]:
        """Return all intervals whose local start date equals day."""
        return tuple(
            item
            for item in self.intervals
            if item.start.astimezone(timezone).date() == day
        )


class SmartEnergyApi:
    """Client for the public smartENERGY price endpoint."""

    def __init__(
        self,
        session: ClientSession,
        *,
        tariff: str = DEFAULT_API_TARIFF,
        timezone: ZoneInfo,
        handling_fee: float,
    ) -> None:
        self._session = session
        self._tariff = tariff
        self._timezone = timezone
        self._handling_fee = Decimal(str(handling_fee))

    async def async_get_prices(self) -> PriceDataset:
        """Fetch and validate current price data."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(API_URL)
                async with response:
                    if response.status != 200:
                        raise OekoSpotConnectionError(
                            f"smartENERGY returned HTTP {response.status}"
                        )
                    payload = await response.json(content_type=None)
        except (TimeoutError, ClientError) as err:
            raise OekoSpotConnectionError("Unable to reach smartENERGY") from err
        except ValueError as err:
            raise OekoSpotInvalidDataError("Response is not valid JSON") from err

        return parse_payload(
            payload,
            expected_tariff=self._tariff,
            timezone=self._timezone,
            handling_fee=self._handling_fee,
            fetched_at=datetime.now(self._timezone),
        )


def parse_payload(
    payload: Any,
    *,
    expected_tariff: str,
    timezone: ZoneInfo,
    handling_fee: Decimal,
    fetched_at: datetime,
) -> PriceDataset:
    """Validate an API payload and convert it into an immutable dataset."""
    if not isinstance(payload, dict):
        raise OekoSpotInvalidDataError("Top-level JSON value must be an object")
    tariff = payload.get("tariff")
    unit = payload.get("unit")
    interval_minutes = payload.get("interval")
    data = payload.get("data")
    if tariff != expected_tariff:
        raise OekoSpotInvalidDataError(f"Unexpected tariff: {tariff!r}")
    if unit != "ct/kWh":
        raise OekoSpotInvalidDataError(f"Unexpected unit: {unit!r}")
    if not isinstance(interval_minutes, int) or interval_minutes <= 0:
        raise OekoSpotInvalidDataError("Invalid interval length")
    if not isinstance(data, list):
        raise OekoSpotInvalidDataError("Missing price data list")

    by_start: dict[datetime, PriceInterval] = {}
    for raw in data:
        if not isinstance(raw, dict):
            raise OekoSpotInvalidDataError("Invalid item in price data")
        try:
            start = datetime.fromisoformat(raw["date"])
            value = Decimal(str(raw["value"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as err:
            raise OekoSpotInvalidDataError("Invalid price interval") from err
        if start.tzinfo is None or not value.is_finite():
            raise OekoSpotInvalidDataError(
                "Intervals require timezone and finite value"
            )
        start_utc = start.astimezone(UTC)
        start = start_utc.astimezone(timezone)
        end = (start_utc + timedelta(minutes=interval_minutes)).astimezone(timezone)
        item = PriceInterval(start, end, value, value + handling_fee)
        existing = by_start.get(start_utc)
        if existing is not None and existing.market_price_ct_kwh != value:
            raise OekoSpotInvalidDataError("Conflicting duplicate interval")
        by_start[start_utc] = item

    intervals = tuple(
        sorted(by_start.values(), key=lambda item: item.start.astimezone(UTC))
    )
    if not intervals:
        raise OekoSpotPriceUnavailableError("No price intervals available")
    for previous, current in pairwise(intervals):
        if current.start.astimezone(UTC) < previous.end.astimezone(UTC):
            raise OekoSpotInvalidDataError("Overlapping price intervals")

    today = fetched_at.astimezone(timezone).date()
    tomorrow = today + timedelta(days=1)
    return PriceDataset(
        tariff=tariff,
        unit=unit,
        interval_minutes=interval_minutes,
        intervals=intervals,
        fetched_at=fetched_at,
        today_complete=_is_day_complete(intervals, today, timezone, interval_minutes),
        tomorrow_complete=_is_day_complete(
            intervals, tomorrow, timezone, interval_minutes
        ),
    )


def _is_day_complete(
    intervals: tuple[PriceInterval, ...],
    day: date,
    timezone: ZoneInfo,
    interval_minutes: int,
) -> bool:
    """Check coverage using elapsed UTC time, including DST days."""
    local_items = [
        item for item in intervals if item.start.astimezone(timezone).date() == day
    ]
    start = datetime.combine(day, datetime.min.time(), timezone)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone)
    expected = int(
        (end.astimezone(ZoneInfo("UTC")) - start.astimezone(ZoneInfo("UTC")))
        / timedelta(minutes=interval_minutes)
    )
    return len(local_items) == expected


def day_statistics(
    dataset: PriceDataset, day: date, timezone: ZoneInfo
) -> tuple[float | None, float | None, float | None]:
    """Return minimum, maximum, and mean tariff price for a local day."""
    values = [
        float(item.tariff_price_ct_kwh)
        for item in dataset.for_date(day, timezone)
    ]
    if not values:
        return None, None, None
    return min(values), max(values), fmean(values)


def cheapest_window(
    dataset: PriceDataset, day: date, timezone: ZoneInfo, minutes: int
) -> PriceWindow | None:
    """Return the cheapest contiguous window, preferring the earlier on ties."""
    items = dataset.for_date(day, timezone)
    count = minutes // dataset.interval_minutes
    if count <= 0 or count * dataset.interval_minutes != minutes:
        return None
    candidates: list[PriceWindow] = []
    for index in range(len(items) - count + 1):
        window = items[index : index + count]
        if any(
            current.start.astimezone(UTC) != previous.end.astimezone(UTC)
            for previous, current in pairwise(window)
        ):
            continue
        values = [float(item.tariff_price_ct_kwh) for item in window]
        candidates.append(
            PriceWindow(
                start=window[0].start,
                end=window[-1].end,
                average=fmean(values),
                total=sum(values),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.average, item.start))
    winner = candidates[0]
    return PriceWindow(
        winner.start, winner.end, winner.average, winner.total, rank=1
    )


def price_level(dataset: PriceDataset, now: datetime, timezone: ZoneInfo) -> str | None:
    """Classify the current value by its rank among today's prices."""
    current = dataset.current(now)
    if current is None:
        return None
    values = sorted(
        item.tariff_price_ct_kwh
        for item in dataset.for_date(now.astimezone(timezone).date(), timezone)
    )
    if not values:
        return None
    rank = sum(value <= current.tariff_price_ct_kwh for value in values) / len(values)
    if rank <= 0.2:
        return "very_low"
    if rank <= 0.4:
        return "low"
    if rank <= 0.6:
        return "normal"
    if rank <= 0.8:
        return "high"
    return "very_high"
