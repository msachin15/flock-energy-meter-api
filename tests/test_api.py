"""HTTP status codes through the real FastAPI app and a fake portal.

Health must not touch the portal. Search total is the filtered count.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import PortalTimeoutError, PortalUpstreamError
from app.main import create_app
from tests.fakes import RecordingPortal
from tests.samples import meter_record, transformer_record


def _settings() -> Settings:
    """Settings for the HTTP tests. The fake portal means these credentials are never sent."""

    return Settings(
        portal_base_url="https://portal.test",
        portal_email="user@example.com",
        portal_password="synthetic-password",
        portal_timeout_seconds=5,
        cache_ttl_seconds=300,
        _env_file=None,
    )


def _client(portal: RecordingPortal) -> TestClient:
    """FastAPI test client wired to the fake portal."""

    application = create_app(settings=_settings(), portal=portal)
    return TestClient(application)


def test_health_does_not_claim_the_portal_is_healthy():
    """GET /health stays local and reports portal not_checked."""

    portal = RecordingPortal(error=AssertionError("health must not call the portal"))
    with _client(portal) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "portal": "not_checked"}
    assert portal.export_calls == 0


def test_meter_routes_search_detail_and_missing_meter():
    """Search total is the filtered count. Missing meters are 404. page=0 is 422."""

    portal = RecordingPortal(
        export=[
            meter_record(),
            meter_record(meterId="J100001", serialNo="GE84132"),
            meter_record(meterId="J200000", serialNo="AB00001", make="Secure"),
        ]
    )
    with _client(portal) as client:
        listed = client.get("/api/v1/meters", params={"query": "j100", "page": 1, "page_size": 1})
        detail = client.get("/api/v1/meters/J100000")
        missing = client.get("/api/v1/meters/NOPE")
        invalid = client.get("/api/v1/meters", params={"page": 0})

    assert listed.status_code == 200
    body = listed.json()
    assert [item["meter_id"] for item in body["data"]] == ["J100000"]
    assert body["pagination"]["total"] == 2
    assert body["data"][0]["install_type"] == "Whole Current"
    assert body["data"][0]["build"] == "legacy"
    assert detail.status_code == 200
    assert detail.json()["serial_no"] == "SE33962"
    assert detail.json()["hierarchy"]["dt"]["code"] == "DT-001"
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "validation_error"


def test_location_consumption_and_date_errors():
    """String coordinates, chronological readings, null for a bad kWh, and an inverted date range."""

    portal = RecordingPortal(
        export=[meter_record(), meter_record(meterId="J100011", serialNo="STRINGS", geo=None)],
        geo={"J100011": {"latitude": "26.1", "longitude": "75.2"}},
        energy={
            "J100000": [
                {"timestamp": "24/06/2026 00:30", "kwh": "2", "kvah": "2", "voltR": "230"},
                {"timestamp": "24/06/2026 00:00", "kwh": "nope", "kvah": "1", "voltR": "229"},
            ]
        },
    )
    with _client(portal) as client:
        location = client.get("/api/v1/meters/J100011/location")
        history = client.get("/api/v1/meters/J100000/consumption")
        backwards = client.get(
            "/api/v1/meters/J100000/consumption",
            params={"start_date": "2026-06-25", "end_date": "2026-06-24"},
        )
        filtered = client.get(
            "/api/v1/meters/J100000/consumption",
            params={"start_date": "2026-06-24", "end_date": "2026-06-24"},
        )

    assert location.status_code == 200
    assert location.json()["source"] == "geo_endpoint"
    assert location.json()["latitude"] == 26.1
    assert history.status_code == 200
    payload = history.json()
    assert payload["timezone"] is None
    assert [item["source_timestamp"] for item in payload["readings"]] == [
        "24/06/2026 00:00",
        "24/06/2026 00:30",
    ]
    assert payload["readings"][0]["kwh"] is None
    assert filtered.json()["readings"][1]["kwh"] == 2.0
    assert backwards.status_code == 422
    assert backwards.json()["error"] == "invalid_date_range"


def test_transformer_routes_and_upstream_errors():
    """Transformer paging, 404, 405, a portal timeout as 504, and a portal 500 as 502."""

    portal = RecordingPortal(transformers=[transformer_record(), transformer_record(code="DT-002")])
    with _client(portal) as client:
        listed = client.get("/api/v1/transformers", params={"page": 1, "page_size": 1})
        detail = client.get("/api/v1/transformers/DT-002")
        missing = client.get("/api/v1/transformers/DT-404")
        method = client.post("/api/v1/meters")

    assert listed.status_code == 200
    assert listed.json()["pagination"]["total"] == 2
    assert listed.json()["data"][0]["feeder_code"] == "F-001"
    assert listed.json()["data"][0]["capacity_kva"] == 100.0
    assert detail.status_code == 200
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"
    assert method.status_code == 405

    timeout_portal = RecordingPortal(error=PortalTimeoutError("timed out"))
    with _client(timeout_portal) as client:
        timeout = client.get("/api/v1/meters")
    assert timeout.status_code == 504
    assert timeout.json()["error"] == "upstream_timeout"
    assert "Traceback" not in timeout.text

    upstream_portal = RecordingPortal(error=PortalUpstreamError(500, "/portal/dts"))
    with _client(upstream_portal) as client:
        upstream = client.get("/api/v1/transformers")
    assert upstream.status_code == 502
    assert upstream.json()["error"] == "upstream_error"
    assert "/portal/dts" not in upstream.text
