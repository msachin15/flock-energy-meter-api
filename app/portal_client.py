"""Authenticated read-only client for the Urja Meter Ops portal.

The session cookie is stored by requests. It is never copied from a browser
profile and never written to logs. Only the bulk export is signed.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests

from app.config import Settings
from app.constants import MAX_UPSTREAM_PAGES, SESSION_COOKIE_NAME
from app.errors import (
    AuthenticationError,
    PortalConnectionError,
    PortalDataError,
    PortalTimeoutError,
    PortalUpstreamError,
)
from app.normalize import extract_export_records, export_total
from app.signing import build_signature

logger = logging.getLogger("flock_energy.portal")


class PortalClient:
    def __init__(self, settings: Settings, session: Any | None = None) -> None:
        """One session for the process. An injected session is how tests avoid the network."""

        self.settings = settings
        self.base_url = settings.portal_base_url
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "flock-energy-api/1.0")
        self.session.headers.setdefault("Accept", "application/json")
        self._authenticated = False
        self._signing_secret: str | None = None
        self._lock = threading.RLock()
        self.export_pages_fetched = 0
        self.transformer_pages_fetched = 0

    def close(self) -> None:
        """Close the underlying session on shutdown."""

        closer = getattr(self.session, "close", None)
        if closer is not None:
            closer()

    def login(self) -> None:
        """Form login, then a meter-search check. HTTP 200 by itself is not success."""

        email = self.settings.portal_email.strip()
        password = self.settings.portal_password.get_secret_value()
        if not email or not password:
            raise AuthenticationError("Portal credentials are not configured")

        body = urlencode((("email", email), ("password", password)))
        # A POST without Origin was rejected with 403. The same form with Origin
        # and Referer set to this portal returned 200 and the session cookie.
        response = self._raw_request(
            "POST",
            f"{self.base_url}/login",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/login",
                "X-Sveltekit-Action": "true",
            },
            data=body,
        )
        if not _login_accepted(response) or not self._has_session_cookie():
            self._invalidate_auth()
            if not _login_accepted(response):
                logger.error("Portal login failed status=%s", response.status_code)
                raise AuthenticationError("Portal login failed")
            logger.error("Portal login did not set a session cookie status=%s", response.status_code)
            raise AuthenticationError("Portal login did not return a session cookie")

        try:
            self._validate_session()
        except AuthenticationError:
            self._invalidate_auth()
            raise
        self._authenticated = True
        logger.info("Portal login succeeded and the meter search check passed")

    def fetch_meter_export(self) -> list[Any]:
        """Signed export. Page 1 held every live record; later pages exist for a short page.

        A bare JSON array has no total, so it is treated as the whole extract.
        An envelope stops once len(data) reaches total. The 100-page cap is a
        loop guard, not an assumption that the portal has that many pages.
        """

        collected: list[Any] = []
        reported_total: int | None = None
        pages = 0
        for page in range(1, MAX_UPSTREAM_PAGES + 1):
            records, page_total = self._fetch_export_page(page)
            pages = page
            if reported_total is None:
                reported_total = page_total
            collected.extend(records)
            if reported_total is None or len(collected) >= reported_total:
                break
            if not records:
                raise PortalDataError("Meter export ended before the reported total was reached.")
        else:
            raise PortalDataError("Meter export exceeded the page safety limit.")
        if reported_total is not None and len(collected) < reported_total:
            raise PortalDataError("Meter export was incomplete.")
        self.export_pages_fetched = pages
        logger.info("Meter export loaded records=%s pages=%s", len(collected), pages)
        return collected

    def fetch_geo(self, meter_id: str) -> dict[str, Any]:
        """GET /portal/meters/{id}/geo. Coordinates in this payload are strings."""

        path = f"/portal/meters/{quote(meter_id, safe='')}/geo"
        payload = self._get_json(path)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PortalDataError("Geography response did not include a data object.")
        return data

    def fetch_energy(self, meter_id: str) -> list[Any]:
        """GET /portal/meters/{id}/energy. Readings are not cached."""

        path = f"/portal/meters/{quote(meter_id, safe='')}/energy"
        payload = self._get_json(path)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise PortalDataError("Energy response did not include a data array.")
        return data

    def fetch_transformers(self) -> list[Any]:
        """Walk /portal/dts until the reported total is in hand. Page count is not fixed."""

        collected: list[Any] = []
        reported_total: int | None = None
        pages = 0
        for page in range(1, MAX_UPSTREAM_PAGES + 1):
            payload = self._get_json("/portal/dts", (("page", str(page)),))
            pages = page
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise PortalDataError("Transformer response did not include a data array.")
            total = payload.get("total")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise PortalDataError("Transformer response did not include a total.")
            if reported_total is None:
                reported_total = total
            batch = payload["data"]
            if not batch and len(collected) < reported_total:
                raise PortalDataError("Transformer listing ended before the reported total was reached.")
            collected.extend(batch)
            if len(collected) >= reported_total:
                break
        else:
            raise PortalDataError("Transformer listing exceeded the page safety limit.")
        self.transformer_pages_fetched = pages
        logger.info("Transformer listing loaded records=%s pages=%s", len(collected), pages)
        return collected

    def _fetch_export_page(self, page: int) -> tuple[list[Any], int | None]:
        """Sign one export page. The signed query string is the query on the URL."""

        path = "/portal/export"
        query_items = (("page", str(page)),)
        url, query = self._build_url(path, query_items)

        def headers() -> dict[str, str]:
            """Build X-Timestamp and X-Signature for this page. Called again after a re-login."""

            # `query` is the same string appended to `url`. Rebuilt after a
            # re-login so a fresh secret is not paired with the old signature.
            timestamp = _unix_timestamp()
            signature = build_signature(self._secret(), "GET", path, query, timestamp)
            return {
                "Accept": "application/json",
                "X-Timestamp": timestamp,
                "X-Signature": signature,
            }

        response = self._request("GET", url, header_factory=headers)
        payload = self._read_json(response, path)
        return extract_export_records(payload), export_total(payload)

    def _secret(self) -> str:
        """Signing secret from GET /portal/keys. Kept in memory. Never logged."""

        with self._lock:
            if self._signing_secret:
                return self._signing_secret
        payload = self._get_json("/portal/keys")
        data = payload.get("data") if isinstance(payload, dict) else None
        secret = data.get("signingSecret") if isinstance(data, dict) else None
        if not isinstance(secret, str) or not secret:
            raise PortalDataError("Portal signing secret was missing.")
        with self._lock:
            self._signing_secret = secret
        return secret

    def _get_json(self, path: str, query_items: tuple[tuple[str, str], ...] = ()) -> Any:
        """Authenticated GET that must come back as JSON. This path is not signed."""

        url, _query = self._build_url(path, query_items)
        response = self._request("GET", url, headers={"Accept": "application/json"})
        return self._read_json(response, path)

    def _validate_session(self) -> None:
        """Reject a login that did not actually open a meter session.

        Uses the raw request, not `_request`, so a failed check cannot recurse into login.
        """

        url, _query = self._build_url("/portal/meters/search", (("q", ""), ("page", "1")))
        response = self._raw_request("GET", url, headers={"Accept": "application/json"})
        if _looks_logged_out(response):
            logger.error("Portal session check was rejected status=%s", response.status_code)
            raise AuthenticationError("Portal session check was rejected")
        if response.status_code != 200:
            raise PortalUpstreamError(response.status_code, "/portal/meters/search")
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            logger.error(
                "Portal session check returned status=%s content_type=%s",
                response.status_code,
                content_type.split(";")[0],
            )
            raise AuthenticationError("Portal session check did not return meter JSON")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthenticationError("Portal session check returned invalid JSON") from exc
        if not _is_meter_search_payload(payload):
            raise AuthenticationError("Portal session check returned an unexpected meter payload")

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        header_factory: Any | None = None,
        data: str | None = None,
        allow_reauth: bool = True,
    ) -> Any:
        """Log in if needed, send the call, and retry once if the session was rejected."""

        self._ensure_authenticated()
        # header_factory is called again after one re-login. There is no second retry.
        outgoing = header_factory() if header_factory else headers
        response = self._raw_request(method, url, headers=outgoing, data=data)
        if allow_reauth and _looks_logged_out(response):
            logger.info("Portal rejected the session path=%s; logging in once more", urlparse(url).path)
            self._invalidate_auth()
            self.login()
            outgoing = header_factory() if header_factory else headers
            response = self._raw_request(method, url, headers=outgoing, data=data)
            if _looks_logged_out(response):
                raise AuthenticationError("Portal rejected the session after a fresh login")
        return response

    def _ensure_authenticated(self) -> None:
        """Run login the first time, and again after the session is cleared."""

        if not self._authenticated:
            self.login()

    def _raw_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: str | None = None,
    ) -> Any:
        """Send one HTTP call. Redirects are not followed, and the cookie jar is updated here."""

        timeout = (self.settings.portal_timeout_seconds, self.settings.portal_timeout_seconds)
        try:
            # requests.Session is not thread-safe. The lock covers the send and the cookie copy.
            # allow_redirects is off so a bounce to /login stays visible.
            with self._lock:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    timeout=timeout,
                    allow_redirects=False,
                )
                self.session.cookies.update(response.cookies)
                return response
        except requests.Timeout as exc:
            logger.error("Portal timeout method=%s path=%s", method, urlparse(url).path)
            raise PortalTimeoutError("Portal request timed out") from exc
        except requests.RequestException as exc:
            logger.error("Portal connection failure method=%s path=%s", method, urlparse(url).path)
            raise PortalConnectionError("Portal request failed") from exc

    def _read_json(self, response: Any, path: str) -> Any:
        """Require HTTP 200 and a JSON body. Anything else becomes a typed portal error."""

        if response.status_code != 200:
            logger.error("Portal HTTP error status=%s path=%s", response.status_code, path)
            raise PortalUpstreamError(response.status_code, path)
        content_type = response.headers.get("Content-Type", "")
        if content_type and "json" not in content_type.lower() and "text/plain" not in content_type.lower():
            raise PortalDataError(f"Portal response from {path} was not JSON.")
        try:
            return response.json()
        except ValueError as exc:
            raise PortalDataError(f"Portal response from {path} was not valid JSON.") from exc

    def _has_session_cookie(self) -> bool:
        """True when the better-auth session cookie is on the session."""

        with self._lock:
            return bool(self.session.cookies.get(SESSION_COOKIE_NAME))

    def _invalidate_auth(self) -> None:
        """Drop the login flag, the signing secret, and every cookie."""

        with self._lock:
            self._authenticated = False
            self._signing_secret = None
            self.session.cookies.clear()

    def _build_url(self, path: str, query_items: tuple[tuple[str, str], ...] = ()) -> tuple[str, str]:
        """Return the full URL and the raw query string. Signing must use that same query string."""

        query = urlencode(query_items)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        return url, query


def _unix_timestamp() -> str:
    """Unix time in seconds, as a string, which is what the signature message uses."""

    import time

    return str(int(time.time()))


def _login_accepted(response: Any) -> bool:
    """True for the JSON redirect to a non-login page, or a real 303 to that page."""

    if response.status_code not in (200, 303):
        return False
    content_type = response.headers.get("Content-Type", "")
    if response.status_code == 303 and "json" not in content_type.lower():
        location = response.headers.get("Location", "")
        return bool(location) and not _targets_login(location)
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or body.get("type") != "redirect":
        return False
    location = body.get("location")
    return isinstance(location, str) and bool(location) and not _targets_login(location)


def _looks_logged_out(response: Any) -> bool:
    """True when a call that should have been authenticated was sent back to login.

    A 403 on the login POST itself is handled in `login`, before this check.
    That case was a missing Origin/Referer, not an expired session.
    """

    if response.status_code in (401, 403):
        return True
    location = response.headers.get("Location", "")
    if response.status_code in (301, 302, 303, 307, 308) and _targets_login(location):
        return True
    content_type = response.headers.get("Content-Type", "")
    if response.status_code == 200 and "html" in content_type.lower():
        return True
    if "json" not in content_type.lower():
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or body.get("type") != "redirect":
        return False
    target = body.get("location")
    return isinstance(target, str) and _targets_login(target)


def _targets_login(location: str) -> bool:
    """True when the location path is /login, whether it is relative or absolute."""

    parsed = urlparse(location)
    path = parsed.path if parsed.scheme or location.startswith("/") else location
    normalized = "/" + path.strip("/")
    return normalized == "/login"


def _is_meter_search_payload(payload: Any) -> bool:
    """True when search JSON has data, a non-negative integer total, and page."""

    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    total = payload.get("total")
    if not isinstance(data, list):
        return False
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return False
    if "page" not in payload:
        return False
    if not data:
        return True
    first = data[0]
    meter_id = first.get("meterId") if isinstance(first, dict) else None
    return isinstance(meter_id, str) and bool(meter_id.strip())
