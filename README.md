# Riverside Family Clinic: Voice Patient Registration

<!-- TEMPLATE: Claude Code completes every TODO in Phase 6. Keep all sections;
     the assessment requires setup, architecture, stack justification, env vars,
     and known limitations / trade-offs. Delete this comment when done. -->

A voice AI agent you can phone to register as a new patient. It collects US patient demographics in natural conversation, confirms everything back, and saves the record to Postgres. A REST API and a live dashboard expose the data.

## Try it

| | |
|---|---|
| 📞 **Call** | **TODO: +1 (XXX) XXX-XXXX** |
| 🌐 **API base URL** | **TODO: https://….vercel.app** (interactive docs at `/docs`) |
| 📊 **Dashboard** | **TODO: https://….vercel.app/dashboard/** |

**Things to try on a call:**
- Register normally.
- Spell a correction ("Actually, it's D-A-V-I-S").
- Give a future birth date.
- Say "Can we start over?"
- Say "Hablo español".
- Call back from the same number to see duplicate detection.
- Book an appointment after registering.

**Testing notes for reviewers:** TODO. Include the cold-start notes (the first API request after a quiet spell takes a second or two), the free-tier limits, and that no credentials are needed.

## Architecture

TODO: diagram and a one-paragraph walkthrough. The key points to cover:
- **Telephony:** LiveKit Cloud (free US number, SIP, dispatch).
- **Voice agent:** a Python LiveKit Agents worker with Deepgram STT, an LLM (LiveKit Inference with a Groq fallback), and Cartesia TTS (Deepgram fallback).
- **Core service layer:** framework-free validation and business rules, shared by the agent and the API. This is what "directly invoke the same service layer" refers to.
- **Postgres:** Supabase; constraints enforce the data model.
- **REST API + dashboard:** FastAPI as one Vercel Function (Python runtime, region `iad1`) that reaches Postgres through Supabase's transaction pooler. The React dashboard is served from Vercel's CDN and polls the API every 5 seconds.

### Separation of concerns
TODO: map each folder to the telephony / LLM logic / data layer / API boundaries.

### Prompt engineering
TODO: link to `src/intake/agent/prompts/system_prompt.md` (commented) and summarize the design:
- Voice-first style rules.
- The read-back generated in code, not by the LLM.
- The prepare → confirm → commit gate enforced in code.
- Tools that return facts, not prose.

## Tech stack & why

| Layer | Choice | Alternatives considered | Why |
|---|---|---|---|
| API | FastAPI + Pydantic v2 | Flask, Django REST Framework | Async, typed models and generated interactive docs; the core layer's Pydantic models are reused as they are. |
| Database | Supabase Postgres (free) | Neon, a managed RDS | Real Postgres: the data model is enforced with check and exclusion constraints and triggers, and it's reachable over IPv4 through Supabase's pooler. |
| API + dashboard hosting | Vercel Hobby (free, no card) | Render free web service (needs a credit card), Fly.io | Vercel runs the FastAPI app as one Python function with no server to manage and serves the dashboard from its CDN. The function runs in `iad1` (Washington, D.C.), next to Supabase `us-east-1`. |
| Database connections | API: Supabase's transaction pooler (port 6543). Agent: the session pooler (port 5432). | Direct connections | Serverless instances come and go, so the pooler keeps Postgres connections bounded; the API holds no pool of its own. The long-running agent keeps a small pool on the session pooler. |

TODO (Phase 6): the voice rows. LiveKit vs Vapi/Twilio (free real number, open-source agent framework); a speech-to-text/LLM/TTS pipeline vs speech-to-speech; LiveKit Inference + Groq fallback; Cartesia + Deepgram fallback.

## Data model & API

TODO: short summary plus a link to `docs/specs/data-model.md` and `docs/specs/api.md`. Include example curl commands for all five endpoints.

## Local setup

TODO: verify these steps from a clean clone.
1. Prerequisites: Python 3.12 + uv, Node 22.12+, Docker, LiveKit CLI.
2. `cp .env.example .env` and fill it in (see below).
3. `docker compose up -d db && uv sync --all-extras` (the extras are the local server and the agent; the API itself needs only the base set)
4. `uv run python -m intake.db.migrate && uv run python -m intake.db.seed`
5. `uv run uvicorn intake.api.main:app --reload`
6. `uv run python -m intake.agent console` to talk to the agent in your terminal.

