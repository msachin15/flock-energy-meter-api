"""Turn portal payloads into API models.

Invalid measurements become null. They are not replaced with zero.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.constants import HIERARCHY_LEVELS
from app.errors import PortalDataError
from app.schemas import (
    ConsumptionReading,
    HierarchyNode,
    Meter,
    NetworkHierarchy,
    RejectedReading,
    Transformer,
)

_PORTAL_TIMESTAMP = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})$")
_RECORDED_AT = "%Y-%m-%dT%H:%M:%S"


def parse_number(value: Any) -> float | None:
    """Parse a portal measurement. Blank, non-numeric, and non-finite values are null.

    Booleans are rejected on purpose: `bool` is a subclass of `int`, and `True` must not become 1.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        if not parsed.is_finite():
            return None
        return float(parsed)
    return None


def as_str(value: Any) -> str | None:
    """Keep real strings, including empty ones. Do not turn numbers into text."""

    if isinstance(value, str):
        return value
    return None


def extract_export_records(payload: Any) -> list[Any]:
    """Accept the live envelope `{data, total}` and the downloaded JSON array.

    The array is what the portal UI saves. The service still calls the live endpoint.
    """

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    raise PortalDataError("Meter export was neither a list nor an envelope with a data list.")


def export_total(payload: Any) -> int | None:
    """Read total from an envelope. A bare array has no total and returns None."""

    if not isinstance(payload, dict) or "total" not in payload:
        return None
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise PortalDataError("Meter export total was not a non-negative integer.")
    return total


def normalize_meter(record: Any) -> Meter | None:
    """Map one export object to a Meter. Returns None when meterId is missing or blank."""

    if not isinstance(record, dict):
        return None
    meter_id = as_str(record.get("meterId"))
    if meter_id is None or not meter_id.strip():
        return None
    latitude, longitude = _coordinates(record.get("geo"))
    return Meter(
        meter_id=meter_id.strip(),
        serial_no=as_str(record.get("serialNo")),
        make=as_str(record.get("make")),
        phase_type=as_str(record.get("phaseType")),
        install_status=as_str(record.get("installStatus")),
        install_type=as_str(record.get("installType")),
        build=as_str(record.get("build")),
        dt_code=as_str(record.get("dtCode")),
        hierarchy=_hierarchy(record.get("hierarchy")),
        latitude=latitude,
        longitude=longitude,
    )


def normalize_transformer(record: Any) -> Transformer | None:
    """Map one transformer row. Returns None when code is missing. Bad capacity becomes null."""

    if not isinstance(record, dict):
        return None
    code = as_str(record.get("code"))
    if code is None or not code.strip():
        return None
    return Transformer(
        code=code.strip(),
        name=as_str(record.get("name")),
        feeder_code=as_str(record.get("feederCode")),
        capacity_kva=parse_number(record.get("capacityKva")),
    )


def parse_portal_timestamp(value: str) -> datetime | None:
    """Accept only DD/MM/YYYY HH:mm. Other shapes, including ISO strings, are rejected."""

    match = _PORTAL_TIMESTAMP.fullmatch(value.strip())
    if match is None:
        return None
    day, month, year, hour, minute = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def parse_consumption(records: list[Any]) -> tuple[list[ConsumptionReading], list[RejectedReading]]:
    """Split rows into timed readings and rejected rows. Bad numbers become null, not zero."""

    readings: list[ConsumptionReading] = []
    rejected: list[RejectedReading] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            rejected.append(RejectedReading(index=index, reason="not_an_object", source_timestamp=None))
            continue
        raw_timestamp = record.get("timestamp")
        parsed = parse_portal_timestamp(raw_timestamp) if isinstance(raw_timestamp, str) else None
        if parsed is None:
            rejected.append(
                RejectedReading(
                    index=index,
                    reason="invalid_timestamp",
                    source_timestamp=raw_timestamp if isinstance(raw_timestamp, str) else None,
                )
            )
            continue
        readings.append(
            ConsumptionReading(
                recorded_at=parsed.strftime(_RECORDED_AT),
                source_timestamp=raw_timestamp,
                kwh=parse_number(record.get("kwh")),
                kvah=parse_number(record.get("kvah")),
                volt_r=parse_number(record.get("voltR")),
            )
        )
    return readings, rejected


def filter_readings_by_date(
    readings: list[ConsumptionReading],
    start_date: date | None,
    end_date: date | None,
) -> list[ConsumptionReading]:
    """Keep readings whose calendar date is inside the inclusive range. Rejected rows are not passed here."""

    selected: list[ConsumptionReading] = []
    for reading in readings:
        day = datetime.strptime(reading.recorded_at, _RECORDED_AT).date()
        if start_date is not None and day < start_date:
            continue
        if end_date is not None and day > end_date:
            continue
        selected.append(reading)
    return selected


def filter_meters(meters: list[Meter], query: str | None) -> list[Meter]:
    """Case-insensitive substring on meter id or serial number. Blank query returns every meter."""

    if query is None or not query.strip():
        return list(meters)
    needle = query.strip().casefold()
    return [
        meter
        for meter in meters
        if needle in meter.meter_id.casefold() or needle in (meter.serial_no or "").casefold()
    ]


def find_meter(meters: list[Meter], meter_id: str) -> Meter | None:
    """Exact meter id first, then a case-insensitive match."""

    return _find(meters, meter_id, lambda meter: meter.meter_id)


def find_transformer(transformers: list[Transformer], code: str) -> Transformer | None:
    """Exact transformer code first, then a case-insensitive match."""

    return _find(transformers, code, lambda item: item.code)


def _find(items: list[Any], identifier: str, read_id) -> Any | None:
    """Shared lookup. Exact text wins over a case-folded match."""

    target = identifier.strip()
    for item in items:
        if read_id(item) == target:
            return item
    folded = target.casefold()
    for item in items:
        if read_id(item).casefold() == folded:
            return item
    return None


def _coordinates(geo: Any) -> tuple[float | None, float | None]:
    """Keep a point only when both values are finite. A single number is not a location."""

    if not isinstance(geo, dict):
        return None, None
    latitude = parse_number(geo.get("lat"))
    longitude = parse_number(geo.get("lng"))
    if latitude is None or longitude is None:
        return None, None
    return latitude, longitude


def _hierarchy(raw: Any) -> NetworkHierarchy:
    """Missing level becomes null. A present level with code "" stays an empty string."""

    if not isinstance(raw, dict):
        raw = {}
    nodes: dict[str, HierarchyNode | None] = {}
    for level in HIERARCHY_LEVELS:
        node = raw.get(level) if level in raw else None
        if level not in raw or node is None:
            nodes[level] = None
            continue
        if not isinstance(node, dict):
            nodes[level] = None
            continue
        nodes[level] = HierarchyNode(name=as_str(node.get("name")), code=as_str(node.get("code")))
    return NetworkHierarchy(**nodes)
