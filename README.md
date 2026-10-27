# Flock Energy Meter API

Read-only HTTP API in front of the Urja Meter Ops portal (`https://urja-ops.flockenergy.tech`).

The portal is how distribution-utility staff look up smart meters: identity, where the meter sits in the network, coordinates, recent consumption, and the distribution transformer it is attached to. The portal has no public API. This service logs in as an operator, calls the portal's existing JSON routes, and exposes a smaller JSON API that another program can use.

The portal is never written to. There is no endpoint here that creates, updates, or deletes portal data.

Further reading:

- [PROTOCOL.md](PROTOCOL.md) describes how the portal actually behaves.
- [openapi.json](openapi.json) is the OpenAPI 3.1 spec generated from this FastAPI app.
- [REFLECTION.md](REFLECTION.md) answers the assignment reflection questions.
- Interactive docs, when the service is running: `http://127.0.0.1:8000/docs`

## How to review this

Start with this file, then `PROTOCOL.md` for what was seen on the portal, then the code map below. `REFLECTION.md` is the judgment, not the evidence.

Two different kinds of proof are in the repo:

- `pytest` proves the client, parsing, paging, and HTTP errors with fake responses. It does not contact the portal.
- The "Live check" section at the bottom of this file is one real read-only run. It is not part of `pytest`.

| Question | Where to look |
| --- | --- |
| Did login match the portal? | `app/portal_client.py` `login`. A 403 without `Origin` and `Referer` is explained there. |
| Is HTTP 200 alone treated as logged in? | `login` also requires the session cookie and a meter-search JSON check. |
| Is the HMAC message exact? | `app/signing.py`. `tests/test_signing.py` locks the newline layout. `tests/test_portal_client.py` checks the signature against the query string on the URL. |
| Are both export shapes accepted? | `extract_export_records` in `app/normalize.py`. Live calls use the envelope. The downloaded file is the bare array. |
| Why is search local? | The paged search route omits install type, build, hierarchy, and coordinates. The signed export has them. See `MeterService.list_meters`. |
| Filter before page? | `list_meters` filters, then `paginate`. `tests/test_meter_service.py` uses 3 rows, page size 1, and expects `total == 2`. |
| Why can coordinates be null? | Both `lat` and `lng` must be finite numbers. One bad value clears the pair. The geography route is only the fallback. |
| Why is `timezone` null? | The portal timestamp has no zone. `recorded_at` has no `Z` and no offset. |
| Why is a bad kWh null, not 0? | `parse_number` in `app/normalize.py`. Zero stays zero. |
| Why 502 for a bad login? | Callers of this API do not authenticate. 502 means this process could not open a portal session. See `app/main.py`. |
| What is cached? | Meter export and transformer list only. Consumption is not. Failed loads are not stored. `app/cache.py`. |
| What was not seen live? | Signed export page 2, and a session left until the one-hour cookie expired. Both are implemented and covered with fakes. |

Suggested order if time is short: `tests/test_signing.py`, `tests/test_portal_client.py`, `app/portal_client.py`, `app/services/meter_service.py`, then `PROTOCOL.md`.

## Features

- Login with a form post, then keep the session cookie in a `requests.Session`.
- Prove the session with the meter search route before treating login as successful.
- Sign the bulk meter export with HMAC-SHA256. The signing secret is fetched after login and is not returned by this API.
- List, search, and fetch meters from that export, including installation type, build, hierarchy, and coordinates.
- Fetch one meter's coordinates, using the dedicated geography route only when the export has no usable point.
- Fetch consumption history, with optional inclusive dates, chronological order, and explicit handling of bad rows.
- List and fetch distribution transformers, following the portal's `total` instead of assuming a fixed page count.
- Cache the export and the transformer list in memory for `CACHE_TTL_SECONDS` (default 300).
- Typed errors for timeouts, unreachable portal, bad portal payloads, and authentication failure.

## Architecture

```text
app/
  main.py                 FastAPI app, error handlers
  routes.py               /health and /api/v1 routes
  config.py               Environment settings
  portal_client.py        Login, session, signing, portal reads
  signing.py              HMAC-SHA256 message and digest
  normalize.py            Portal JSON to API models
  schemas.py              Response models
  cache.py                Process-local TTL cache
  services/meter_service.py
  services/transformer_service.py
tests/                    Pytest suite. No network and no real credentials.
scripts/check_portal.py   Optional read-only live check.
```

