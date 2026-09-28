# Riverside Family Clinic: Voice Patient Registration

A voice AI agent you can phone to register as a new patient. It collects US patient demographics in natural conversation, confirms everything back, and saves the record to Postgres. A REST API and a live dashboard expose the data.

## Try it

| | |
|---|---|
| 📞 **Call** | **+1 (484) 317-5014** |
| 🌐 **API base URL** | **https://riverside-intake.vercel.app** (interactive docs at `/docs`) |
| 📊 **Dashboard** | **https://riverside-intake.vercel.app/dashboard/** (patients), **[/dashboard/#calls](https://riverside-intake.vercel.app/dashboard/#calls)** (every call with its summary and transcript) |

**Things to try on a call:**
- Register normally.
- Spell a correction ("Actually, it's D-A-V-I-S").
- Give a future birth date.
- Say "Can we start over?"
- Say "Hablo español".
- Call back from the same number to see duplicate detection.
- Book an appointment after registering.

**Testing notes for reviewers:**
- **No sign-up or credentials.** Call the number, and use the API and dashboard as they are.
- **Please use made-up details.** The dashboard and API are public. Any US-format number works, such as `512-555-0123`.
- **Maya can take 10–20 seconds to answer the first call after a quiet spell.** The free plan stops the agent when nobody is calling, and that call starts it again. Please stay on the line.
- **The first API request after a quiet spell takes a second or two** while a serverless instance starts.
- **Please keep calls to a few minutes.** Everyone shares the free plan's 50 phone minutes a month, and calls stop connecting once they're used up (they reset on the 1st).
- **After a call,** the dashboard shows it within about 5 seconds: the patient under Patients, and the transcript and summary under Calls. Caller IDs show only their last 4 digits.

## Architecture

```mermaid
flowchart LR
    caller([Caller])
    lk["LiveKit Cloud<br/>US number · SIP · dispatch rule"]
    subgraph agentbox ["Voice agent · LiveKit Cloud, us-east"]
        pipeline["Deepgram STT → LLM → Cartesia TTS<br/>turn detector · noise cancellation"]
        tools["9 tools"]
    end
    subgraph vercel ["Vercel"]
        dashboard["React dashboard<br/>(CDN)"]
        api["FastAPI<br/>(Python function, iad1)"]
    end
    core["intake.core<br/>validation · spoken forms · services · SQL"]
    db[("Supabase Postgres<br/>constraints · triggers")]

    caller -->|phone call| lk
    lk -->|a room per call| pipeline
    pipeline <--> tools
    dashboard -->|polls every 5 s| api
    tools --> core
    api --> core
    core -->|"agent: session pooler<br/>API: transaction pooler"| db
```

