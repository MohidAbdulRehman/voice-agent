# CLAUDE.md: Patient Intake Voice Agent

Operating manual for Claude Code in this repository. Read it at the start of every session.

## What we're building

A phone-based voice agent that registers new patients for a fictional US clinic, **Riverside Family Clinic**:
1. A caller dials a real US number and talks naturally with **Maya**, the clinic's virtual intake assistant.
2. Maya collects the demographic fields, reads everything back, and saves the record to Postgres only after the caller confirms.
3. After saving, Maya can book a first appointment, switch to Spanish, and recognize returning callers.
4. A REST API and a small live dashboard expose the data.

This is a take-home assessment. Reviewers will phone the number, call the API, and read the code and README.

**Guiding principle:** a simple system that works flawlessly beats an ambitious one that breaks. Finish and verify each piece before starting the next.

## Source-of-truth documents

Read the relevant document before coding that area. If code and a spec disagree, stop and ask.

| Document | Covers |
|---|---|
| `docs/private/REQUIREMENTS.md` | Requirement IDs → implementation → evidence. **Update the Status/Evidence columns as you go.** (Gitignored.) |
| `docs/specs/data-model.md` | Field rules, normalization, error codes, spoken forms |
| `db/migrations/0001_init.sql` | Schema. Already written and tested on Postgres 16; **do not weaken any constraint.** |
| `db/seed.sql` | 2 fake patients, 3 mock doctors with schedules |
| `docs/specs/api.md` | REST contract, envelope, status codes, dashboard |
| `docs/specs/agent.md` | Voice agent wiring, state, the 9 tool contracts, call lifecycle, edge cases |
| `src/intake/agent/prompts/system_prompt.md` | The commented system prompt (already written) |
| `docs/specs/testing.md` | Test plan, evals E1–E13, manual phone script |

## Hard rules

1. **Verify third-party APIs before writing integration code.** The LiveKit Agents API changes often. Use the `livekit-docs` MCP server and the `livekit-examples/agent-starter-python` template for every LiveKit class, parameter and CLI command. Use official docs for Deepgram, Cartesia and Groq plugin options. Never write LiveKit code from memory. If the docs contradict `agent.md`, follow the docs for *how* and the spec for *behavior*, and tell the human.
2. **Secrets:**
   - Never print, log, echo or commit values from `.env`. Never paste real keys into code, tests, docs or commit messages.
   - Read configuration only through `intake.config.Settings` (pydantic-settings).
   - Before the first commit, confirm `.env` and `docs/private/` are git-ignored. The repo is **public**.
3. **Layering** (enforce with an import-linter contract or a simple test):
   - `intake.core` imports nothing from FastAPI or LiveKit.
   - `intake.api` and `intake.agent` depend on `core`; nothing depends on `api` or `agent`.
   - All reads and writes go through `core` services.
   - Parameterized SQL only; never build SQL with string formatting.
4. **Tests never touch Supabase.** They use `TEST_DATABASE_URL` (the local Docker Postgres). Only `migrate`/`seed` run against `DATABASE_URL`, and only when the human asks.
5. **Don't fix a failing test by loosening a DB constraint or a validation rule.** Fix the code, or ask.
6. **Dependencies:** use only the approved list below. Ask before adding anything else.
7. **Fictional data only:** 555-01XX phone numbers and `example.com` emails.
8. **Phase gates:** at the end of each phase, run the checks, update `REQUIREMENTS.md`, summarize what changed and what's next, then **stop and wait** for the human to say continue.
9. **Free-tier guardrails:**
   - Never place real phone calls or run `pytest -m evals` without asking. Both consume limited free credits: 50 inbound phone minutes/month, and LiveKit Inference's $2.50/month.
   - Prefer console mode and text-only tests.
10. **Voice-agent rules:**
   - Keep the tool list fixed for the whole call.
   - Tools return structured facts with a `status` key, never sentences, and never raise to the LLM.
   - The read-back text comes from `core/speech.py`, not from the LLM.

## Approved stack