A request for meters loads the signed export once, validates it, and caches the normalized list. Search and pagination then happen in this process. Filtering runs before pagination, so `pagination.total` is the number of matches, not the size of the whole catalog.

Transformers are read page by page until `total` is reached, then cached. Consumption is not cached. Each history call goes to the portal.

The cache lives in the process. It is not shared across machines, and it is empty after a restart. A failed portal call is not stored. When the TTL ends, the next request loads again. Callers that arrive during a refresh wait for that refresh instead of starting a second one.

## Prerequisites

- Python 3.11 or newer. Development used Python 3.13.
- Network access to the portal when you want live data. The test suite does not need it.

## Installation

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux, activate with `source .venv/bin/activate` and copy the example with `cp .env.example .env`.

Edit `.env` and set `PORTAL_EMAIL` and `PORTAL_PASSWORD` to the operator account from the assignment. Do not commit `.env`.

## Configuration

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `PORTAL_BASE_URL` | no | `https://urja-ops.flockenergy.tech` | Portal origin, with no path. |
| `PORTAL_EMAIL` | yes, for live calls | empty | Operator email. |
| `PORTAL_PASSWORD` | yes, for live calls | empty | Operator password. Held as a secret string so it does not appear in `repr`. |
| `PORTAL_TIMEOUT_SECONDS` | no | `15` | Connect timeout and read timeout, in seconds. |
| `CACHE_TTL_SECONDS` | no | `300` | How long a successful meter export or transformer list is reused. `0` refreshes on every read. |

## Run

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The service listens on port 8000. Swagger UI is at `/docs`, ReDoc at `/redoc`.

This API does not ask callers for the portal password. The process uses the `.env` account. Bind it to localhost, or put it behind something that authenticates your own users, before exposing it beyond one machine.

## Tests

```powershell
pytest
```

The suite does not use portal credentials and does not open a network connection. The last run in this workspace was `39 passed`. Pytest also prints a Starlette deprecation warning because FastAPI's `TestClient` still imports `httpx`. The tests pass with that warning.

`scripts/check_portal.py` is separate. It logs in and prints counts only: meter total, export pages, transformer total, transformer pages, whether the first meter has coordinates, and how many consumption rows parsed. It does not print the password, cookie, or signing secret. Skip it when `.env` has no account.

## Examples

These bodies are from the live portal on 27 October 2026 for meter `J100000` and transformer `DT-001`.

Health does not call the portal:

```http
GET /health
```

```json
{"status": "ok", "portal": "not_checked"}
```

One meter:

```http
GET /api/v1/meters/J100000
```

```json
{
  "meter_id": "J100000",
  "serial_no": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "install_type": "Whole Current",
  "build": "legacy",
  "dt_code": "DT-001",
  "hierarchy": {
    "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
    "circle": {"name": "Circle 1", "code": "C-01"},
    "division": {"name": "Division 1", "code": "D-01"},
    "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
    "substation": {"name": "Substation 1", "code": "SS-01"},
    "feeder": {"name": "Feeder 1", "code": "F-001"},
    "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"}
  },
  "latitude": 26.938961002479868,
  "longitude": 75.83095696146852
}
```

Search, then page. `j100` matches meter ids. On the day of the live check every meter id started with `J100`, so this query matched the whole catalog. `pagination.total` is the filtered count.

```http
GET /api/v1/meters?query=SE33962&page=1&page_size=20
```

Location:

```http
GET /api/v1/meters/J100000/location
```

```json
{
  "meter_id": "J100000",
  "latitude": 26.938961002479868,
  "longitude": 75.83095696146852,
  "source": "export"
}
```

`source` is `geo_endpoint` when the geography route had to be called.

Consumption. Dates are inclusive and apply only to rows with a parsed timestamp. The response below is the real shape; `recorded_at_convention` and `interpretation` are long fixed strings, omitted here with `...`. The reading is the first live row for `J100000`.

```http
GET /api/v1/meters/J100000/consumption
```

