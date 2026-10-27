"""HMAC-SHA256 request signing used by the portal bulk export.

The message is the HTTP method, path, raw query string, and timestamp,
joined with newline characters. The caller must pass the same query string
that is sent on the wire.
"""

import hashlib
import hmac


def build_signing_message(method: str, path: str, query_string: str, timestamp: str) -> str:
    """Four lines. An empty query is still a blank line, so the timestamp stays last."""

    return "\n".join((method.upper(), path, query_string, timestamp))


def build_signature(
    secret: str,
    method: str,
    path: str,
    query_string: str,
    timestamp: str,
) -> str:
    """Lowercase hex HMAC-SHA256 of the newline message. The secret is the HMAC key."""

    message = build_signing_message(method, path, query_string, timestamp)
    digest = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()