- **Python 3.12**, managed with **uv**. Single `pyproject.toml`, `src/intake/` layout.
- **API:**
  - FastAPI, uvicorn, pydantic v2, pydantic-settings, email-validator.
  - SQLAlchemy 2.x (async) with asyncpg. The app converts `postgresql://` to `postgresql+asyncpg://` in code.
  - structlog for JSON logs, slowapi for rate limiting.
- **Agent:**
  - `livekit-agents`, with plugins for deepgram, cartesia, groq, silero, turn-detector and noise-cancellation (exact package names per LiveKit docs).
  - The LLM primary is **LiveKit Inference** (no extra key); the fallback is Groq.
- **Tests:** pytest, pytest-asyncio, httpx, freezegun (or time-machine). **Lint:** ruff (lint + format). **Secret scan:** gitleaks in CI.
- **Dashboard:** React + Vite + TypeScript + Tailwind, and Vitest. Playwright is optional.
- **Infrastructure:**
  - Docker Compose (local `postgres:16`), GitHub Actions CI.
  - Render (API + dashboard, free web service via `render.yaml` + `Dockerfile.api`).
  - LiveKit Cloud (agent deployment, per LiveKit docs).

## Repository layout (target)

```
.
├── CLAUDE.md  README.md  .env.example  .gitignore  pyproject.toml  uv.lock
├── docker-compose.yml          # local Postgres 16 for dev + tests (host port 5433)
├── .github/workflows/ci.yml    # ruff, pytest (Postgres service), gitleaks
├── Dockerfile                  # agent image (LiveKit Cloud deploy; confirm expected location in LiveKit docs)
├── Dockerfile.api              # API + built dashboard (Render)
├── render.yaml
├── db/migrations/0001_init.sql   db/seed.sql   db/docker-init/ (creates intake_test)
├── src/intake/
│   ├── config.py               # Settings (pydantic-settings); single source of env config
│   ├── logging.py              # structlog JSON setup
│   ├── core/                   # framework-free domain layer
│   │   ├── models.py           # Pydantic models: PatientCreate, PatientUpdate, Patient, errors
│   │   ├── validation.py       # normalizers + validators (data-model.md)
│   │   ├── speech.py           # spoken forms + read-back groups (EN/ES)
│   │   ├── states.py           # USPS codes + full-name mapping
│   │   ├── repository.py       # async SQL access (parameterized); SIMULATE_DB_FAILURE hook
│   │   └── services.py         # PatientService, CallService, SchedulingService
│   ├── db/                     # engine/session, migrate.py, seed.py, check.py
│   ├── api/                    # main.py, routes/, errors.py (envelope), ws.py (LISTEN → WebSocket)
│   └── agent/
│       ├── __main__.py         # entrypoint; LiveKit CLI (console/dev/start)
│       ├── session.py          # STT/LLM/TTS/VAD/turn-detection/background-audio wiring
│       ├── state.py            # CallState dataclass
│       ├── tools.py            # the 9 function tools (agent.md §4)
│       ├── lifecycle.py        # calls row, transcript, summary, shutdown handling
│       ├── scripts.py          # fixed greeting/silence lines (EN/ES)
│       └── prompts/system_prompt.md  +  loader.py
├── dashboard/                  # React app; built into src/intake/api/static/ for serving
├── tests/{unit,db,api,agent,evals}/
├── scripts/smoke.sh            # live API smoke check
└── docs/specs/*.md   docs/private/ (gitignored)   docs/manual-test-log.md
```

## Commands

Adjust these as you build and keep this list accurate.

