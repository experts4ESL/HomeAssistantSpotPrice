"""Asynchronous client and data model for the smartENERGY market API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from statistics import fmean, pstdev
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
class PricePlateau:
    """A contiguous low- or high-price plateau."""

    kind: str
    start: datetime
    end: datetime
    average: float
    minimum: float
    maximum: float
    spread: float
    standard_deviation: float
    duration_minutes: int
    interval_count: int
    rank: int
    threshold: float
    delta_from_daily_average: float


@dataclass(frozen=True, slots=True)
class PriceCycle:
    """A price-only pairing of a low plateau followed by a high plateau."""

    charge: PricePlateau
    discharge: PricePlateau
    gross_spread: float


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
    reference_time: datetime | None = None,
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
    if interval_minutes != 15:
        raise OekoSpotInvalidDataError(
            f"Unexpected interval length: {interval_minutes!r}"
        )
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
        if (
            start_utc.minute % interval_minutes
            or start_utc.second
            or start_utc.microsecond
        ):
            raise OekoSpotInvalidDataError("Price interval is not quarter-hour aligned")
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

    today = (reference_time or fetched_at).astimezone(timezone).date()
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
    start = datetime.combine(day, datetime.min.time(), timezone)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    expected_starts: set[datetime] = set()
    cursor = start_utc
    while cursor < end_utc:
        expected_starts.add(cursor)
        cursor += timedelta(minutes=interval_minutes)
    actual_starts = {
        item.start.astimezone(UTC)
        for item in intervals
        if item.start.astimezone(timezone).date() == day
    }
    return actual_starts == expected_starts


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
    less = sum(value < current.tariff_price_ct_kwh for value in values)
    equal = sum(value == current.tariff_price_ct_kwh for value in values)
    rank = (less + equal / 2) / len(values)
    if rank <= 0.2:
        return "very_low"
    if rank <= 0.4:
        return "low"
    if rank <= 0.6:
        return "normal"
    if rank <= 0.8:
        return "high"
    return "very_high"


def chart_points(
    dataset: PriceDataset, day: date, timezone: ZoneInfo
) -> list[dict[str, str | float]]:
    """Return compact, JSON-safe chart points for a local day."""
    return [
        {
            "start": item.start.isoformat(),
            "epex_price": float(item.market_price_ct_kwh),
            "tariff_price": float(item.tariff_price_ct_kwh),
        }
        for item in dataset.for_date(day, timezone)
    ]


def _quantile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated quantile."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def find_price_plateaus(
    dataset: PriceDataset,
    day: date,
    timezone: ZoneInfo,
    *,
    kind: str,
    percentile: float,
    minimum_minutes: int,
) -> tuple[PricePlateau, ...]:
    """Find ranked contiguous low- or high-price plateaus."""
    if kind not in {"low", "high"}:
        raise ValueError("Plateau kind must be 'low' or 'high'")
    if not 0 < percentile < 1:
        raise ValueError("Percentile must be between zero and one")
    items = dataset.for_date(day, timezone)
    if not items:
        return ()
    values = [float(item.tariff_price_ct_kwh) for item in items]
    quantile = percentile if kind == "low" else 1 - percentile
    threshold = _quantile(values, quantile)
    qualifies = (
        (lambda value: value <= threshold)
        if kind == "low"
        else (lambda value: value >= threshold)
    )

    groups: list[list[PriceInterval]] = []
    current: list[PriceInterval] = []
    for item in items:
        value = float(item.tariff_price_ct_kwh)
        contiguous = (
            not current
            or current[-1].end.astimezone(UTC) == item.start.astimezone(UTC)
        )
        if qualifies(value) and contiguous:
            current.append(item)
            continue
        if current:
            groups.append(current)
            current = []
        if qualifies(value):
            current = [item]
    if current:
        groups.append(current)

    daily_average = fmean(values)
    candidates: list[PricePlateau] = []
    for group in groups:
        duration = len(group) * dataset.interval_minutes
        if duration < minimum_minutes:
            continue
        prices = [float(item.tariff_price_ct_kwh) for item in group]
        average = fmean(prices)
        candidates.append(
            PricePlateau(
                kind=kind,
                start=group[0].start,
                end=group[-1].end,
                average=average,
                minimum=min(prices),
                maximum=max(prices),
                spread=max(prices) - min(prices),
                standard_deviation=pstdev(prices),
                duration_minutes=duration,
                interval_count=len(group),
                rank=0,
                threshold=threshold,
                delta_from_daily_average=average - daily_average,
            )
        )
    candidates.sort(
        key=(
            (lambda item: (item.average, -item.duration_minutes, item.start))
            if kind == "low"
            else (lambda item: (-item.average, -item.duration_minutes, item.start))
        )
    )
    return tuple(
        PricePlateau(
            kind=item.kind,
            start=item.start,
            end=item.end,
            average=item.average,
            minimum=item.minimum,
            maximum=item.maximum,
            spread=item.spread,
            standard_deviation=item.standard_deviation,
            duration_minutes=item.duration_minutes,
            interval_count=item.interval_count,
            rank=rank,
            threshold=item.threshold,
            delta_from_daily_average=item.delta_from_daily_average,
        )
        for rank, item in enumerate(candidates, start=1)
    )


def best_price_cycle(
    low_plateaus: tuple[PricePlateau, ...],
    high_plateaus: tuple[PricePlateau, ...],
) -> PriceCycle | None:
    """Return the largest gross price spread with charge before discharge."""
    candidates = [
        PriceCycle(
            charge=low,
            discharge=high,
            gross_spread=high.average - low.average,
        )
        for low in low_plateaus
        for high in high_plateaus
        if low.end.astimezone(UTC) <= high.start.astimezone(UTC)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.gross_spread,
            item.charge.duration_minutes + item.discharge.duration_minutes,
            -item.charge.start.timestamp(),
        ),
    )


def plateau_to_dict(plateau: PricePlateau) -> dict[str, str | int | float]:
    """Serialize a plateau as compact entity attributes."""
    return {
        "kind": plateau.kind,
        "start": plateau.start.isoformat(),
        "end": plateau.end.isoformat(),
        "duration_minutes": plateau.duration_minutes,
        "interval_count": plateau.interval_count,
        "average_price": round(plateau.average, 4),
        "minimum_price": round(plateau.minimum, 4),
        "maximum_price": round(plateau.maximum, 4),
        "price_spread": round(plateau.spread, 4),
        "price_stddev": round(plateau.standard_deviation, 4),
        "rank": plateau.rank,
        "threshold": round(plateau.threshold, 4),
        "delta_from_daily_average": round(
            plateau.delta_from_daily_average, 4
        ),
    }


def dataset_to_dict(dataset: PriceDataset) -> dict[str, Any]:
    """Serialize a dataset for Home Assistant storage."""
    return {
        "tariff": dataset.tariff,
        "unit": dataset.unit,
        "interval": dataset.interval_minutes,
        "fetched_at": dataset.fetched_at.isoformat(),
        "data": [
            {
                "date": item.start.isoformat(),
                "value": str(item.market_price_ct_kwh),
            }
            for item in dataset.intervals
        ],
    }


def dataset_from_dict(
    stored: Any,
    *,
    expected_tariff: str,
    timezone: ZoneInfo,
    handling_fee: Decimal,
    reference_time: datetime,
) -> PriceDataset:
    """Restore and revalidate a stored dataset."""
    if not isinstance(stored, dict):
        raise OekoSpotInvalidDataError("Stored dataset must be an object")
    try:
        fetched_at = datetime.fromisoformat(stored["fetched_at"])
    except (KeyError, TypeError, ValueError) as err:
        raise OekoSpotInvalidDataError("Stored fetch timestamp is invalid") from err
    if fetched_at.tzinfo is None:
        raise OekoSpotInvalidDataError("Stored fetch timestamp requires a timezone")
    payload = {
        "tariff": stored.get("tariff"),
        "unit": stored.get("unit"),
        "interval": stored.get("interval"),
        "data": stored.get("data"),
    }
    return parse_payload(
        payload,
        expected_tariff=expected_tariff,
        timezone=timezone,
        handling_fee=handling_fee,
        fetched_at=fetched_at,
        reference_time=reference_time,
    )
