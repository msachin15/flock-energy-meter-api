"""Portal HTTP behaviour with a fake session. No network.

Covers the login form, the session cookie on the next call, a failed login,
one re-login after HTTP 401, export signatures, both export shapes,
transformer paging from `total`, and timeout / bad JSON / HTTP 500.
"""

import hashlib
import hmac
import logging
from urllib.parse import parse_qs

import pytest
import requests

from app.constants import SESSION_COOKIE_NAME
from app.errors import (
    AuthenticationError,
    PortalConnectionError,
    PortalDataError,
    PortalTimeoutError,
    PortalUpstreamError,
)
from app.portal_client import PortalClient
from tests.fakes import (
    INVALID_JSON,
    JSON_HEADERS,
    SESSION_VALUE,
    FakeSession,
    login_success,
    search_success,
)


def _client(settings, handler) -> tuple[PortalClient, FakeSession]:
    """Portal client bound to the fake session."""

    session = FakeSession(handler)
    return PortalClient(settings, session=session), session


def _capture_logs():
    """Collect portal log lines so a test can prove a secret was not written."""

    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            """Store one formatted log message."""

            records.append(record.getMessage())

    logger = logging.getLogger("flock_energy.portal")
    handler = ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return records, logger, handler


def test_login_request_uses_form_fields_header_and_redirect_json(settings):
    """Login is a form POST with the SvelteKit header, Origin, and Referer, then a search check."""

    def handler(call):
        """Login succeeds. The following search check also succeeds."""

        if call["url"].endswith("/login"):
            return login_success()
        return search_success()

    client, session = _client(settings, handler)
    client.login()

    login = session.calls[0]
    body = parse_qs(login["data"])
    assert login["method"] == "POST"
    assert login["url"] == "https://portal.test/login"
    assert login["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert login["headers"]["X-Sveltekit-Action"] == "true"
    assert login["headers"]["Origin"] == "https://portal.test"
    assert login["headers"]["Referer"] == "https://portal.test/login"
    assert login["allow_redirects"] is False
    assert login["timeout"] == (5, 5)
    assert body["email"] == ["user@example.com"]
    assert body["password"] == ["synthetic-password"]
    assert client._authenticated is True
    assert session.calls[1]["url"] == "https://portal.test/portal/meters/search?q=&page=1"


def test_session_cookie_is_stored_and_sent_on_the_next_request(settings):
    """The cookie from login is on the session and is sent with the search check."""

    client, session = _client(settings, lambda _call: login_success() if _call["url"].endswith("/login") else search_success())
    client.login()

    assert session.cookies.get(SESSION_COOKIE_NAME) == SESSION_VALUE
    assert SESSION_VALUE in session.calls[1]["cookie"]
    assert session.calls[0]["cookie"] == ""


def test_login_failure_does_not_validate_a_session(settings):
    """A failure JSON body stops login. The search route is not called."""

    def handler(_call):
        """Portal form failure: HTTP 200 with type failure and no cookie."""

        return {"status": 200, "json": {"type": "failure", "status": 400}, "headers": JSON_HEADERS}

    client, session = _client(settings, handler)
    with pytest.raises(AuthenticationError, match="Portal login failed"):
        client.login()
    assert client._authenticated is False
    assert [call["method"] for call in session.calls] == ["POST"]


def test_login_without_the_session_cookie_fails(settings):
    """Redirect JSON without the session cookie is not a successful login."""

    def handler(_call):
        """Redirect body with no Set-Cookie."""

        return {
            "status": 200,
            "json": {"type": "redirect", "status": 303, "location": "/meters"},
            "headers": JSON_HEADERS,
        }

    client, _session = _client(settings, handler)
    with pytest.raises(AuthenticationError, match="session cookie"):
        client.login()
    assert client._authenticated is False


def test_missing_credentials_do_not_make_a_request():
    """Empty email and password fail before any HTTP call."""

    from app.config import Settings

    empty = Settings(
        portal_base_url="https://portal.test",
        portal_email="",
        portal_password="",
        portal_timeout_seconds=5,
        cache_ttl_seconds=300,
        _env_file=None,
    )
    client, session = _client(empty, lambda _call: login_success())
    with pytest.raises(AuthenticationError, match="not configured"):
        client.login()
    assert session.calls == []


def test_expired_session_reauthenticates_once_and_resigns_the_export(settings):
    """One 401 causes one new login and a new signature. Secrets stay out of the logs."""

    state = {"exports": 0}
    records, logger, handler = _capture_logs()

    def route(call):
        """First signed export returns 401. The retry returns the meter array."""

        if call["url"].endswith("/login"):
            return login_success()
        if call["url"].endswith("/portal/meters/search?q=&page=1"):
            assert SESSION_VALUE in call["cookie"]
            return search_success()
        if call["url"].endswith("/portal/keys"):
            assert "X-Signature" not in call["headers"]
            assert SESSION_VALUE in call["cookie"]
            return {"status": 200, "json": {"data": {"signingSecret": "synthetic-secret"}}, "headers": JSON_HEADERS}
        if call["url"].startswith("https://portal.test/portal/export?"):
            state["exports"] += 1
            query = call["url"].split("?", 1)[1]
            timestamp = call["headers"]["X-Timestamp"]
            message = f"GET\n/portal/export\n{query}\n{timestamp}"
            expected = hmac.new(b"synthetic-secret", message.encode("utf-8"), hashlib.sha256).hexdigest()
            assert call["headers"]["X-Signature"] == expected
            assert SESSION_VALUE in call["cookie"]
            if state["exports"] == 1:
                return {"status": 401, "json": {"error": "expired"}, "headers": JSON_HEADERS}
            return {"status": 200, "json": {"data": [{"meterId": "J100000"}], "total": 1}, "headers": JSON_HEADERS}
        raise AssertionError(call["url"])

    try:
        client, session = _client(settings, route)
        records_out = client.fetch_meter_export()
    finally:
        logger.removeHandler(handler)

    assert records_out == [{"meterId": "J100000"}]
    assert state["exports"] == 2
    assert sum(1 for call in session.calls if call["url"].endswith("/login")) == 2
    assert client.export_pages_fetched == 1
    rendered = "\n".join(records)
    assert "synthetic-password" not in rendered
    assert "synthetic-secret" not in rendered
    assert "synthetic-session" not in rendered


def test_export_pages_are_signed_with_the_raw_query_until_total_is_reached(settings):
    """page=1 and page=2 are signed separately until total is reached."""

    def route(call):
        """Page 1 is short of total. Page 2 finishes the extract."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        if call["url"].endswith("/portal/keys"):
            return {"status": 200, "json": {"data": {"signingSecret": "synthetic-secret"}}, "headers": JSON_HEADERS}
        if "/portal/export?" in call["url"]:
            query = call["url"].split("?", 1)[1]
            timestamp = call["headers"]["X-Timestamp"]
            message = f"GET\n/portal/export\n{query}\n{timestamp}".encode("utf-8")
            expected = hmac.new(b"synthetic-secret", message, hashlib.sha256).hexdigest()
            assert call["headers"]["X-Signature"] == expected
            if query == "page=1":
                return {
                    "status": 200,
                    "json": {"data": [{"meterId": "J1"}, {"meterId": "J2"}], "total": 3},
                    "headers": JSON_HEADERS,
                }
            if query == "page=2":
                return {
                    "status": 200,
                    "json": {"data": [{"meterId": "J3"}], "total": 3},
                    "headers": JSON_HEADERS,
                }
            raise AssertionError(query)
        raise AssertionError(call["url"])

    client, session = _client(settings, route)
    assert [row["meterId"] for row in client.fetch_meter_export()] == ["J1", "J2", "J3"]
    export_urls = [call["url"] for call in session.calls if "/portal/export?" in call["url"]]
    assert export_urls == [
        "https://portal.test/portal/export?page=1",
        "https://portal.test/portal/export?page=2",
    ]
    assert sum(1 for call in session.calls if call["url"].endswith("/portal/keys")) == 1


@pytest.mark.parametrize(
    "payload",
    [
        [{"meterId": "J9"}],
        {"data": [{"meterId": "J9"}], "total": 1},
    ],
)
def test_export_accepts_array_and_envelope(settings, payload):
    """A complete array or a complete envelope is one request."""

    def route(call):
        """Return whichever export shape the test parameterized."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        if call["url"].endswith("/portal/keys"):
            return {"status": 200, "json": {"data": {"signingSecret": "synthetic-secret"}}, "headers": JSON_HEADERS}
        if "/portal/export?" in call["url"]:
            return {"status": 200, "json": payload, "headers": JSON_HEADERS}
        raise AssertionError(call["url"])

    client, session = _client(settings, route)
    assert client.fetch_meter_export() == [{"meterId": "J9"}]
    assert sum(1 for call in session.calls if "/portal/export?" in call["url"]) == 1


def test_transformer_pages_follow_reported_total(settings):
    """Two upstream pages are fetched because total is 3, not because two pages were assumed."""

    def route(call):
        """Page 1 has two rows. Page 2 has the last row. Page 3 must not be called."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        if call["url"].endswith("/portal/dts?page=1"):
            return {
                "status": 200,
                "json": {"data": [{"code": "DT-001"}, {"code": "DT-002"}], "total": 3, "page": 1, "pageSize": 2},
                "headers": JSON_HEADERS,
            }
        if call["url"].endswith("/portal/dts?page=2"):
            return {
                "status": 200,
                "json": {"data": [{"code": "DT-003"}], "total": 3, "page": 2, "pageSize": 2},
                "headers": JSON_HEADERS,
            }
        raise AssertionError(call["url"])

    client, session = _client(settings, route)
    assert [row["code"] for row in client.fetch_transformers()] == ["DT-001", "DT-002", "DT-003"]
    assert client.transformer_pages_fetched == 2
    assert not any(call["url"].endswith("/portal/dts?page=3") for call in session.calls)


def test_upstream_http_error_bad_json_and_timeout(settings):
    """Timeout, invalid JSON, HTTP 500, and a connection error become typed failures."""

    def timeout_route(call):
        """The export call times out once and is not retried."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        if call["url"].endswith("/portal/keys"):
            return {"status": 200, "json": {"data": {"signingSecret": "synthetic-secret"}}, "headers": JSON_HEADERS}
        raise requests.Timeout("timed out")

    client, session = _client(settings, timeout_route)
    with pytest.raises(PortalTimeoutError):
        client.fetch_meter_export()
    assert sum(1 for call in session.calls if "/portal/export?" in call["url"]) == 1

    def bad_json(call):
        """HTTP 200 with a body that is not JSON."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        if call["url"].endswith("/portal/keys"):
            return {"status": 200, "json": {"data": {"signingSecret": "synthetic-secret"}}, "headers": JSON_HEADERS}
        return {"status": 200, "json": INVALID_JSON, "headers": JSON_HEADERS}

    client, _session = _client(settings, bad_json)
    with pytest.raises(PortalDataError):
        client.fetch_meter_export()

    def server_error(call):
        """The transformer route returns HTTP 500."""

        if call["url"].endswith("/login"):
            return login_success()
        if "/portal/meters/search" in call["url"]:
            return search_success()
        return {"status": 500, "json": {"error": "down"}, "headers": JSON_HEADERS}

    client, _session = _client(settings, server_error)
    with pytest.raises(PortalUpstreamError) as caught:
        client.fetch_transformers()
    assert caught.value.status_code == 500

    def offline(call):
        """The login connection fails before a response exists."""

        if call["url"].endswith("/login"):
            raise requests.ConnectionError("no route")
        raise AssertionError(call["url"])

    client, _session = _client(settings, offline)
    with pytest.raises(PortalConnectionError):
        client.login()