```json
{
  "meter_id": "J100000",
  "timezone": null,
  "recorded_at_convention": "...",
  "interpretation": "...",
  "readings": [
    {
      "recorded_at": "2026-06-23T23:30:00",
      "source_timestamp": "23/06/2026 23:30",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "volt_r": 226.0
    }
  ],
  "rejected": []
}
```

`recorded_at` has no offset. `timezone` is always null. Rows that cannot be parsed stay in `rejected` and are not turned into zeros. For this meter the live history was 337 readings, every 30 minutes, from `2026-06-23T23:30:00` through `2026-06-30T23:30:00`, with nothing rejected. kWh did not decrease from one step to the next. The service still returns the register values as received. `start_date=2026-06-24&end_date=2026-06-24` keeps readings whose calendar date is 24 June and leaves 23 June and 30 June out.

Transformer:

```http
GET /api/v1/transformers/DT-001
```

```json
{
  "code": "DT-001",
  "name": "Malviya Nagar DT 1",
  "feeder_code": "F-001",
  "capacity_kva": 100.0
}
```

A missing meter or transformer:

```json
{"error": "not_found", "message": "Meter 'NOPE' was not found.", "details": null}
```

HTTP 404. A meter that exists but has no usable coordinates uses the same status with `"error": "location_unavailable"`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process is up. Does not call the portal. |
| `GET` | `/api/v1/meters` | Search and page meters. |
| `GET` | `/api/v1/meters/{meter_id}` | One meter. |
| `GET` | `/api/v1/meters/{meter_id}/location` | Numeric coordinates. |
| `GET` | `/api/v1/meters/{meter_id}/consumption` | History, optional `start_date` and `end_date` (`YYYY-MM-DD`). |
| `GET` | `/api/v1/transformers` | Page transformers. |
| `GET` | `/api/v1/transformers/{code}` | One transformer. |

List parameters:

- `query` on meters: optional case-insensitive substring of meter id or serial number. Other fields, including make, are not searched.
- `page`: integer, default 1, minimum 1.
- `page_size`: integer, default 20, minimum 1, maximum 100.

A page past the end returns an empty `data` array and the real `pagination.total`. `total_pages` is 0 when there are no matches.

Lookup of one meter or transformer is exact first, then case-insensitive.

Field names in this API are `snake_case`. The portal names they come from are listed on the models and in [PROTOCOL.md](PROTOCOL.md).

## Authentication and security

Callers do not log in to this API. The process logs in to the portal.

- Credentials come from the environment or `.env`.
- `.env` is gitignored. `.env.example` has empty secrets.
- The password is not hardcoded, not written to logs, and wrapped so a settings dump does not show it.
- The session cookie and the signing secret stay in memory. They are not response fields.
- Logs record status codes and paths. A filter redacts values that follow names such as `password`, `signingSecret`, `session_token`, `X-Signature`, and `X-Timestamp`.
- Login is one form POST. The client does not read browser cookies.
- Portal requests use a connect timeout and a read timeout. A rejected session is refreshed once, not in a loop.
- There are no write routes.

The live login also sends `Origin` and `Referer`. Without them the portal returned 403. See [PROTOCOL.md](PROTOCOL.md).

## Errors

Responses use `error`, `message`, and `details`. Stack traces, cookies, and portal secrets are not included.

| HTTP | `error` | When |
| --- | --- | --- |
| 404 | `not_found` | Unknown meter, transformer, consumption, or path. |
| 404 | `location_unavailable` | The meter exists and both coordinate sources failed. |
| 422 | `validation_error` | Bad page, page size, or date text. `details` lists the fields. |
| 422 | `invalid_date_range` | `end_date` is before `start_date`. |
| 405 | `method_not_allowed` | Anything other than GET on these routes. |
| 502 | `authentication_failed` | The portal login or session check failed, or credentials are missing. |
| 502 | `upstream_unavailable` | The portal could not be reached. |
| 502 | `upstream_error` | The portal returned an HTTP error. |
| 502 | `upstream_data` | The body was not usable JSON or did not have the expected shape. |
| 504 | `upstream_timeout` | The portal exceeded `PORTAL_TIMEOUT_SECONDS`. |
| 500 | `internal_error` | An unexpected bug. The client still gets no traceback. |

