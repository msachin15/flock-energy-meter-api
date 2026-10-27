"""Shared names and limits.

MAX_UPSTREAM_PAGES is a safety stop so a broken total cannot loop forever.
It is not an assumption about how many pages the portal currently has.
"""

API_TITLE = "Flock Energy Meter API"
API_VERSION = "1.0.0"

SESSION_COOKIE_NAME = "__Secure-better-auth.session_token"

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_UPSTREAM_PAGES = 100

HIERARCHY_LEVELS = (
    "zone",
    "circle",
    "division",
    "subdivision",
    "substation",
    "feeder",
    "dt",
)

RECORDED_AT_CONVENTION = (
    "recorded_at is a naive datetime in YYYY-MM-DDTHH:mm:ss, converted from the "
    "portal format DD/MM/YYYY HH:mm. No timezone, offset, or UTC marker is added "
    "because the portal does not provide one. source_timestamp is the original value."
)

CONSUMPTION_INTERPRETATION = (
    "In the supplied sample, kWh and kVAh increase over time. That pattern is "
    "consistent with cumulative register readings, but it has not been confirmed "
    "as the portal's definition. Values are returned as received, not as interval consumption."
)