## Deployment

| Part | Where | Configured by |
|---|---|---|
| REST API + dashboard | Vercel Hobby, function region `iad1` | `vercel.json` + `app.py` |
| Voice agent | LiveKit Cloud | Phase 4 |
| Database | Supabase (free) | `python -m intake.db.migrate` and `seed` |

### Vercel: what `vercel.json` does

- Runs the FastAPI app (`app.py` re-exports `intake.api.main:app`) as one Python function in `iad1`.
- Installs only the API's dependencies. Vercel runs `uv sync --no-dev` from `uv.lock`, which skips the `server` (uvicorn) and `agent` extras. The function bundle is about 50 MB, or about 70 MB with the bytecode Vercel precompiles, out of a 500 MB limit. `excludeFiles` also leaves out the agent code, tests, docs, the dashboard sources and the migrations.
- Builds the dashboard into `src/intake/api/static/`, which the app mounts at `/dashboard`. Vercel copies that mount to its CDN (`[tool.vercel.fastapi.static] cdn = true` in `pyproject.toml`), and `vercel.json` gives those files the same security headers the API sends.
- Redirects `/` to `/dashboard/`, and calls `/health` once a day (a Vercel Cron Job). `/health` runs `SELECT 1`, so the free Supabase project never pauses for inactivity.

### Vercel: environment variables

Set these in the Vercel project (Settings → Environment Variables). Never commit them.

| Name | Required | Value |
|---|---|---|
| `DATABASE_URL` | Yes | Supabase's **transaction pooler** URI (port **6543**): Supabase → Connect → Transaction pooler, with the database password filled in. It's the local session-pooler URL with `:5432` changed to `:6543`. |
| `PUBLIC_PHONE_NUMBER` | Once the number exists (Phase 4) | The number to call, e.g. `+15125550100`; the dashboard banner hides without it. |
| `CLINIC_NAME`, `AGENT_PERSONA_NAME`, `CLINIC_TIMEZONE`, `LOG_LEVEL` | No | The defaults match the demo. |

After deploying, check the live API: `bash scripts/smoke.sh https://<project>.vercel.app`.

`Dockerfile.api` builds the same API and dashboard into one image for local or Docker hosting. `docs/alternatives/render.yaml` is an unused Render Blueprint.

## Environment variables

TODO: table of every variable in `.env.example` with its purpose and where to get it.

## Testing

TODO: how to run each layer, what it covers, and the latest results. Mention the opt-in LLM-judged evals and the manual phone test log.

## Edge cases & resilience

TODO: summarize how each is handled:
- Invalid input.
- Dropped calls (nothing saved without confirmation; call marked `abandoned`).
- Database failure (apology, one retry, callback promise; never silence).
- Start over.
- Silence.
- LLM/TTS provider fallback.

## Known limitations & trade-offs

TODO: include at least these:
- **Names can't contain spaces**, per the spec's alphabetic + hyphen/apostrophe rule.
- **Accented letters are allowed.**
- **Phone numbers aren't unique** (families share them).
- **US territories are accepted** as states.
- **No authentication** on the API/dashboard (demo scope).
- **Free-tier limits:** 50 inbound phone minutes/month, LLM and voice credits, and Vercel's Hobby plan (personal, non-commercial use).
- **Serverless cold starts:** the first API request after a quiet spell takes a second or two while a function instance starts and opens a database connection.
- **Polling instead of WebSockets:** Vercel Functions can't hold WebSockets or a Postgres `LISTEN` connection, so the dashboard polls every 5 seconds while its tab is visible. New data shows up within about 5 seconds rather than instantly.
- **Transaction pooler:** the API reaches Postgres through Supabase's transaction pooler, so it can't use session features (`LISTEN`, session settings, long-lived prepared statements), and each request opens a short connection. The agent uses the session pooler.
- **Rate limits are per function instance** on Vercel (the counters live in memory), so they're best-effort when several instances run at once.
- **Duplicate detection reveals the name** on file for a phone number, as the spec requires. Production would verify date of birth first.
- **Summaries are best-effort.**
- **Not HIPAA-compliant:** fictional data only.

## Next steps

TODO: e.g. an API key for writes, a multi-agent workflow for scheduling, audio recording, outbound reminder calls, HIPAA hardening, and load testing.