Authentication failures are 502, not 401. A 401 would mean the caller of this API failed to authenticate, and this API does not have that step. A 502 means this process could not establish a usable portal session.

If the portal is down and the cache is empty or expired, meter and transformer calls fail with one of the 502 or 504 codes above. Cached data from a successful load is still served until the TTL ends. After the TTL, a failed refresh is not hidden by serving the old copy. Consumption has no cache, so it fails immediately when the portal fails. The in-memory copy is discarded on process exit.

## Caching

`CACHE_TTL_SECONDS` applies separately to the meter export and the transformer list.

- Only a fully read, normalized success is stored.
- An exception leaves nothing new in the cache.
- Expiry causes the next call to load again.
- Two callers hitting an empty cache share one load.
- Consumption is read through every time. A per-meter TTL would be a reasonable follow-up; it is not here, because each meter's history is its own payload and the catalog is already cached.

At the current size, 403 meters and 40 transformers, holding both lists in memory is trivial.

## Decisions and trade-offs

The bulk export is the meter catalog. The paged search route omits `installType`, `build`, hierarchy, and coordinates, and it returns 20 rows at a time. One signed export returned all 403 meters, so local search and paging avoid a request per page. The trade-off is that a search still depends on that full download, and the result can be up to five minutes old.

Transformer paging follows `total` and `pageSize` from the portal. The public page size is independent, with a cap of 100, so a client can ask for all 40 transformers in one response.

Coordinates prefer the export so a meter list does not fan out into hundreds of geography calls. String coordinates from the geography route are parsed only as a fallback.

Timestamps stay naive. Adding `Z` would claim UTC without evidence.

Invalid measurements become null. Coercing them to zero would look like a real reading.

The service is synchronous and uses a lock around portal HTTP calls because a `requests.Session` is not a safe shared object. FastAPI runs these routes on its thread pool. Throughput is limited by the portal, which is the point of the cache.

Floats are the JSON number type. Values are checked with `Decimal` first so `"nope"` does not become a number, and a blank does not become zero. Binary floats are not exact for every decimal. For the live series, two decimal places, that is acceptable. A string decimal would preserve more and would be a worse fit for the "numeric values" requirement.

## Intentionally not built

- A hierarchy browser, a nearby-meter query, and extra filters beyond id and serial.
- A web dashboard.
- Redis, a database, or a job queue.
- Interval kWh computed from the cumulative series.
- Authentication for callers of this API.
- Background refresh before the TTL.

The catalog is small enough that those can wait. Building them before the login, the signed export, and the tests would have been the wrong order.

## Limitations

- Live behavior was checked once, on 27 October 2026: login, search check, keys, one signed export page (403 meters), two transformer pages (40 transformers), geography for `J100000`, and 337 consumption rows. Details are in [PROTOCOL.md](PROTOCOL.md). That check is not part of `pytest`.
- Signed export page 2 is implemented and covered with a fake response. The live export did not need it.
- The hour-long cookie was not left to expire against the portal. Renewal is covered by a mocked 401.
- Multiple server workers do not share the cache or the session.
- This API trusts its caller.
- Portal fields that this service does not map are dropped, so a new portal column will not appear until the model is updated.
- Coordinates are not range-checked.

## Live check from this workspace

`python scripts/check_portal.py` printed:

```text
login: ok
meters: 403
export_pages: 1
transformers: 40
transformer_pages: 2
sample_meter: J100000
sample_has_coordinates: True
location_source: export
consumption_readings: 337
consumption_rejected: 0
consumption_first: 2026-06-23T23:30:00
consumption_last: 2026-06-30T23:30:00
kwh_non_decreasing: True
```

A follow-up read, still without printing secrets, confirmed the search page size of 20, the transformer page size of 20, string geography fields, string energy fields, 30-minute spacing, and the session cookie attributes `Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax`.

## Publishing

The project is prepared locally and has not been committed or pushed. After review:

1. Confirm `git status` does not list `.env`.
2. Create a public git repository.
3. Commit the source, tests, `README.md`, `PROTOCOL.md`, `REFLECTION.md`, `openapi.json`, `requirements.txt`, and `.env.example`.
4. Do not commit `.env`, `.venv`, or the raw meter export.
5. Push, and send the repository URL back to the assignment contact.
