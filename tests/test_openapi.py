"""The committed openapi.json must match the app. Edit routes, then regenerate the file."""

import json
from pathlib import Path

from app.constants import API_TITLE, API_VERSION
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = {
    "/health",
    "/api/v1/meters",
    "/api/v1/meters/{meter_id}",
    "/api/v1/meters/{meter_id}/location",
    "/api/v1/meters/{meter_id}/consumption",
    "/api/v1/transformers",
    "/api/v1/transformers/{code}",
}


def test_openapi_describes_the_running_application():
    """The live spec is OpenAPI 3.x and lists every route."""

    spec = app.openapi()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == API_TITLE
    assert spec["info"]["version"] == API_VERSION
    assert REQUIRED_PATHS <= set(spec["paths"])
    consumption = spec["paths"]["/api/v1/meters/{meter_id}/consumption"]["get"]
    parameter_names = {item["name"] for item in consumption["parameters"]}
    assert {"start_date", "end_date"} <= parameter_names


def test_committed_openapi_matches_the_application():
    """openapi.json matches the app. Regenerate it after a route or schema change."""

    document = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert document == app.openapi()
