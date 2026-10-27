"""Optional live check. Not part of pytest.

Prints counts and statuses only. It does not print credentials, cookies,
signing secrets, or signatures. Needs network access and a filled-in .env.
A reviewer without the portal account can ignore this script.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.errors import PortalError
from app.portal_client import PortalClient
from app.services.meter_service import MeterService
from app.services.transformer_service import TransformerService
from app.cache import TtlCache


def main() -> int:
    """Log in and print counts only. Exit 2 when credentials are missing, 1 on a portal error."""

    settings = get_settings()
    if not settings.portal_email.strip() or not settings.portal_password.get_secret_value():
        print("live_check: skipped, portal credentials are not configured")
        return 2

    client = PortalClient(settings)
    meters = MeterService(client, TtlCache(settings.cache_ttl_seconds))
    transformers = TransformerService(client, TtlCache(settings.cache_ttl_seconds))
    try:
        page = meters.list_meters(None, 1, 1)
        transformer_page = transformers.list_transformers(1, 1)
        print(f"login: ok")
        print(f"meters: {page.pagination.total}")
        print(f"export_pages: {client.export_pages_fetched}")
        print(f"transformers: {transformer_page.pagination.total}")
        print(f"transformer_pages: {client.transformer_pages_fetched}")
        if not page.data:
            print("sample_meter: none")
            return 0
        sample = page.data[0]
        print(f"sample_meter: {sample.meter_id}")
        print(f"sample_has_coordinates: {sample.latitude is not None and sample.longitude is not None}")
        location = meters.get_location(sample.meter_id)
        print(f"location_source: {location.source}")
        history = meters.get_consumption(sample.meter_id, None, None)
        print(f"consumption_readings: {len(history.readings)}")
        print(f"consumption_rejected: {len(history.rejected)}")
        if history.readings:
            print(f"consumption_first: {history.readings[0].recorded_at}")
            print(f"consumption_last: {history.readings[-1].recorded_at}")
            increasing = history.readings[-1].kwh is not None and history.readings[0].kwh is not None
            if increasing:
                print(f"kwh_non_decreasing: {history.readings[-1].kwh >= history.readings[0].kwh}")
        return 0
    except PortalError as exc:
        print(f"live_check: failed error_type={type(exc).__name__}")
        print("live_check: the client raised a typed portal error. No credentials were printed.")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
