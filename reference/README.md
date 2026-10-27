# Reference evidence

The raw portal extracts used while building this service are local investigation
files. They are not part of the repository.

Kept out of git on purpose:

- The assignment brief, because it contains the portal password.
- `meter-export.json`, the downloaded meter array (403 records in the copy that was inspected).
- The energy-history sample.
- Login-page HTML beyond the field names recorded in `PROTOCOL.md`.

Tests use small synthetic records under `tests/`. The running service reads the
live portal, not these files.