A call to the number reaches LiveKit Cloud. Its dispatch rule creates a room for the call and sends in the `patient-intake` agent, a Python [LiveKit Agents](https://docs.livekit.io/agents/) worker deployed to LiveKit Cloud. The agent greets the caller with a fixed line, then runs a loop: Deepgram speech-to-text, an LLM (`gpt-4.1-mini` through LiveKit Inference, with Groq as a fallback), and Cartesia text-to-speech (with Deepgram as a fallback).

The LLM decides what to ask next. To look anything up or save anything, it calls one of nine tools, which call `intake.core` in-process. That's the same validation and service layer the REST API uses. `prepare_record` validates the details and returns a read-back written by code, and `commit_record` saves only after the caller confirms that exact version. When the call ends, however it ends, a shutdown handler stores the transcript, a short summary and the outcome on the call's row.

The API is FastAPI running as one Vercel Function, and it reads the same Postgres. So a new registration appears on the dashboard within about 5 seconds.

### Separation of concerns

| Boundary | Where | What it owns |
|---|---|---|
| Telephony | LiveKit Cloud (number, dispatch rule), `Dockerfile` + `livekit.toml`, `src/intake/agent/session.py` | Dispatch as `patient-intake` and caller ID from the SIP participant. The STT, LLM and TTS wiring with their fallbacks. Turn detection, noise cancellation and background audio. Silence handling and the call time limit. |
| LLM logic | `src/intake/agent/`: `prompts/`, `tools.py`, `state.py`, `scripts.py`, `lifecycle.py` | The commented system prompt and its loader, and the 9 tools, which return structured facts, never prose. Per-call state, the fixed lines (greeting and silence) in English and Spanish, and the call record: transcript, summary and final status. |
| Data layer | `src/intake/core/`, `src/intake/db/`, `db/migrations/`, `db/seed.sql` | Normalization and validation (one error code per field), spoken forms and read-back groups, parameterized SQL, and the services both the agent and the API call. The schema's constraints mirror the Python rules. |
| API | `src/intake/api/`, `app.py`, `vercel.json` | HTTP only: routing, the `{data, error}` envelope, status codes, rate limits and security headers. No business rules. |
| Dashboard | `dashboard/` | A read-only React app served at `/dashboard`. |

`intake.core` imports nothing from FastAPI or LiveKit, and `api` and `agent` depend on `core` but never on each other. `tests/unit/test_layering.py` enforces both rules.

### Prompt engineering

The prompt is [`src/intake/agent/prompts/system_prompt.md`](src/intake/agent/prompts/system_prompt.md). Comments throughout explain each rule, including the rules added after an eval or a test call caught a problem. `loader.py` strips the comments before sending, so they cost no tokens. The design:
- **Written for the ear.** Everything is spoken, so the style rules come first: one or two short sentences, one question at a time, no lists or field names, and digits grouped the way people say them.
- **Short imperative rules.** Small, fast models follow them more reliably than prose, and a short prompt matters because it's resent every turn.
- **Facts from tools, not the model.** The read-back text comes from `core/speech.py`, with exact spellings and digits ("five one two, five five five…"). `prepare_record` returns it, and Maya reads it out verbatim.
- **Guarantees in code, not just in the prompt:**
  - `commit_record` accepts only the latest draft, and only with the caller's yes.
  - Any correction makes a new draft.
  - One call can create at most one patient, because `source_call_id` is unique.
- **Tools return facts, not prose.** Every tool returns a `status` plus data and never raises to the LLM. Errors are codes the prompt knows how to put into words.
- **Fixed text where it matters.** The greeting, which includes the virtual-assistant disclosure, and the silence lines are scripted. The sentences the assessment expects word for word are marked "say exactly".

## Tech stack & why

| Layer | Choice | Alternatives considered | Why |
|---|---|---|---|
| Telephony + agent hosting | LiveKit Cloud: phone number, SIP, agent deployment | Twilio plus a custom server, Vapi, Retell | A real US number and 50 inbound minutes on the free plan, with no card needed. The agent is open-source LiveKit Agents code in this repo, not configuration in a vendor dashboard. The deployment comes with recordings and transcripts (Agent insights). |
| Voice pipeline | Speech-to-text → LLM → text-to-speech | A realtime speech-to-speech model (OpenAI Realtime, Gemini Live) | Registration needs exact spellings and digits. A separate transcript can be inspected, and the read-back comes from code rather than a model's voice. Each stage can also fall back on its own. |
| Speech-to-text | Deepgram Nova-3, multilingual | Whisper, AssemblyAI | Streaming with low latency, English and Spanish in one model (callers can switch mid-call), and keyterm hints for answers like "Decline to Answer". |
| LLM | `gpt-4.1-mini` via LiveKit Inference; fallback Groq `llama-3.3-70b-versatile` | GPT-4o, Claude | Fast and dependable at tool calls for its price. LiveKit Inference needs no extra key and includes $2.50 of free use a month. Groq is a different provider, so one provider's outage doesn't end the call. |
| Text-to-speech | Cartesia Sonic-3; fallback Deepgram Aura-2 | ElevenLabs, OpenAI TTS | Natural, low-latency voices in English and Spanish. The fallback keeps the call going if Cartesia fails or its credit runs out. |
| Turn-taking and noise | LiveKit's turn detector with Silero VAD; Krisp noise cancellation | A silence timeout alone | The turn detector doesn't jump in while a caller pauses mid-phone-number, and callers can interrupt Maya. Krisp's telephony voice isolation cleans up callers in cars and cafés. The turn detector is free when deployed to LiveKit Cloud. |
| API | FastAPI + Pydantic v2 | Flask, Django REST Framework | Async, typed models and generated interactive docs; the core layer's Pydantic models are reused as they are. |
| Database | Supabase Postgres (free) | Neon, a managed RDS | Real Postgres: the data model is enforced with check and exclusion constraints and triggers, and it's reachable over IPv4 through Supabase's pooler. |
| API + dashboard hosting | Vercel Hobby (free, no card) | Render free web service (needs a credit card), Fly.io | Vercel runs the FastAPI app as one Python function with no server to manage and serves the dashboard from its CDN. The function runs in `iad1` (Washington, D.C.), next to Supabase `us-east-1`. |
| Database connections | API: Supabase's transaction pooler (port 6543). Agent: the session pooler (port 5432). | Direct connections | Serverless instances come and go, so the pooler keeps Postgres connections bounded; the API holds no pool of its own. The long-running agent keeps a small pool on the session pooler. |

## Data model & API

- **Tables:** one `patients` table, soft-deleted with `deleted_at` and never removed. Beside it, `calls` holds each conversation's transcript, summary, outcome and last draft. `doctors`, `doctor_schedules` and `appointments` are mock scheduling data.
- **Rules checked twice:** every field rule is enforced in `intake.core.validation`, which gives a stable error code per field, and again by a Postgres check constraint. The tests check that the two agree.
- **No double bookings:** exclusion constraints stop overlapping appointments.
- **Full details:** [`docs/specs/data-model.md`](docs/specs/data-model.md) has the field rules and spoken forms; [`docs/specs/api.md`](docs/specs/api.md) has the contract and status codes.

Every response is `{"data": ..., "error": null}` or `{"data": null, "error": {"code", "message", "details"}}`. Dates of birth are `MM/DD/YYYY`, and timestamps are UTC ISO 8601.

```bash
API=https://riverside-intake.vercel.app

# Create (201). The phone can be in any format; it's stored as 10 digits.
curl -s -X POST "$API/patients" -H 'Content-Type: application/json' -d '{
  "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/05/1990", "sex": "Female",
  "phone_number": "(512) 555-0100", "address_line_1": "1 Main St", "city": "Austin",
  "state": "TX", "zip_code": "78701"}'

# List, newest first, with optional filters (last_name, date_of_birth, phone_number, limit, offset)
curl -s "$API/patients?last_name=doe&phone_number=512-555-0100"

# Get one: use the patient_id from the create response
curl -s "$API/patients/<patient_id>"

# Update: only the fields sent change; null clears an optional field
curl -s -X PUT "$API/patients/<patient_id>" -H 'Content-Type: application/json' \
  -d '{"city": "Round Rock", "email": "jane.doe@example.com"}'

# Soft delete: the record drops out of lists and lookups, and a second DELETE returns 404
curl -s -X DELETE "$API/patients/<patient_id>"
```

A validation failure returns 422 with one entry per field:

```bash
curl -s -X POST "$API/patients" -H 'Content-Type: application/json' -d '{
  "first_name": "Jane", "date_of_birth": "01/01/2090", "sex": "Female",
  "phone_number": "5125550100", "address_line_1": "1 Main St", "city": "Austin",
  "state": "TX", "zip_code": "78701"}'
# {"data": null, "error": {"code": "VALIDATION_ERROR", "message": "2 fields are invalid.", "details": [
#   {"field": "last_name", "code": "required", ...}, {"field": "date_of_birth", "code": "in_future", ...}]}}
```

The dashboard also uses read-only endpoints for calls, appointments and doctors, listed in `api.md` and at `/docs`.

## Local setup

1. **Prerequisites:** Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22.12+ and Docker. You only need the [LiveKit CLI](https://docs.livekit.io/reference/developer-tools/livekit-cli/) to deploy.
2. `git clone https://github.com/MohidAbdulRehman/voice-agent.git && cd voice-agent`
3. `cp .env.example .env`, then fill it in (see [Environment variables](#environment-variables)).
   - For the API and tests alone, only `DATABASE_URL` matters. To use the local database, set it to `postgresql://postgres:postgres@localhost:5433/intake`.
   - The agent also needs the LiveKit, Deepgram, Cartesia and Groq keys.
4. `docker compose up -d db` starts Postgres 16 on `localhost:5433`, with the `intake` and `intake_test` databases.
5. `uv sync --all-extras`. The extras are the local server and the agent; the API itself needs only the base set.
6. `uv run python -m intake.db.migrate && uv run python -m intake.db.seed` creates the schema and the demo data (2 patients, 3 doctors).
7. `cd dashboard && npm ci && npm run build && cd ..` builds the dashboard into `src/intake/api/static/`.
8. `uv run uvicorn intake.api.main:app --reload` starts the API. The dashboard is at http://localhost:8000/dashboard/ and the interactive docs at http://localhost:8000/docs.
9. `uv run pytest` runs the test suite against `intake_test`.
10. `uv run python -m intake.agent console` lets you talk to the agent in your terminal.
    - Add `--text` to type instead of speaking.
    - Add `--record` to save the conversation's audio (caller on the left channel, agent on the right) under `console-recordings/`.

## Deployment

| Part | Where | Configured by |
|---|---|---|
| REST API + dashboard | Vercel Hobby, function region `iad1` | `vercel.json` + `app.py` |
| Voice agent | LiveKit Cloud, region `us-east` | `Dockerfile` (LiveKit Cloud builds it) + `livekit.toml` |
| Database | Supabase (free) | `python -m intake.db.migrate` and `seed` |

### Vercel: what `vercel.json` does

- Runs the FastAPI app (`app.py` re-exports `intake.api.main:app`) as one Python function in `iad1`.
- Installs only the API's dependencies.
  - Vercel runs `uv sync --no-dev` from `uv.lock`, which skips the `server` (uvicorn) and `agent` extras.
  - The function bundle is about 50 MB, or about 70 MB with the bytecode Vercel precompiles, out of a 500 MB limit.
  - `excludeFiles` also leaves out the agent code, tests, docs, the dashboard sources and the migrations.
- Builds the dashboard into `src/intake/api/static/`, which the app mounts at `/dashboard`. Vercel copies that mount to its CDN (`[tool.vercel.fastapi.static] cdn = true` in `pyproject.toml`), and `vercel.json` gives those files the same security headers the API sends.
- Redirects `/` to `/dashboard/`, and calls `/health` once a day (a Vercel Cron Job). `/health` runs `SELECT 1`, so the free Supabase project never pauses for inactivity.

### Vercel: environment variables

Set these in the Vercel project (Settings → Environment Variables), then redeploy: a change applies only to new deployments. Never commit them.

| Name | Required | Value |
|---|---|---|
| `DATABASE_URL` | Yes | Supabase's **transaction pooler** URI (port **6543**): Supabase → Connect → Transaction pooler, with the database password filled in. It's the local session-pooler URL with `:5432` changed to `:6543`. |
| `PUBLIC_PHONE_NUMBER` | For the banner | The number to call, e.g. `+14843175014`; the dashboard banner hides without it. |
| `CLINIC_NAME`, `AGENT_PERSONA_NAME`, `CLINIC_TIMEZONE`, `LOG_LEVEL` | No | The defaults match the demo. |

After deploying, check the live API: `bash scripts/smoke.sh https://<project>.vercel.app`.

`Dockerfile.api` builds the same API and dashboard into one image for local or Docker hosting. `docs/alternatives/render.yaml` is an unused Render Blueprint.

### LiveKit Cloud: the voice agent

LiveKit Cloud builds `Dockerfile` itself, and CI builds the same image on every push. The image holds no secrets: they're set with the LiveKit CLI and injected when the agent starts. LiveKit Cloud provides `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` on its own.

1. **Deploy**, from the repo root:
   - Run `lk cloud auth`, then `lk agent create --region us-east --secrets-file=.env --ignore-empty-secrets`. Without that last flag, the CLI stops at any key left blank in `.env`.
   - The first deploy writes `livekit.toml`. After that, `lk agent deploy` ships a new version.
   - `lk agent status` and `lk agent logs` show how it's doing.
2. **Secrets the agent uses:**
   - Required: `DATABASE_URL` (Supabase's **session pooler**, port 5432), `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` and `GROQ_API_KEY`.
   - Optional: the voice IDs `CARTESIA_VOICE_EN`/`_ES` and `DEEPGRAM_TTS_VOICE_EN`/`_ES`.
   - After editing `.env`, `lk agent update-secrets --secrets-file=.env --ignore-empty-secrets` uploads the changes and restarts the agent. The agent ignores any other keys in `.env`.
3. **Phone number:** Telephony → Phone Numbers → **Rent a number** (one US number is free). Then Telephony → Dispatch rules → **Create new dispatch rule** → JSON editor:
   ```json
   {
     "name": "Patient intake",
     "rule": { "dispatchRuleIndividual": { "roomPrefix": "call-" } },
     "roomConfig": { "agents": [{ "agentName": "patient-intake" }] }
   }
   ```
   Assign the rule to the number: Phone Numbers → ⋮ → Assign dispatch rule.
4. **Recordings:** turn on Settings → Data and privacy → **Agent observability**.
   - Each call's audio (both voices, to play or download) and transcript then appear under Sessions → the call → **Agent insights** for 30 days. They're uploaded when the call ends.
   - To listen while a call is live, open its session and select **Observe in Console**.

On the free plan the agent scales to zero when idle, so the first call after a quiet spell waits 10–20 seconds while it starts. Before a demo, warm it up with a short session in the Agent Console (Agents → the agent → **Launch Console**), which uses no phone minutes.

## Environment variables

Every variable is read through `intake.config.Settings`. A blank value means "use the default".

| Variable | Used by | Purpose | Where to get it |
|---|---|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Agent | Connect to LiveKit, and pay for the LLM through LiveKit Inference. Only needed locally: LiveKit Cloud injects them into the deployed agent. | LiveKit Cloud → your project → Settings → API keys |
| `AGENT_NAME` | Agent | The name the agent registers under; must match the dispatch rule. Default `patient-intake`. | |
| `PUBLIC_PHONE_NUMBER` | API | The number in the dashboard banner, in E.164 format (`+14843175014`). | The number you rent in LiveKit |
| `DEEPGRAM_API_KEY` | Agent | Speech-to-text, and the fallback voice | [console.deepgram.com](https://console.deepgram.com) |
| `DEEPGRAM_STT_MODEL` | Agent | Default `nova-3`, used in multilingual mode | |
| `DEEPGRAM_TTS_VOICE_EN`, `DEEPGRAM_TTS_VOICE_ES` | Agent | Fallback voices: Aura-2 voice IDs such as `aura-2-asteria-en`. A blank English voice uses Deepgram's default. A blank Spanish voice means the fallback stays English. | [Deepgram voices](https://developers.deepgram.com/docs/tts-models) |
| `CARTESIA_API_KEY` | Agent | The primary voice | [play.cartesia.ai/keys](https://play.cartesia.ai/keys) |
| `CARTESIA_TTS_MODEL` | Agent | Default `sonic-3` | |
| `CARTESIA_VOICE_EN`, `CARTESIA_VOICE_ES` | Agent | Voice IDs. A blank English voice uses Cartesia's default. A blank Spanish voice means the English voice speaks Spanish. | [play.cartesia.ai/voices](https://play.cartesia.ai/voices) |
| `LLM_PRIMARY_MODEL` | Agent | LiveKit Inference model, default `openai/gpt-4.1-mini` | |
| `GROQ_API_KEY` | Agent | The fallback LLM | [console.groq.com/keys](https://console.groq.com/keys) |
| `LLM_FALLBACK_MODEL` | Agent | Default `llama-3.3-70b-versatile` | |
| `DATABASE_URL` | API, agent, migrate, seed | Postgres | Supabase → Connect: the **session pooler** (port 5432) for local runs and the agent, the **transaction pooler** (port 6543) for Vercel. Or use the local Docker database. |
| `TEST_DATABASE_URL` | Tests | The test database. Tests never use `DATABASE_URL`. | Default: the local Docker `intake_test` |
| `CLINIC_NAME`, `AGENT_PERSONA_NAME` | Agent, API | Names in the greeting, the prompt and the dashboard | |
| `CLINIC_TIMEZONE` | Agent, API | Default `America/New_York`. Sets what "today" means, for the future-birth-date check and for scheduling. | |
| `MAX_CALL_MINUTES` | Agent | After this, Maya wraps up politely (default 12), to protect the free minutes | |
| `API_CORS_ORIGINS` | API | Allowed origins for the Vite dev server; production is same-origin | |
| `LOG_LEVEL` | Agent, API | Default `INFO` | |
| `SIMULATE_DB_FAILURE` | Agent, API | `true` makes patient writes fail, to demo the failure path | |

## Testing

| Layer | Command | What it covers | Latest result |
|---|---|---|---|
| Unit | `uv run pytest tests/unit` | Every validation rule and error code, normalization, spoken forms and read-back groups (English and Spanish), the prompt loader, the layering rules and the settings | 218 passed |
| Database | `uv run pytest tests/db` | Python/Postgres parity (each invalid example is also rejected by a check constraint), overlapping-booking constraints, idempotency, `available_slots()` across a daylight-saving change, triggers and the migration runner | 108 passed |
| API | `uv run pytest tests/api` | Every endpoint with every status code it can return, the envelope, rate limits and a database outage | 90 passed |
| Agent tools | `uv run pytest tests/agent` | The 9 tools against real Postgres with no LLM. Also the confirmation gate, the database-failure path, dropped calls, the booking race and the session wiring | 53 passed |
| Dashboard | `cd dashboard && npm test` | Rendering API responses, tabs, formatting and refresh states | 33 passed |
| Conversation evals | `uv run pytest -m evals` (opt-in: spends LLM credit and prints the cost) | 7 scripted conversations, each checking the tool calls made and an LLM-judged reply (E1–E7 in [`testing.md`](docs/specs/testing.md)) | 6 of 7 passed in the last full run. E3's only failure was that Maya read back every detail after a correction. That was accepted as safer, since the caller re-confirms the whole record, and E3 now allows it. |
| Live API | `bash scripts/smoke.sh <base URL>` (needs `jq`) | 17 checks of status codes and the envelope against a running API | 17/17 on the Vercel deployment |
| Phone calls | [`docs/manual-test-log.md`](docs/manual-test-log.md) | 4 scripted calls to the real number | See the log |

`uv run pytest` runs everything except the evals, against the local `intake_test` database. It never touches Supabase. CI (GitHub Actions) runs these checks on every push:
- ruff, the test suite against a Postgres 16 service, and the dashboard's typecheck, tests and build;
- a gitleaks secret scan;
- a smoke test of the API image behind a transaction-mode PgBouncer, like Supabase's pooler;
- a build of the agent image.

## Edge cases & resilience

- **Invalid input:** `prepare_record` checks every detail with the same rules as the API and returns an error code per field. Maya asks again only for the fields that failed, for example a birth date in the future or a 7-digit phone number. The database's check constraints are a second line of defense.
- **Dropped calls:** nothing is written to `patients` until the caller confirms the read-back. The shutdown handler runs however the call ends, and a call that drops mid-registration is marked `abandoned`, with its transcript and draft kept.
- **Database failure:** `commit_record` retries once in code, then reports the failure as retryable. Maya apologizes and offers one more try. If that fails too, the call is marked `failed` with the details kept, and Maya says the clinic will call back. The caller never hears silence. Try it locally with `SIMULATE_DB_FAILURE=true`.
- **Start over:** `start_over` clears the draft but keeps the call and its language, and Maya asks for the name again.
- **Silence:** after about 12 seconds Maya asks "Are you still there?". After a second silence she says goodbye and ends the call.
- **Provider failure:** the LLM and the voice each have a fallback (LiveKit Inference → Groq, Cartesia → Deepgram) that takes over mid-call. Each switch is logged.
- **Long calls:** at 12 minutes Maya wraps up, to protect the free minutes.
- **Returning callers:** a known phone number gets the assessment's exact sentence, then the update path, which writes only the changed fields. Because `source_call_id` is unique, one call can never save a patient twice.
- **Booking race:** if two callers pick the same slot, exclusion constraints let exactly one win, and the other is offered alternatives.
- **Emergencies and off-topic questions:** Maya says "Please hang up and call 911 right now" and ends the call. She points medical and billing questions to the clinic, then carries on.
- **Noisy lines:** Krisp voice isolation cleans the caller's audio. Speech-to-text gets hints for "Male", "Female" and "Decline to Answer", which a test call misheard.

## Known limitations & trade-offs

- **Names can't contain spaces**, per the spec's alphabetic + hyphen/apostrophe rule. Maya asks how the caller would like a name like "Van Buren" recorded.
- **Accented letters are allowed.**
- **Phone numbers aren't unique** (families share them).
- **US territories are accepted** as states.
- **US phone numbers only.** A caller with a non-US caller ID is asked for a US number.
- **English and Spanish only.**
- **No authentication** on the API/dashboard (demo scope).
- **Free-tier limits:** 50 inbound phone minutes/month, LLM and voice credits, and Vercel's Hobby plan (personal, non-commercial use).
- **Latency:** each reply goes through speech-to-text, the LLM and text-to-speech in turn. Replies that save or look something up take longer, because the LLM runs again after the tool; background typing sounds fill that gap.
- **Agent cold starts:** on the free plan the first call after a quiet spell waits 10–20 seconds for the agent to start.
- **Serverless cold starts:** the first API request after a quiet spell takes a second or two while a function instance starts and opens a database connection.
- **Polling instead of WebSockets:** Vercel Functions can't hold WebSockets or a Postgres `LISTEN` connection, so the dashboard polls every 5 seconds while its tab is visible. New data shows up within about 5 seconds rather than instantly.
- **Transaction pooler:** the API reaches Postgres through Supabase's transaction pooler, so it can't use session features (`LISTEN`, session settings, long-lived prepared statements), and each request opens a short connection. The agent uses the session pooler.
- **Rate limits are per function instance** on Vercel (the counters live in memory), so they're best-effort when several instances run at once.
- **Duplicate detection reveals the name** on file for a phone number, as the spec requires. Production would verify date of birth first.
- **Calls are recorded without an announcement.** LiveKit's Agent observability keeps each call's audio and transcript for 30 days, but the greeting doesn't say so.
- **Summaries are best-effort:** a short LLM call when the call ends. If it fails, the call is still saved without one.
- **Not HIPAA-compliant:** fictional data only.

## Next steps

- **Protect writes and personal data:** an API key or sign-in for writes and the dashboard, and a date-of-birth check before revealing whose record a number belongs to.
- **Consent and compliance:** a recording notice in the greeting, PII redaction in LiveKit's observability (built in, off by default), and HIPAA hardening: signed BAAs with each vendor, audit logs and encryption reviews.
- **Faster replies:** a paid LiveKit plan keeps the agent warm (no cold start), and per-turn timings from Agent insights would show which stage to tune.
- **Hand-offs:** a separate scheduling agent after registration instead of one agent with every tool, plus a transfer to the front desk.
- **Outbound calls and reminders:** confirmation texts and reminder calls. LiveKit numbers are inbound-only today.
- **Push updates** over server-sent events or WebSockets on a long-running host, instead of polling.
- **Load testing:** many simultaneous calls, and the pooler's connection limits.
- **Evals on a schedule:** run the conversation evals in CI nightly, with a spending cap.
