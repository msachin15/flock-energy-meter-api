# Portal protocol

Read this as the evidence file. Sentences that describe a request or a payload were checked. Paragraphs that start with "Inference" were not seen on a live response.

This note describes the Urja Meter Ops portal at `https://urja-ops.flockenergy.tech` as used by this service. It separates what was observed from what was inferred.

Observations below come from three places:

- The supplied login page, meter export, and energy sample.
- Read-only requests made with this service on 27 October 2026, using the assignment account from the local `.env`.
- The signing steps supplied with the assignment. The live signed export was accepted; the portal's JavaScript was not re-fetched in this session.

No cookies, passwords, or signing secrets are recorded here.

## Login

The login page is `GET /login`. The supplied HTML is a SvelteKit page. The form is `method="POST"` and has no `action`, so the browser posts to `/login`. The fields are `email` and `password`. There is no hidden CSRF input in that HTML.

The login call that succeeded is:

- `POST /login`
- `Content-Type: application/x-www-form-urlencoded`
- Body fields `email` and `password`
- Headers `X-Sveltekit-Action: true`, `Accept: application/json`, `Origin: https://urja-ops.flockenergy.tech`, and `Referer: https://urja-ops.flockenergy.tech/login`
- Redirects are not followed

The successful response was HTTP 200, `application/json`, and this body:

```json
{"type":"redirect","status":303,"location":"/meters"}
```

The HTTP status was 200. The redirect is described inside the JSON. `status: 303` and `location: "/meters"` are fields, not the response line.

The same POST without `Origin` and `Referer` returned HTTP 403 during this session. Those two headers were not in the original investigation notes. They were added after that 403.

The response sets one cookie:

- Name: `__Secure-better-auth.session_token`
- Attributes observed on the `Set-Cookie` header: `Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax`

The cookie value is not stored in this repository. `requests.Session` keeps it in memory and sends it on later requests. The client does not read a browser profile.

A login is not treated as successful unless all of the following are true:

- The response matches the redirect shape above, and the location is not the login page.
- The session cookie is present.
- `GET /portal/meters/search?q=&page=1` returns HTTP 200 JSON with a `data` array, an integer `total`, and a `page`. If `data` is not empty, the first object must have a string `meterId`.

On 27 October 2026 that check passed. The search payload's keys were `data`, `page`, `pageSize`, and `total`. `total` was 403, `page` was 1, `pageSize` was 20, and `data` contained 20 meters.

A failed form result is expected to use a JSON `type` other than `redirect`. That path is covered by tests with a synthetic response. A live bad password was not submitted.

## Session expiry

The cookie's `Max-Age` is 3600 seconds. This client does not decode the cookie or schedule its own timer. If a later portal response is HTTP 401 or 403, a redirect to `/login`, an HTML page, or JSON whose `type` is `redirect` and whose location is `/login`, the client drops the cookie and the signing secret and logs in once more. It does not keep retrying.

That retry path is tested with mocked responses. It was not forced against the live portal.

## Request signing

`GET /portal/keys` returns JSON whose only top-level key observed was `data`, and `data` contained `signingSecret`. The value was a non-empty string. It is not logged, returned by this API, or written here.

The supplied signing algorithm, which this service implements in `app/signing.py`, is:

1. Timestamp: `str(int(time.time()))`, Unix seconds.
2. Message: HTTP method, path, raw query string, and timestamp, joined by `\n`. The method is uppercased by this client.
3. HMAC-SHA256, UTF-8 secret as the key, UTF-8 message as the data.
4. Lowercase hexadecimal digest.

For the export that succeeded, the message was:

```text
GET
/portal/export
page=1
<unix seconds>
```

The headers sent are `X-Timestamp` and `X-Signature`. The query string signed is the same string appended to the URL.

On 27 October 2026 one signed `GET /portal/export?page=1` returned the full meter list. No second export page was requested.

Inference, not observed: if `total` were greater than the number of records in hand, this client would request `page=2`, `page=3`, and so on, each with its own timestamp and a signature over that page's raw query (`page=2`, not `page=1`). A safety stop at 100 pages prevents a bad `total` from looping. The live portal did not exercise page 2.

Other calls in this client are not signed. Live calls to search, keys, transformer pages, geography, and energy succeeded without `X-Signature`. That does not prove some unused portal route is unsigned.

## Endpoints

| Portal request | Observed role |
| --- | --- |
| `POST /login` | Form login. |
| `GET /portal/meters/search?q=&page=1` | Paged meter search. Used to prove the session, not as the source of the full catalog. |
| `GET /portal/keys` | Returns `data.signingSecret`. |
| `GET /portal/export?page=1` | Signed bulk meter export. |
| `GET /portal/meters/{meterId}/geo` | Coordinates as strings. |
| `GET /portal/meters/{meterId}/energy` | Consumption history. |
| `GET /portal/dts?page=1` | Paged distribution transformers. |

Meter ids in those paths are URL-encoded by this client.

## Meter search

The live search envelope is:

```json
{
  "data": [],
  "total": 403,
  "page": 1,
  "pageSize": 20
}
```

Each search row has `meterId`, `serialNo`, `make`, `phaseType`, `installStatus`, and `dtCode`. It does not include `installType`, `build`, `hierarchy`, or `geo`.

Checked queries, reported as totals only:

- Empty `q`: total 403.
- `J100000` and `j100000`: total 1, meter `J100000`. Matching is case-insensitive.
- `J100402`: total 1.
- `SE33962`, `SE339`, and `33962`: total 1, meter `J100000`. Serial matching is partial, not only exact.
- `J100`: total 403. Every current meter id begins with `J100`, so this does not by itself prove a general substring rule, but together with the serial checks it behaves like a case-insensitive substring over meter id and serial.
- `HPL`: total 0. Make is not searched.
- `no-such-meter`: total 0.

