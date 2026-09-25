# Test plan

**Goal:** every requirement in `docs/private/REQUIREMENTS.md` has automated evidence, or a documented manual check where automation isn't practical (real phone audio).

```
            /  Manual phone calls (≤ 4, scripted)  \     Real telephony + voice quality
           /  Agent evals: LLM-judged conversations   \  Opt-in: `pytest -m evals` (uses LLM credits)
          /  Agent tool tests (real Postgres, no LLM)   \
         /  API integration tests (httpx + real Postgres) \
        /  DB constraint + parity tests (real Postgres)    \
       /  Unit tests: validation, normalization, speech     \   Many, fast
```

**Rules:**
- Tests **never** touch Supabase. They use `TEST_DATABASE_URL` pointing at the Docker Postgres (`docker compose up -d db`). Each test run applies migrations to a fresh schema or database and truncates between tests.
- CI (GitHub Actions) runs lint and everything except `evals`, with a `postgres:16` service container. Evals run manually before submission.
- Use obviously fake data only: 555-01XX numbers and `example.com` emails.

## 1. Unit tests: `tests/unit/`

Table-driven (`pytest.mark.parametrize`), one module per concern:
- **`test_validation.py`**: every rule and error code in `data-model.md`. That includes names (José, O'Brien, Smith-Jones accepted; Van Buren, Jane2, J., -Jane rejected; 50 vs 51 chars) and date of birth (02/29/2024 is valid; 02/29/2023 is `not_a_real_date`; tomorrow in the clinic time zone is `in_future`, tested with a frozen clock across midnight UTC vs Eastern; 12/31/1899 is `too_old`; 1990-03-05 is `invalid_format`). Also phone formats (`(512) 555-0100`, `+1 512 555 0100` accepted; `555-0100` and `112-555-0100` rejected), the ZIP forms, state codes and names, member ID stripping, and language mapping.
- **`test_speech.py`**: English and Spanish spoken forms for every field, plus read-back group order. Include an update read-back that contains only changed fields.
- **`test_prompt_loader.py`**: comments are stripped, every `{{placeholder}}` is filled, and no `{{` remains.

## 2. Database tests: `tests/db/`

- **Parity:** for each invalid example from the unit tests, a raw SQL insert must raise `CheckViolation`. This proves the database agrees with Python.
- **Exclusion constraints:** overlapping doctor bookings and overlapping patient bookings are rejected; a cancelled appointment frees its slot.
- **Idempotency:** a second patient with the same `source_call_id` is rejected.
- **`available_slots()`:** respects the day of week, excludes booked slots, excludes slots less than 1 hour away, and handles the time zone correctly across a daylight-saving boundary (use dates in early November).
- **Triggers:** `updated_at` changes on update; `intake_changes` NOTIFY fires on insert, update and delete.
- **Migration runner:** idempotent (running it twice is a no-op), and the seed can run twice.

## 3. API integration tests: `tests/api/` (the assessment's "automated tests for the API layer" bonus)

Use `httpx.AsyncClient` against the app with the test database. **Every endpoint × every status code it can return**, including at least:

| Case | Expect |
|---|---|
| POST a valid patient (phone in any format) | 201, `Location` header, normalized phone, `preferred_language = English`, DOB `MM/DD/YYYY` |
| POST missing `last_name` + future DOB | 422 with **two** entries in `details` |
| POST with an unknown field / with `patient_id` | 422 (`unknown_field` / `read_only`) |
| POST malformed JSON / a JSON array body | 400 |
| GET `/patients?last_name=doe` (case-insensitive) | 200, matches |
| GET with `date_of_birth=03/05/1990` / `=1990-03-05` | 200 / 400 |
| GET with `phone_number=(512) 555-0100` | 200, normalized match |
| GET `/patients/not-a-uuid` / random UUID | 400 / 404 |
| PUT partial (`city` only) | 200, only `city` changed, `updated_at` advanced |
| PUT `{}` / `last_name: null` / `email: null` | 422 / 422 / 200 with email cleared |
| DELETE, then GET / PUT / DELETE again / list | 404 / 404 / 404 / absent |
| Soft-deleted row still in the DB | Confirmed via raw SQL |
| Database down (monkeypatch the engine to raise) | 500 `DATABASE_ERROR` in the envelope |
| Rate limit exceeded | 429 in the envelope |
| Every response | Matches the envelope schema (a shared assertion helper) |
| `/health` | 200 when the database is up; 503 when it's down |

## 4. Agent tool tests: `tests/agent/test_tools.py` (no LLM)

Call the tool functions directly with a fake `RunContext` and the test database:
- `prepare_record` returns incomplete / invalid / duplicate / ok, and the read-back is in the session language.
- `commit_record`: not_confirmed, stale_draft, saved; committing twice creates exactly one patient.
- `commit_record` with `SIMULATE_DB_FAILURE=true`: the first call returns `retryable: true`, the second returns `retryable: false`, the call status becomes `failed`, and the payload is kept.
- Update path: only changed fields are written, and `calls.patient_id` is linked.
- The shutdown handler after an uncommitted draft gives status `abandoned`, a stored transcript, and no patient row.
- `book_appointment` race: book the same slot twice and the second returns `slot_taken` with alternatives.

## 5. Agent behavior evals: `tests/evals/` (marked `evals`; opt-in)

Use LiveKit Agents' built-in testing helpers (text-only sessions with an LLM judge; look up the current API via the `livekit-docs` MCP). The judge is the agent's primary model on LiveKit Inference. **Each scenario asserts both the tool calls made and a judged intent.** These mirror what reviewers will try. There are seven, all in English, to keep the free LiveKit Inference credit for demo calls; each run ends by printing the tokens it used and their cost.

| # | Scenario (scripted caller turns) | Must happen |
|---|---|---|
| E1 | Happy path, all required fields in order | The optional details are offered before the read-back; `prepare_record` ok, the read-back covers every group, `commit_record` only after "yes", closing uses "You're all set, [name]." with `end_call(completed)` |
| E2 | Optional offer accepted: insurance + emergency contact | Both are in the read-back and saved |
| E3 | "Actually, my last name is spelled D-A-V-I-S, not D-A-V-I-E-S" | The draft is corrected and only the last name is read back |
| E4 | A DOB in the future, then "My number is 555-0100" (7 digits), then "Can we start over?" | Each invalid answer is re-asked on its own; `start_over`, then the agent asks for the name again; no commit |
| E5 | Phone matches a seeded patient | The exact duplicate sentence, then the update path writes changes only |
| E6 | After saving, schedule an appointment | Slots offered (≤ 3); booking confirmed with the doctor's name |
| E7 | "Is this a real person?" / "I have chest pain" | Discloses virtual assistant / 911 guidance + `end_call(emergency)` |

Left out to save credits, and covered elsewhere:
- **A failing database:** the tool tests (§4) cover it, with `retryable: true`, then `false`, and a `failed` call.
- **Spanish:** manual call #4.
- **A "no" at the read-back:** the tool tests cover stale drafts.
- **Details given out of order:** manual call #2.

## 6. Dashboard: `dashboard/` (light)

- Component smoke test (Vitest) for the patients table rendering the API envelope.
- Optional Playwright test: open `/dashboard`, insert a row via SQL, and assert it appears within a few seconds without a page reload, which proves the polling works.

## 7. Manual phone script (the free plan allows 50 inbound minutes/month, so ≤ 4 calls, under 3 minutes each)

Run the phone calls only **after** evals E1–E7 pass in text mode. To listen back afterwards, turn on the project's Agent observability first (`agent.md` §2, Recording). Record results in `docs/manual-test-log.md` (date, scenario, pass/fail, notes on voice quality and latency):
1. Happy path + appointment, in English.
2. Spelled correction + a future DOB + start over, giving the address before the name.
3. Call again from the same phone: duplicate detection, then update.
4. "Hablo español" path.

After each call, verify via `GET /patients?phone_number=…` and `GET /calls`. Check that the transcript and summary are stored.

## 8. Pre-submission smoke check: `scripts/smoke.sh`

Curls the live API: health, list, create, get, put, delete, and the 400/404/422 cases, with the envelope checked by `jq`. It exits non-zero on any mismatch. Run it against the Vercel URL right before submitting and again on review day. CI also runs it against the Docker image behind a transaction-mode PgBouncer, the same kind of pooler the Vercel deployment uses.
