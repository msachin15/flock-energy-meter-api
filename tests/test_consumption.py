"""Timestamp parsing, nulls instead of zeroes, and calendar order.

String-sorting the portal's DD/MM/YYYY values would put 01/02 before 31/01.
These tests require the real calendar order.
"""

from datetime import date

import pytest

from app.normalize import filter_readings_by_date, parse_consumption
from app.services.meter_service import MeterService
from app.cache import TtlCache
from tests.fakes import RecordingPortal
from tests.samples import meter_record


def test_timestamps_are_naive_and_numbers_are_converted():
    """DD/MM/YYYY HH:mm becomes a naive ISO time. Zero stays zero. Blanks become null."""

    readings, rejected = parse_consumption(
        [
            {"timestamp": "24/06/2026 00:00", "kwh": "48439.16", "kvah": "52314.29", "voltR": "229"},
            {"timestamp": "24/06/2026 00:30", "kwh": "0", "kvah": "", "voltR": None},
        ]
    )

    assert rejected == []
    assert readings[0].recorded_at == "2026-06-24T00:00:00"
    assert readings[0].source_timestamp == "24/06/2026 00:00"
    assert "Z" not in readings[0].recorded_at
    assert "+" not in readings[0].recorded_at
    assert readings[0].kwh == pytest.approx(48439.16)
    assert readings[0].kvah == pytest.approx(52314.29)
    assert readings[0].volt_r == 229.0
    assert readings[1].kwh == 0.0
    assert readings[1].kvah is None
    assert readings[1].volt_r is None


def test_malformed_rows_are_reported_and_not_coerced_to_zero():
    """Bad timestamps are rejected. A bad number on a good timestamp is null, not zero."""

    readings, rejected = parse_consumption(
        [
            "not-a-row",
            {"timestamp": "2026-06-24T00:00:00", "kwh": "10"},
            {"timestamp": "32/01/2026 00:00", "kwh": "10"},
            {"timestamp": "24/06/2026 01:00", "kwh": "nope", "kvah": "n/a", "voltR": "bad"},
        ]
    )

    assert [item.reason for item in rejected] == ["not_an_object", "invalid_timestamp", "invalid_timestamp"]
    assert rejected[1].source_timestamp == "2026-06-24T00:00:00"
    assert len(readings) == 1
    assert readings[0].kwh is None
    assert readings[0].kvah is None
    assert readings[0].volt_r is None
    assert readings[0].recorded_at == "2026-06-24T01:00:00"


def test_date_filter_is_inclusive_and_order_follows_the_calendar():
    """Sort by calendar date. String order of DD/MM/YYYY would be wrong."""

    readings, rejected = parse_consumption(
        [
            {"timestamp": "01/02/2026 00:00", "kwh": "3", "kvah": "3", "voltR": "230"},
            {"timestamp": "31/01/2026 10:00", "kwh": "2", "kvah": "2", "voltR": "230"},
            {"timestamp": "02/01/2026 00:00", "kwh": "1", "kvah": "1", "voltR": "230"},
            {"kwh": "9"},
        ]
    )
    selected = filter_readings_by_date(readings, date(2026, 1, 31), date(2026, 1, 31))
    ordered = sorted(selected, key=lambda item: item.recorded_at)
    full = sorted(readings, key=lambda item: item.recorded_at)

    assert [item.source_timestamp for item in full] == [
        "02/01/2026 00:00",
        "31/01/2026 10:00",
        "01/02/2026 00:00",
    ]
    assert [item.source_timestamp for item in ordered] == ["31/01/2026 10:00"]
    assert len(rejected) == 1


def test_service_returns_chronological_readings_and_keeps_rejected_rows():
    """The date filter drops out-of-range readings and still reports rows that could not be timed."""

    portal = RecordingPortal(
        export=[meter_record()],
        energy={
            "J100000": [
                {"timestamp": "01/02/2026 00:00", "kwh": "3", "kvah": "3", "voltR": "1"},
                {"timestamp": "bad", "kwh": "0"},
                {"timestamp": "02/01/2026 00:00", "kwh": "1", "kvah": "1", "voltR": "1"},
            ]
        },
    )
    service = MeterService(portal, TtlCache(300))
    result = service.get_consumption("J100000", date(2026, 1, 1), date(2026, 1, 31))

    assert result.timezone is None
    assert [item.source_timestamp for item in result.readings] == ["02/01/2026 00:00"]
    assert result.rejected[0].reason == "invalid_timestamp"
    assert "YYYY-MM-DDTHH:mm:ss" in result.recorded_at_convention