This API does not proxy that endpoint for listing. It filters the bulk export with the same case-insensitive substring rule and keeps export order.

## Bulk export

`GET /portal/export?page=1`, signed, returned an envelope. This client read 403 records from `data`, and `total` matched that length, so it stopped after one page.

The supplied `meter-export.json` is a JSON array, which is `data` saved without the envelope. The parser accepts both shapes. Production calls the live endpoint. The file is not embedded in the service.

Each live export record has:

`meterId`, `serialNo`, `make`, `phaseType`, `installStatus`, `installType`, `build`, `dtCode`, `hierarchy`, `geo`.

`installType` and `build` are present on the export and absent from search rows. This API keeps them.

`hierarchy` contains `zone`, `circle`, `division`, `subdivision`, `substation`, `feeder`, and `dt`. Those objects use `name` and `code`.

`geo` uses numeric `lat` and `lng`.

On the live export of 403 meters, blank hierarchy values were real and were not dropped:

- `circle.code` empty on 6 meters, `circle.name` empty on 5.
- `feeder.code` empty on 5, `feeder.name` empty on 3.
- `substation.code` empty on 3.

An empty string is a different fact from a missing level. The API preserves `""` and uses `null` only when the level or the field is absent. The supplied export showed the same pattern, including meter `J100011` (`circle.code` empty) and meter `J100162` (`feeder.name` empty).

## Geography

`GET /portal/meters/J100000/geo` returned:

```json
{"data": {"latitude": "<string>", "longitude": "<string>"}}
```

Both values were strings, unlike export `geo.lat` and `geo.lng`, which are numbers.

This API prefers the export. For `J100000` the export coordinates were finite numbers, so the public location resource reports `source: "export"`. The geography endpoint is called only when either export coordinate is missing or not a finite number. A partial point is not returned. `0` is a valid coordinate; it is not treated as missing.

## Consumption

`GET /portal/meters/J100000/energy` returned `data` with 337 objects. Each object has string fields `timestamp`, `kwh`, `kvah`, and `voltR`.

The timestamp form is `DD/MM/YYYY HH:mm`. The first live value was `23/06/2026 23:30` and the last parsed instant was `2026-06-30T23:30:00`. All 337 timestamps matched that pattern. The spacing between consecutive readings was 30 minutes in every case. Nothing in the payload names a timezone, so this API does not add `Z` or an offset.

For this meter, numeric `kwh` was present on every row and each step was greater than or equal to the previous one. `kvah` in the supplied sample moves the same way. That is consistent with cumulative register readings. The portal does not say that, and this API does not convert the series into interval consumption.

Invalid numbers become `null`. They are not stored as zero. A row whose timestamp does not match `DD/MM/YYYY HH:mm` is listed under `rejected` instead of being dropped silently. The live `J100000` history had zero rejected rows.

## Transformers

`GET /portal/dts?page=1` returned:

- Keys: `data`, `page`, `pageSize`, `total`
- `total`: 40
- `page`: 1
- `pageSize`: 20
- `data` length: 20

Row fields: `code`, `name`, `feederCode`, `capacityKva`.

The client requested the next page because 20 is less than 40, then stopped. It does not assume the catalog is two pages. It stops when the collected count reaches `total`, and it errors if a page is empty before that. A hard stop at 100 pages is only a loop guard.

Meter `dtCode` matches transformer `code`. The live meter `J100000` has `dtCode` `DT-001`, and transformer `DT-001` is `Malviya Nagar DT 1` with `feederCode` `F-001` and `capacityKva` 100. The export's `hierarchy.dt` for that meter carries the same name and code. `hierarchy.feeder.code` for that meter is `F-001`.

## Normalization

| Portal field | API field | Notes |
| --- | --- | --- |
| `meterId` | `meter_id` | Required. Surrounding whitespace is stripped. |
| `serialNo` | `serial_no` | String, may be empty. |
| `make` | `make` | |
| `phaseType` | `phase_type` | |
| `installStatus` | `install_status` | |
| `installType` | `install_type` | Export only. |
| `build` | `build` | Export only. |
| `dtCode` | `dt_code` | Empty string preserved. |
| `hierarchy.*` | `hierarchy.*` | `name` and `code`. Empty strings preserved. |
| `geo.lat`, `geo.lng` | `latitude`, `longitude` | Numbers. Both required or both null. |
| `latitude`, `longitude` | `latitude`, `longitude` | Geography endpoint. Strings parsed as numbers. |
| `code` | `code` | Transformer. |
| `feederCode` | `feeder_code` | |
| `capacityKva` | `capacity_kva` | Number, or null if not finite. |
| `timestamp` | `recorded_at` and `source_timestamp` | Naive local conversion. Original string kept. |
| `kwh`, `kvah` | `kwh`, `kvah` | Numbers or null. |
| `voltR` | `volt_r` | Number or null. |

Measurements are parsed with `Decimal` and then stored as JSON numbers. Non-numeric text, blanks, booleans, and non-finite values become null. A real zero stays zero.

`recorded_at` is `YYYY-MM-DDTHH:mm:ss` with no offset. `source_timestamp` is the portal string.

## Unresolved

- Export page 2 was not needed, so the signed multi-page path is untested against the portal.
- Session renewal after the hour was not left running against the portal.
- A wrong password was not sent.
- No portal route besides the ones in the table was mapped.
- The portal does not document whether `kwh` is a cumulative register. The monotonic series is only evidence.
- Search ranking, if any, was not compared beyond totals and the first id.
- Coordinates are not checked against a valid latitude/longitude range.