```bash
uv sync                                    # install
docker compose up -d db                    # local Postgres 16 on 127.0.0.1:5433 (dbs: intake, intake_test)
uv run python -m intake.db.check           # prints "ok" if DATABASE_URL connects (never prints the URL)
uv run python -m intake.db.check --test    # same check for TEST_DATABASE_URL (local Docker)
uv run python -m intake.db.migrate         # applies db/migrations/*.sql in order, tracked in schema_migrations (DATABASE_URL: ask first)
uv run python -m intake.db.seed            # idempotent demo data (DATABASE_URL: ask first)
# Local dev DB instead of Supabase: set DATABASE_URL=postgresql://postgres:postgres@localhost:5433/intake for the command
# (bash: prefix the command; PowerShell: $env:DATABASE_URL = "..."). --test targets TEST_DATABASE_URL.
uv run ruff check . && uv run ruff format --check .
uv run pytest                              # unit + db + api + agent tool tests (local DB)
uv run pytest -m evals                     # LLM-judged conversation evals: ASK FIRST (uses credits)
uv run uvicorn intake.api.main:app --reload
uv run python -m intake.agent console      # talk to the agent in the terminal (no phone minutes)
uv run python -m intake.agent dev          # register with LiveKit Cloud (phone/playground)
cd dashboard && npm install && npm run dev
```

## Phases (stop after each for human review)

**Phase 0: Scaffold & verify**
- Tasks: `pyproject.toml`, the package layout, `Settings`, logging, `docker-compose.yml`, the `.gitignore` check, CI with lint + pytest + gitleaks, and `db/check.py`.
- Done when: `uv run pytest` passes (placeholder test), `db.check` prints ok against both the local and the Supabase database, and CI is green.

**Phase 1: Data layer**
- Tasks: the migration runner, applying the migration and seed locally, core models, validation, speech, states, repository and services.
- Tests: unit tests + DB tests from `testing.md` §1–2.
- Done when: all pass. Then, **with the human's go-ahead**, apply the migration and seed to Supabase.

**Phase 2: REST API + dashboard shell**
- Tasks: every endpoint in `api.md`, the envelope/error handlers, rate limiting, sanitization, `/health`, and `scripts/smoke.sh`. Build a basic React dashboard (patients table + detail panel), plus `Dockerfile.api` and `render.yaml`.
- Tests: `testing.md` §3.
- Done when: all API tests pass and the human deploys to Render and `smoke.sh` passes against the live URL.

**Phase 3: Agent, text first**
- Tasks: `CallState`, the 9 tools, the prompt loader, lifecycle/shutdown handling, and session wiring (verify every API via `livekit-docs`).
- Tests: tool tests (`testing.md` §4).
- Done when: tool tests pass and the human runs a console conversation successfully. Evals E1–E13 run only when the human says so.

**Phase 4: Voice & telephony**
- Tasks: Cartesia voices (EN/ES) with Deepgram fallback, turn detection, background audio, noise cancellation, silence handling, the call length cap, SIP caller ID, and explicit dispatch as `patient-intake`. Deploy the agent to LiveKit Cloud with secrets set through LiveKit's secret mechanism, not baked into the image.
- Done when: the human completes manual calls #1–#2.

**Phase 5: Bonuses**
- Tasks: scheduling tools, Spanish end to end, call transcripts + summaries in the dashboard, live updates (LISTEN/NOTIFY → WebSocket, with a polling fallback).
- Done when: E7, E9 and E11 pass and manual calls #3–#4 are done.

**Phase 6: Hardening & docs**
- Tasks: complete the README (all required sections; see its template), `docs/manual-test-log.md`, a `REQUIREMENTS.md` audit (every row Done with evidence), and a final `smoke.sh` run.

## Conventions

- **API envelope:** `{"data": ..., "error": null}` or `{"data": null, "error": {"code", "message", "details"}}`. It's defined in one place, `api/errors.py`.
- **Time:** store `timestamptz` in UTC; render ISO 8601 with `Z`. DOB is rendered `MM/DD/YYYY`. "Today" is computed in `CLINIC_TIMEZONE`. Use an injectable clock so tests can freeze time.
- **Logging:** structlog JSON to stdout, event names as in `agent.md` §8. Include `call_id` in agent logs. Log a caller number's last 4 digits only, except inside the `registration.committed` payload.
- **Code style:**
  - Type hints everywhere and small functions.
  - Docstrings on public functions; tool docstrings are what the LLM sees, so keep them precise.
  - No dead code or commented-out code.
- **Commits:** small, conventional messages (`feat(api): …`, `test(core): …`).
