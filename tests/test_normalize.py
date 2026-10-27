"""Export shapes, blank hierarchy codes, and coordinates. Fixtures are a few synthetic meters."""

import pytest

from app.errors import PortalDataError
from app.normalize import (
    extract_export_records,
    normalize_meter,
    normalize_transformer,
    parse_consumption,
    parse_number,
)
from tests.samples import meter_record, transformer_record


def test_export_parsing_accepts_envelope_and_downloaded_array():
    """Both the live envelope and the downloaded array yield the same records."""

    record = meter_record()
    assert extract_export_records([record]) == [record]
    assert extract_export_records({"data": [record], "total": 1}) == [record]


def test_export_parsing_rejects_an_unexpected_shape():
    """A JSON object without a data list is a portal data error."""

    with pytest.raises(PortalDataError):
        extract_export_records({"meters": []})


def test_meter_normalization_preserves_export_fields_and_blank_hierarchy_codes():
    """Empty hierarchy code and name stay empty. A missing level is null."""

    record = meter_record()
    record["hierarchy"] = {
        **record["hierarchy"],
        "circle": {"name": "Circle 6", "code": ""},
        "feeder": {"name": "", "code": "F-003"},
    }
    del record["hierarchy"]["subdivision"]
    meter = normalize_meter(record)

    assert meter is not None
    assert meter.meter_id == "J100000"
    assert meter.serial_no == "SE33962"
    assert meter.install_type == "Whole Current"
    assert meter.build == "legacy"
    assert meter.dt_code == "DT-001"
    assert meter.hierarchy.circle is not None
    assert meter.hierarchy.circle.code == ""
    assert meter.hierarchy.circle.name == "Circle 6"
    assert meter.hierarchy.feeder is not None
    assert meter.hierarchy.feeder.name == ""
    assert meter.hierarchy.feeder.code == "F-003"
    assert meter.hierarchy.subdivision is None
    assert meter.latitude == 26.9
    assert meter.longitude == 75.8


def test_meter_without_an_id_is_unusable_and_missing_hierarchy_is_empty():
    """No meterId means the row is dropped. A null hierarchy does not drop the meter."""

    assert normalize_meter({"serialNo": "SE1"}) is None
    meter = normalize_meter(meter_record(hierarchy=None, installType=None, build=None))
    assert meter is not None
    assert meter.hierarchy.zone is None
    assert meter.install_type is None
    assert meter.build is None


def test_coordinates_normalize_numbers_and_numeric_strings():
    """Numbers and numeric strings both become floats. A partial or invalid point becomes null."""

    numeric = normalize_meter(meter_record(geo={"lat": 26.5, "lng": 75.5}))
    textual = normalize_meter(meter_record(geo={"lat": "26.938961", "lng": "75.830956"}))
    partial = normalize_meter(meter_record(geo={"lat": 26.5}))
    invalid = normalize_meter(meter_record(geo={"lat": "north", "lng": "east"}))

    assert numeric is not None and (numeric.latitude, numeric.longitude) == (26.5, 75.5)
    assert textual is not None
    assert textual.latitude == pytest.approx(26.938961)
    assert textual.longitude == pytest.approx(75.830956)
    assert partial is not None and partial.latitude is None and partial.longitude is None
    assert invalid is not None and invalid.latitude is None and invalid.longitude is None


def test_invalid_measurements_stay_null_and_zero_stays_zero():
    """Text, blanks, booleans, and NaN are null. The number 0 is kept."""

    assert parse_number("nope") is None
    assert parse_number("") is None
    assert parse_number(None) is None
    assert parse_number(True) is None
    assert parse_number(float("nan")) is None
    assert parse_number("0") == 0.0
    assert parse_number(0) == 0.0
    assert parse_number(" 226 ") == 226.0


def test_transformer_normalization_keeps_capacity_and_blank_fields():
    """Numeric capacity is kept. An unparseable capacity is null. A missing code drops the row."""

    item = normalize_transformer(transformer_record(capacityKva="100", feederCode=""))
    broken = normalize_transformer(transformer_record(code="DT-009", capacityKva="many"))
    assert item is not None
    assert item.capacity_kva == 100.0
    assert item.feeder_code == ""
    assert broken is not None
    assert broken.capacity_kva is None
    assert normalize_transformer({"name": "missing code"}) is None
