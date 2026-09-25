# syntax=docker/dockerfile:1
# The voice agent, as LiveKit Cloud builds and runs it (`lk agent create`, then
# `lk agent deploy`). Secrets are set with the LiveKit CLI and injected at runtime,
# never baked in; LiveKit Cloud provides LIVEKIT_URL, LIVEKIT_API_KEY and
# LIVEKIT_API_SECRET itself. Requirements: docs.livekit.io/deploy/agents/builds
#   docker build --tag intake-agent .

# --- 1. Install the agent and its dependencies into /app/.venv with uv -----------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra agent --no-install-project
COPY README.md ./
COPY src/ src/
RUN uv sync --locked --no-dev --extra agent && python -m compileall -q src
# Fail the build, not the first call, if a plugin can't load on Linux.
RUN .venv/bin/python -c "import intake.agent.session"

# --- 2. Runtime: Python, the virtualenv and the code, without uv -----------------
FROM python:3.12-slim
RUN useradd --uid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build --chown=app:app /app /app
WORKDIR /app
USER app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
# `start` registers with LiveKit Cloud as AGENT_NAME and waits for calls.
CMD ["python", "-m", "intake.agent", "start"]
