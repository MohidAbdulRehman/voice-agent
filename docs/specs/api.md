# REST API contract

FastAPI app at `src/intake/api/`, deployed as one Vercel Function (see Deployment below). It also serves interactive docs at `/docs`; the dashboard lives at `/dashboard` on the same origin. All validation goes through `intake.core`; route handlers contain no business rules.

## Envelope (every response, including errors)

```json
{ "data": { ... }, "error": null }
{ "data": [ ... ], "error": null }
{ "data": null, "error": { "code": "VALIDATION_ERROR", "message": "1 field is invalid.", "details": [
    { "field": "date_of_birth", "code": "in_future", "message": "Date of birth can't be in the future." } ] } }
```

FastAPI's built-in handlers (`RequestValidationError`, `HTTPException`, uncaught exceptions) are overridden, so no raw FastAPI error shape ever escapes. Timestamps are ISO 8601 UTC with a `Z` suffix. `date_of_birth` is always `MM/DD/YYYY`.

## Status codes

| Code | `error.code` | When |
|---|---|---|
| 200 | none | Successful GET, PUT or DELETE |
| 201 | none | POST created. Includes a `Location: /patients/{id}` header. |
| 400 | `BAD_REQUEST` | Malformed JSON, body isn't a JSON object, path id isn't a UUID, or a query param has a bad format (e.g. `date_of_birth=1990-03-05`, `limit=abc`) |
| 404 | `NOT_FOUND` | Unknown id **or soft-deleted** patient (GET, PUT, DELETE) |
| 405 | `METHOD_NOT_ALLOWED` | The path exists, but not with this method |
| 413 | `PAYLOAD_TOO_LARGE` | Body larger than 32 KB |
| 422 | `VALIDATION_ERROR` | Field rules fail, a required field is missing, an unknown field is present, a read-only field is present, or a PUT body is empty |
| 429 | `RATE_LIMITED` | Over the limit: 120 req/min per IP overall, 30 req/min for writes. Includes `Retry-After` (seconds). Requests rejected before a handler runs (unknown paths, malformed ids) aren't counted. |
| 500 | `INTERNAL_ERROR` / `DATABASE_ERROR` | Unexpected error. The body never includes stack traces or SQL. |
| 503 | `SERVICE_UNAVAILABLE` | `/health` only: the database is unreachable |

## Patients

### `GET /patients`
Lists patients that are not soft-deleted, newest first (`created_at DESC`, with `patient_id` as a tie-breaker).

Query params (all optional, combined with AND; each is validated server-side, and a bad format returns 400):
- `last_name`: case-insensitive exact match after name normalization.
- `date_of_birth`: `MM/DD/YYYY`.
- `phone_number`: any format; normalized to 10 digits first.
- `limit`: default 50, max 200.
- `offset`: default 0.

### `GET /patients/{patient_id}`
Returns 200 with the patient, or 404.

### `POST /patients`
The body contains all required fields and any optional ones. Unknown or read-only fields return 422. On success, returns 201 with the full created record, including `patient_id` and `preferred_language` (defaulted to `English`).

```json
POST /patients
{ "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/05/1990", "sex": "Female",
  "phone_number": "(512) 555-0100", "address_line_1": "1 Main St", "city": "Austin",
  "state": "TX", "zip_code": "78701" }

201 Created
{ "data": { "patient_id": "8f1c…", "first_name": "Jane", "last_name": "Doe",
            "date_of_birth": "03/05/1990", "sex": "Female", "phone_number": "5125550100",
            "email": null, "address_line_1": "1 Main St", "address_line_2": null,
            "city": "Austin", "state": "TX", "zip_code": "78701",
            "insurance_provider": null, "insurance_member_id": null,
            "preferred_language": "English", "emergency_contact_name": null,
            "emergency_contact_phone": null,
            "created_at": "2026-09-24T15:04:05Z", "updated_at": "2026-09-24T15:04:05Z" },
  "error": null }
```

API responses include `deleted_at` only on the DELETE response. The internal field `source_call_id` is never exposed.

