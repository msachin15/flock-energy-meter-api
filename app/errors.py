"""Typed failures for the portal client and the public API."""


class PortalError(Exception):
    """Base class for failures while talking to the portal."""


class AuthenticationError(PortalError):
    """Login failed, the session cookie was missing, or the session was rejected."""


class PortalTimeoutError(PortalError):
    """The portal did not respond within the configured timeout."""


class PortalConnectionError(PortalError):
    """The portal could not be reached."""


class PortalUpstreamError(PortalError):
    """The portal returned an HTTP error status."""

    def __init__(self, status_code: int, path: str) -> None:
        """Remember the portal status and path for logs. The public API does not echo the path."""

        self.status_code = status_code
        self.path = path
        super().__init__(f"Upstream HTTP {status_code} for {path}")


class PortalDataError(PortalError):
    """The portal response was not usable JSON or did not match the expected shape."""


class NotFoundError(Exception):
    """A meter or transformer does not exist."""

    def __init__(self, error: str, message: str) -> None:
        """Carry the public error code and message used in the 404 body."""

        self.error = error
        self.message = message
        super().__init__(message)


class LocationUnavailable(NotFoundError):
    """The meter exists, but neither source has usable coordinates."""

    def __init__(self, meter_id: str) -> None:
        """404 with error location_unavailable. The meter exists; the point does not."""

        super().__init__(
            "location_unavailable",
            f"Meter '{safe_identifier(meter_id)}' has no valid coordinates.",
        )


class InvalidQuery(Exception):
    """A query parameter failed a rule that FastAPI's parser does not cover."""

    def __init__(self, error: str, message: str) -> None:
        """422 for a rule FastAPI's parser does not cover, such as an inverted date range."""

        self.error = error
        self.message = message
        super().__init__(message)


def safe_identifier(value: str, limit: int = 80) -> str:
    """Collapse whitespace so an identifier can be echoed in an error message."""

    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def error_payload(error: str, message: str, details: list | None = None) -> dict:
    """Stable error body: error, message, and details. Details is null unless validation failed."""

    return {"error": error, "message": message, "details": details}
