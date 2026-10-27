"""HMAC vector. The expected digest is computed here, not by calling the same helper twice."""

import hashlib
import hmac

from app.signing import build_signature, build_signing_message


def test_signature_matches_hmac_sha256_of_the_newline_message():
    """The digest is HMAC-SHA256 of the four-line message, lowercase hex."""

    message = "GET\n/portal/export\npage=1\n1700000000"
    expected = hmac.new(b"test-secret", message.encode("utf-8"), hashlib.sha256).hexdigest()

    assert build_signing_message("GET", "/portal/export", "page=1", "1700000000") == message
    signature = build_signature("test-secret", "GET", "/portal/export", "page=1", "1700000000")

    assert signature == expected
    assert signature == signature.lower()
    assert len(signature) == 64


def test_message_uses_newlines_and_keeps_an_empty_query():
    """Method, path, query, and timestamp are separated by newlines. An empty query stays a blank line."""

    message = build_signing_message("get", "/portal/keys", "", "1700000000")

    assert message == "GET\n/portal/keys\n\n1700000000"
    assert message.count("\n") == 3
    assert " " not in message.split("\n")[0]


def test_signature_changes_when_the_query_string_changes():
    """page=1 and page=2 must not share a signature."""

    first = build_signature("test-secret", "GET", "/portal/export", "page=1", "1700000000")
    second = build_signature("test-secret", "GET", "/portal/export", "page=2", "1700000000")

    assert first != second
