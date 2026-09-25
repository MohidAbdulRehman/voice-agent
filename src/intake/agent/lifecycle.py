"""The calls row behind a conversation (docs/specs/agent.md §5).

A call is opened when the session starts and closed by the job's shutdown
handler, which runs however the call ends: a goodbye, a hang-up or a dropped
connection. Only a confirmed commit ever writes a patient, so a dropped call
never creates or changes one.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from livekit.agents import llm

from intake.agent.state import CallState
from intake.core.models import CallStatus, Channel, TranscriptEntry
from intake.core.services import Services

log = structlog.stdlib.get_logger("intake.agent")

SUMMARY_TIMEOUT_SECONDS = 6.0  # the job gets 10 seconds to shut down
MIN_TURNS_FOR_SUMMARY = 2  # caller turns
_PHONE_LIKE_DIGITS = re.compile(r"\d{10,}")  # a phone number, not the digits of a random id

Summarizer = Callable[[list[TranscriptEntry]], Awaitable[str]]


def last_four(number: str | None) -> str | None:
    """A phone number as logs show it: the last four digits only."""
    return None if number is None else number[-4:]


def mask_digits(text: str) -> str:
    """Hide all but the last four digits of a phone number, such as one in a room name."""
    return _PHONE_LIKE_DIGITS.sub(lambda run: "*" * (len(run[0]) - 4) + run[0][-4:], text)


async def open_call(
    services: Services, *, room_name: str, channel: Channel, caller_number: str | None
) -> CallState:
    """Insert the ``in_progress`` calls row and tag every later log line with its id."""
    call_id = await services.calls.start(
        room_name=room_name, channel=channel, caller_number=caller_number
    )
    structlog.contextvars.bind_contextvars(call_id=str(call_id))
    log.info(
        "call.started",
        channel=channel,
        caller_number=last_four(caller_number),
        room=mask_digits(room_name),
    )
    return CallState(call_id=call_id, channel=channel, caller_number=caller_number)


def transcript_from(history: llm.ChatContext) -> list[TranscriptEntry]:
    """The spoken turns of the conversation, in order."""
    entries = []
    for item in history.items:
        if item.type != "message" or item.role not in ("user", "assistant"):
            continue
        if text := item.text_content:
            at = datetime.fromtimestamp(item.created_at, UTC)
            entries.append(TranscriptEntry(role=item.role, text=text, at=at))
    return entries


async def close_call(
    services: Services,
    state: CallState,
    history: llm.ChatContext,
    *,
    started_at: float,
    fallback_reason: str,
    summarize: Summarizer | None,
) -> CallStatus:
    """Save the transcript, end reason and settled status; then, best effort, a summary.

    The status settles in the database: ``registered``/``updated``/``failed`` stay,
    otherwise it's ``abandoned`` if data was prepared and ``no_action`` if not.
    ``started_at`` is a ``time.monotonic()`` reading from the start of the call.
    """
    transcript = transcript_from(history)
    end_reason = state.end_reason or fallback_reason
    status = await services.calls.finish(
        state.call_id, end_reason=end_reason, transcript=transcript
    )
    turns = sum(entry.role == "user" for entry in transcript)
    if summarize is not None and turns >= MIN_TURNS_FOR_SUMMARY:
        await _save_summary(services, state, transcript, summarize)
    log.info(
        "call.ended",
        status=status,
        end_reason=end_reason,
        duration_s=round(time.monotonic() - started_at, 1),
        turns=turns,
        language=state.language,
    )
    return status


async def _save_summary(
    services: Services,
    state: CallState,
    transcript: list[TranscriptEntry],
    summarize: Summarizer,
) -> None:
    """Best effort: a slow or failing LLM never holds up the shutdown."""
    try:
        async with asyncio.timeout(SUMMARY_TIMEOUT_SECONDS):
            summary = (await summarize(transcript)).strip()
        if summary:
            await services.calls.save_summary(state.call_id, summary)
    except Exception:
        log.warning("call.summary_failed", exc_info=True)
