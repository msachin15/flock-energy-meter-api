"""Meter queries over a cached bulk export, plus per-meter location and history."""

from __future__ import annotations

import logging
from datetime import date

from app.cache import TtlCache
from app.constants import CONSUMPTION_INTERPRETATION, MAX_PAGE_SIZE, RECORDED_AT_CONVENTION
from app.errors import (
    InvalidQuery,
    LocationUnavailable,
    NotFoundError,
    PortalDataError,
    PortalUpstreamError,
    safe_identifier,
)
from app.normalize import (
    filter_meters,
    filter_readings_by_date,
    find_meter,
    normalize_meter,
    parse_consumption,
    parse_number,
)
from app.pagination import paginate
from app.portal_client import PortalClient
from app.schemas import ConsumptionResponse, Meter, MeterLocation, MeterPage

logger = logging.getLogger("flock_energy.meters")


class MeterService:
    def __init__(self, portal: PortalClient, cache: TtlCache) -> None:
        """Hold the portal client and the meter-export cache."""

        self._portal = portal
        self._cache = cache

    def list_meters(self, query: str | None, page: int, page_size: int) -> MeterPage:
        """Filter the cached export, then page. `total` is the match count, not the catalog size."""

        _check_page(page, page_size)
        matched = filter_meters(self._meters(), query)
        rows, pagination = paginate(matched, page, page_size)
        return MeterPage(data=[row.model_copy(deep=True) for row in rows], pagination=pagination)

    def get_meter(self, meter_id: str) -> Meter:
        """Look up one meter. The returned copy is not the cached object."""

        found = find_meter(self._meters(), meter_id)
        if found is None:
            raise NotFoundError("not_found", f"Meter '{safe_identifier(meter_id)}' was not found.")
        return found.model_copy(deep=True)

    def get_location(self, meter_id: str) -> MeterLocation:
        """Use export geo when both numbers exist. Call /geo only for the other meters."""

        meter = self.get_meter(meter_id)
        if meter.latitude is not None and meter.longitude is not None:
            return MeterLocation(
                meter_id=meter.meter_id,
                latitude=meter.latitude,
                longitude=meter.longitude,
                source="export",
            )
        try:
            raw = self._portal.fetch_geo(meter.meter_id)
        except PortalUpstreamError as exc:
            if exc.status_code == 404:
                raise LocationUnavailable(meter.meter_id) from exc
            raise
        latitude = parse_number(raw.get("latitude"))
        longitude = parse_number(raw.get("longitude"))
        if latitude is None or longitude is None:
            raise LocationUnavailable(meter.meter_id)
        return MeterLocation(
            meter_id=meter.meter_id,
            latitude=latitude,
            longitude=longitude,
            source="geo_endpoint",
        )

    def get_consumption(
        self,
        meter_id: str,
        start_date: date | None,
        end_date: date | None,
    ) -> ConsumptionResponse:
        """Load history for a known meter, filter by date, and sort by recorded_at."""

        if start_date is not None and end_date is not None and end_date < start_date:
            raise InvalidQuery("invalid_date_range", "end_date must be on or after start_date.")
        meter = self.get_meter(meter_id)
        try:
            raw_readings = self._portal.fetch_energy(meter.meter_id)
        except PortalUpstreamError as exc:
            if exc.status_code == 404:
                raise NotFoundError(
                    "not_found",
                    f"Consumption for meter '{safe_identifier(meter.meter_id)}' was not found.",
                ) from exc
            raise
        readings, rejected = parse_consumption(raw_readings)
        # Date filters apply only to parsed rows. Rejected rows have no usable timestamp,
        # so they stay on the response instead of being dropped.
        selected = filter_readings_by_date(readings, start_date, end_date)
        return ConsumptionResponse(
            meter_id=meter.meter_id,
            timezone=None,
            recorded_at_convention=RECORDED_AT_CONVENTION,
            interpretation=CONSUMPTION_INTERPRETATION,
            readings=sorted(selected, key=lambda reading: reading.recorded_at),
            rejected=rejected,
        )

    def _meters(self) -> list[Meter]:
        """Cached normalized export. The first caller loads it; later callers reuse it until the TTL."""

        return self._cache.get_or_load(self._load)

    def _load(self) -> list[Meter]:
        """Normalize the export. Skip blank ids and duplicate ids. Fail if every row was unusable."""

        raw_records = self._portal.fetch_meter_export()
        meters: list[Meter] = []
        seen: set[str] = set()
        skipped = 0
        duplicates = 0
        for record in raw_records:
            meter = normalize_meter(record)
            if meter is None:
                skipped += 1
                continue
            key = meter.meter_id.casefold()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            meters.append(meter)
        if skipped:
            logger.warning("Skipped %s meter records without a usable meter id", skipped)
        if duplicates:
            logger.warning("Skipped %s duplicate meter ids", duplicates)
        if raw_records and not meters:
            raise PortalDataError("Meter export contained no usable meter records.")
        return meters


def _check_page(page: int, page_size: int) -> None:
    """Reject a non-positive page or a page size above the documented maximum."""

    if page < 1 or page_size < 1:
        raise InvalidQuery("invalid_pagination", "page and page_size must be positive integers.")
    if page_size > MAX_PAGE_SIZE:
        raise InvalidQuery("invalid_pagination", f"page_size cannot exceed {MAX_PAGE_SIZE}.")
