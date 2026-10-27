# Reflection

These answers match the code in this repo. The login mistake is the live HTTP 403 described in `PROTOCOL.md` and in `PortalClient.login`. The criticisms in the last section are still true: tests do not call the portal, and export page 2 was not seen live.



## What assumptions did you make?

I assumed the form with no `action` posts to `/login`, and that a login is real only after the session cookie exists and the meter search returns meter JSON. I assumed the supplied HMAC inputs are the whole signing scheme, and that only the export needs those headers, because the other reads succeeded without them. I assumed that if an export page ever comes back short of `total`, the next page should be signed over `page=N` rather than reused from page 1. The live catalog fit in page 1, so that branch is an inference. I treated blank hierarchy codes as data, not as corruption. I treated portal timestamps as naive local datetimes. I treated the monotonic kWh series as an observation, not as permission to compute interval energy. I also assumed a caller of this API is trusted: the service holds the portal password, and the API itself has no user login.

## Which part was the most difficult, and how did you get unstuck?

The first live login matched the notes and still returned HTTP 403. The body was not a normal failed-password payload, and adding retries would not have helped. I sent one direct form POST that included `Origin` and `Referer`, still without printing the password or the cookie, and that call returned 200, the redirect JSON, and `Set-Cookie` for `__Secure-better-auth.session_token`. Those two headers were the missing piece. After that, the signed export, both transformer pages, and the energy history came back on the first attempt. The signing code was less mysterious once the tests locked the newline message to the exact query string on the URL.

## If you had another day, what would you improve?

I would record a sanitized cassette of the live responses so the integration could be replayed without the portal account. I would cache consumption per meter for a short TTL, and I would expose the network hierarchy and a nearby-meter query on top of the coordinates that are already normalized. I would also run the process long enough to see the hour-long cookie expire, and I would split "bad password" from "login rejected before the form was considered" in the logs. The log line today only has the status code, which was enough to find the 403 but not enough to explain it.

## What mistake did you make while solving this?

I treated the supplied login notes as a complete request. They were right about the method, the form fields, the SvelteKit header, the JSON redirect, and the cookie, and I stopped there. The portal still answered 403 until `Origin` and `Referer` were set. I burned a live attempt on a client that could not succeed, then had to compare that call with a browser-shaped form POST. The fix is small. The miss was assuming the notes listed every header that matters.

## If you were reviewing your own submission, what would you criticise?

The tests never talk to the portal. They would stay green if the portal renamed a field. The live check was a script run once, not a repeatable test in this repo. Export page 2 is implemented and unit-tested with fakes, and it was not seen live. The cache is inside one process, so two workers would each log in and could disagree until their TTLs lapse. Consumption is fetched again on every request. Listing meters always pulls the full export first, which is fine for 403 rows and a poor fit for a much larger catalog. JSON numbers are floats, so a later meter with more decimal places would not round-trip exactly. The API also has no authentication of its own. Anyone who can reach the port can read the portal through this process.