### `PUT /patients/{patient_id}`
Partial update: only the fields present are changed.
- `null` clears an **optional** field.
- `null` on a required field returns 422.
- `null` on `preferred_language` returns 422. To reset it, send `"English"`.
- Unknown or read-only fields return 422. An empty body returns 422.
- `updated_at` is set by a database trigger.
- Returns 200 with the full updated record, or 404 if the patient doesn't exist or is soft-deleted.

### `DELETE /patients/{patient_id}`
Soft delete: sets `deleted_at`. The row is never removed. Returns 200 with the record, including `deleted_at`. A second DELETE returns 404. Deleted patients disappear from lists, lookups and duplicate detection.

## Read-only endpoints for the dashboard and bonuses

| Endpoint | Returns |
|---|---|
| `GET /patients/{id}/calls` | Calls linked to the patient: status, times, language, summary, transcript |
| `GET /patients/{id}/appointments` | The patient's appointments with doctor name |
| `GET /calls?status=&limit=&offset=` | Recent calls, newest first, without transcripts |
| `GET /calls/{call_id}` | One call with its full transcript |
| `GET /doctors` | Active doctors with specialty and languages |
| `GET /dashboard/config` | Public settings for the dashboard banner: `{clinic_name, assistant_name, phone_number, clinic_timezone}` |
| `GET /health` | `{status, database, version}`. Runs `SELECT 1`, so the uptime pinger also keeps the Supabase free project active. Returns 503 if the database is unreachable. |

**Live updates are polling, not push.** Vercel Functions can't hold WebSockets or a Postgres `LISTEN` connection, so the dashboard re-reads the list (and the open patient's calls and appointments) every 5 seconds while its tab is visible. That costs at most about 36 requests a minute per open tab, well inside the rate limit.

A call's `caller_number` is carrier metadata the caller never chose to give, so the API masks it to the last four digits (`***-***-0143`). The internal LiveKit room name is never exposed.

## Dashboard (`/dashboard`)

React + Vite + TypeScript, built into static files in `src/intake/api/static/`, which FastAPI mounts at `/dashboard`. On Vercel, the build copies that mount to the CDN, which serves the files with the dashboard's security headers from `vercel.json`; locally and in `Dockerfile.api`, FastAPI serves them. Either way it's the same origin as the API, so production needs no CORS.

Features:
- A patients table with search boxes that map to the three API filters.
- A patient detail panel: all fields, call history with summary and expandable transcript, and appointments.
- A calls tab.
- A "live" indicator showing when the data last refreshed (polling every 5 s), or that the API can't be reached and refreshing is being retried.
- A header banner with the phone number to call (from `PUBLIC_PHONE_NUMBER`).

The dashboard is **read-only** and unauthenticated, which is a documented limitation. It's responsive, accessible (labels, contrast, keyboard navigation) and hides soft-deleted patients.

## Cross-cutting

- **Sanitization:** normalization rules from `data-model.md`, a 32 KB body limit, parameterized SQL only, and control characters rejected.
- **CORS:** allow only `API_CORS_ORIGINS` (local dev: `http://localhost:5173`).
- **Security headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a basic Content-Security-Policy for the dashboard.
- **Logging:** one JSON line per request with method, path, status, duration and request id. Request bodies and query strings are not logged; patient payloads are logged only by the agent's registration event. Every response carries the id as `X-Request-ID`.
- **Caching:** API responses are `Cache-Control: no-store`, since they carry patient data.
- **No authentication** by design for the review. This is a documented trade-off; next step would be an API key for writes.
- **Deployment:** Vercel's Hobby plan, from `vercel.json`. The API is one Python function (entrypoint `app.py`) in `iad1` (Washington, D.C.), next to Supabase `us-east-1`; it installs only the API dependencies and connects through Supabase's **transaction pooler** (port 6543) with no client-side pool and no reused prepared statements. The build command builds the dashboard, and Vercel serves the app's `/dashboard` mount from its CDN (`[tool.vercel.fastapi.static] cdn = true` in `pyproject.toml`). `Dockerfile.api` (a multi-stage build: Node builds the dashboard, then the Python runtime) stays for local and Docker hosting; `docs/alternatives/render.yaml` is an unused Render alternative.
- **Rate limits on Vercel** are counted per function instance (in memory), so they are best-effort when several instances run at once.
