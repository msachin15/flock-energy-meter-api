"""HTTP stand-ins. Nothing in this module contacts a network."""

import json
from typing import Any

import requests

from app.constants import SESSION_COOKIE_NAME
from app.errors import PortalUpstreamError

INVALID_JSON = object()
JSON_HEADERS = {"Content-Type": "application/json"}
SESSION_VALUE = "synthetic-session"


class FakeResponse:
    def __init__(self, spec: dict[str, Any]) -> None:
        """A response the portal client can read. set_cookie lands on response.cookies."""

        self.status_code = spec.get("status", 200)
        self.headers = {str(key): str(value) for key, value in spec.get("headers", JSON_HEADERS).items()}
        self._body = spec.get("json", None)
        self.text = spec.get("text", "")
        self.cookies = requests.cookies.RequestsCookieJar()
        cookie = spec.get("set_cookie")
        if cookie is not None:
            name, value = cookie
            self.cookies.set(name, value)

    def json(self) -> Any:
        """Return the canned body, or raise if the test asked for invalid JSON."""

        if self._body is INVALID_JSON:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return self._body


class FakeSession:
    """Records calls and lets the portal client copy response cookies onto the jar."""

    def __init__(self, handler) -> None:
        """Record calls. This session does not store cookies by itself."""

        self.handler = handler
        self.cookies = requests.cookies.RequestsCookieJar()
        self.calls: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def request(self, method, url, headers=None, data=None, timeout=None, allow_redirects=None, **_kwargs):
        """Record the call, including cookies already on the jar, then return the handler's response."""

        call = {
            "method": method,
            "url": url,
            "headers": dict(headers or {}),
            "data": data,
            "timeout": timeout,
            "allow_redirects": allow_redirects,
            "cookie": "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookies),
        }
        self.calls.append(call)
        spec = self.handler(call)
        return FakeResponse(spec)

    def close(self) -> None:
        """No-op so the app lifespan can shut the test double down."""

        return None


def login_success() -> dict[str, Any]:
    """The live login shape: HTTP 200, a redirect JSON body, and the session cookie."""

    return {
        "status": 200,
        "json": {"type": "redirect", "status": 303, "location": "/meters"},
        "headers": JSON_HEADERS,
        "set_cookie": (SESSION_COOKIE_NAME, SESSION_VALUE),
    }


def search_success() -> dict[str, Any]:
    """A minimal meter-search payload that passes the post-login check."""

    return {
        "status": 200,
        "json": {
            "data": [{"meterId": "J100000", "serialNo": "SE33962"}],
            "total": 1,
            "page": 1,
            "pageSize": 20,
        },
        "headers": JSON_HEADERS,
    }


class RecordingPortal:
    def __init__(
        self,
        export: list | None = None,
        energy: dict | None = None,
        geo: dict | None = None,
        transformers: list | None = None,
        error: Exception | None = None,
    ) -> None:
        """In-memory portal used by service and API tests."""

        self.export = [] if export is None else export
        self.energy = {} if energy is None else energy
        self.geo = {} if geo is None else geo
        self.transformers = [] if transformers is None else transformers
        self.error = error
        self.geo_calls: list[str] = []
        self.energy_calls: list[str] = []
        self.export_calls = 0
        self.transformer_calls = 0

    def fetch_meter_export(self) -> list:
        """Return the canned export, or raise the configured error."""

        self.export_calls += 1
        if self.error is not None:
            raise self.error
        return self.export

    def fetch_geo(self, meter_id: str) -> dict:
        """Return canned geography, or 404 when this meter has none."""

        self.geo_calls.append(meter_id)
        if meter_id not in self.geo:
            raise PortalUpstreamError(404, f"/portal/meters/{meter_id}/geo")
        return self.geo[meter_id]

    def fetch_energy(self, meter_id: str) -> list:
        """Return canned history, or 404 when this meter has none."""

        self.energy_calls.append(meter_id)
        if meter_id not in self.energy:
            raise PortalUpstreamError(404, f"/portal/meters/{meter_id}/energy")
        return self.energy[meter_id]

    def fetch_transformers(self) -> list:
        """Return the canned transformer rows, or raise the configured error."""

        self.transformer_calls += 1
        if self.error is not None:
            raise self.error
        return self.transformers

    def close(self) -> None:
        """No-op so the app lifespan can shut the test double down."""

        return None
