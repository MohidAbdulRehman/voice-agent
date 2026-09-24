# Riverside Family Clinic: Voice Patient Registration

<!-- TEMPLATE: Claude Code completes every TODO in Phase 6. Keep all sections;
     the assessment requires setup, architecture, stack justification, env vars,
     and known limitations / trade-offs. Delete this comment when done. -->

A voice AI agent you can phone to register as a new patient. It collects US patient demographics in natural conversation, confirms everything back, and saves the record to Postgres. A REST API and a live dashboard expose the data.

## Try it

| | |
|---|---|
| 📞 **Call** | **TODO: +1 (XXX) XXX-XXXX** |
| 🌐 **API base URL** | **TODO: https://….onrender.com** (interactive docs at `/docs`) |
| 📊 **Dashboard** | **TODO: https://….onrender.com/dashboard** |

**Things to try on a call:**
- Register normally.
- Spell a correction ("Actually, it's D-A-V-I-S").
- Give a future birth date.
- Say "Can we start over?"
- Say "Hablo español".
- Call back from the same number to see duplicate detection.
- Book an appointment after registering.

**Testing notes for reviewers:** TODO. Include the first-call cold-start note, the free-tier limits, and that no credentials are needed.

## Architecture

TODO: diagram and a one-paragraph walkthrough. The key points to cover:
- **Telephony:** LiveKit Cloud (free US number, SIP, dispatch).
- **Voice agent:** a Python LiveKit Agents worker with Deepgram STT, an LLM (LiveKit Inference with a Groq fallback), and Cartesia TTS (Deepgram fallback).
- **Core service layer:** framework-free validation and business rules, shared by the agent and the API. This is what "directly invoke the same service layer" refers to.
- **Postgres:** Supabase; constraints enforce the data model.
- **REST API + dashboard:** FastAPI on Render, with live updates via Postgres LISTEN/NOTIFY → WebSocket.

### Separation of concerns
TODO: map each folder to the telephony / LLM logic / data layer / API boundaries.

### Prompt engineering
TODO: link to `src/intake/agent/prompts/system_prompt.md` (commented) and summarize the design:
- Voice-first style rules.
- The read-back generated in code, not by the LLM.
- The prepare → confirm → commit gate enforced in code.
- Tools that return facts, not prose.

## Tech stack & why

TODO: a table of choice, alternatives considered, and reason. Cover: LiveKit vs Vapi/Twilio (free real number, open-source agent framework); a speech-to-text/LLM/TTS pipeline vs speech-to-speech; LiveKit Inference + Groq fallback; Cartesia + Deepgram fallback; FastAPI + Pydantic; Postgres constraints; Supabase + Render free tiers.

## Data model & API

TODO: short summary plus a link to `docs/specs/data-model.md` and `docs/specs/api.md`. Include example curl commands for all five endpoints.

## Local setup

TODO: verify these steps from a clean clone.
1. Prerequisites: Python 3.12 + uv, Node 20, Docker, LiveKit CLI.
2. `cp .env.example .env` and fill it in (see below).
3. `docker compose up -d db && uv sync`
4. `uv run python -m intake.db.migrate && uv run python -m intake.db.seed`
5. `uv run uvicorn intake.api.main:app --reload`
6. `uv run python -m intake.agent console` to talk to the agent in your terminal.

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
- **Free-tier limits:** 50 inbound phone minutes/month, LLM and voice credits, and cold starts on the agent and API.
- **Duplicate detection reveals the name** on file for a phone number, as the spec requires. Production would verify date of birth first.
- **Summaries are best-effort.**
- **Not HIPAA-compliant:** fictional data only.

## Next steps

TODO: e.g. an API key for writes, a multi-agent workflow for scheduling, audio recording, outbound reminder calls, HIPAA hardening, and load testing.
