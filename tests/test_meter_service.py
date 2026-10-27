"""Catalog behaviour: filter then page, 404, export coordinates vs the geo fallback."""

import pytest

from app.cache import TtlCache
from app.errors import LocationUnavailable, NotFoundError, PortalTimeoutError
from app.services.meter_service import MeterService
from tests.fakes import RecordingPortal
from tests.samples import meter_record


def service_for(records, **portal_kwargs) -> tuple[MeterService, RecordingPortal]:
    """Build a meter service over a fake export."""

    portal = RecordingPortal(export=records, **portal_kwargs)
    return MeterService(portal, TtlCache(300)), portal


def test_search_filters_before_pagination_and_ignores_other_fields():
    """query=j100 matches two meters. Page size 1 still reports total 2. Make is not searched."""

    records = [
        meter_record(meterId="J100000", serialNo="SE33962", make="HPL"),
        meter_record(meterId="J100001", serialNo="GE84132", make="L&T"),
        meter_record(meterId="J200000", serialNo="AB00001", make="HPL"),
    ]
    service, portal = service_for(records)

    page = service.list_meters("j100", page=1, page_size=1)
    assert [item.meter_id for item in page.data] == ["J100000"]
    assert page.pagination.total == 2
    assert page.pagination.total_pages == 2
    assert page.pagination.page == 1

    second = service.list_meters("j100", page=2, page_size=1)
    assert [item.meter_id for item in second.data] == ["J100001"]
    assert second.pagination.total == 2
    assert service.list_meters("ge84132", page=1, page_size=20).pagination.total == 1
    assert service.list_meters("hpl", page=1, page_size=20).pagination.total == 0
    assert portal.export_calls == 1


def test_unknown_meter_is_not_found_and_lookup_is_case_insensitive():
    """j100000 finds J100000. An unknown id is 404 and does not call the geo route."""

    service, portal = service_for([meter_record()])
    assert service.get_meter("j100000").serial_no == "SE33962"
    with pytest.raises(NotFoundError) as caught:
        service.get_meter("missing")
    assert caught.value.error == "not_found"
    assert portal.geo_calls == []


def test_location_uses_export_coordinates_and_falls_back_only_when_needed():
    """Good export geo skips the geo route. Missing geo uses it. Unparseable geo is location_unavailable."""

    export = [
        meter_record(),
        meter_record(meterId="J100010", serialNo="NOGEO", geo={"lat": "north", "lng": "east"}),
        meter_record(meterId="J100011", serialNo="STRINGS", geo=None),
    ]
    service, portal = service_for(
        export,
        geo={"J100011": {"latitude": "26.938961", "longitude": "75.830956"}},
    )

    exported = service.get_location("J100000")
    assert exported.source == "export"
    assert exported.latitude == 26.9
    assert portal.geo_calls == []

    fallback = service.get_location("J100011")
    assert fallback.source == "geo_endpoint"
    assert fallback.latitude == pytest.approx(26.938961)
    assert fallback.longitude == pytest.approx(75.830956)

    with pytest.raises(LocationUnavailable):
        service.get_location("J100010")


def test_failed_export_is_not_cached():
    """A timeout is raised and the next call loads again."""

    portal = RecordingPortal(export=[meter_record()], error=PortalTimeoutError("timed out"))
    service = MeterService(portal, TtlCache(300))
    with pytest.raises(PortalTimeoutError):
        service.list_meters(None, 1, 20)
    portal.error = None
    page = service.list_meters(None, 1, 20)
    assert page.pagination.total == 1
    assert portal.export_calls == 2
