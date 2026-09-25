"""The voice pipeline, and the entrypoint LiveKit runs for each call (docs/specs/agent.md §2).

Speech-to-text is Deepgram; the LLM is LiveKit Inference with Groq as a fallback;
the voice is Cartesia with Deepgram as a fallback. Voice activity and end-of-turn
detection are LiveKit's built-in models. Class and parameter names follow LiveKit
Agents 1.8, checked against its docs and source.
"""

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import structlog
from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    UserStateChangedEvent,
    inference,
    llm,
    room_io,
    stt,
    tts,
)
from livekit.plugins import cartesia, deepgram, groq
from pydantic import SecretStr

from intake.agent import scripts
from intake.agent.lifecycle import Summarizer, close_call, open_call
from intake.agent.prompts.loader import render_prompt
from intake.agent.state import CallState
from intake.agent.tools import AgentDeps, IntakeAgent
from intake.config import Settings, get_settings
from intake.core.models import Channel, TranscriptEntry
from intake.core.services import build_services, utc_now
from intake.core.speech import SpokenLanguage
from intake.core.validation import Invalid, clinic_today, normalize_phone
from intake.db.engine import make_engine
from intake.logging import configure_agent_logging

log = structlog.stdlib.get_logger("intake.agent")

TEMPERATURE = 0.3
KEYTERMS = ("Decline to Answer",)  # plus the clinic's name
SIP_CALLER_NUMBER = "sip.phoneNumber"  # participant attribute set by LiveKit telephony
SILENCE_SECONDS = 12.0  # caller silence before "Are you still there?", and again before goodbye
WRAP_UP_GRACE_SECONDS = 60.0  # after the time-limit wrap-up, the call ends even if the LLM hasn't
# Per-turn latencies (seconds) logged at debug level, from each message's metrics.
TURN_LATENCIES = (
    "transcription_delay",
    "end_of_turn_delay",
    "llm_node_ttft",
    "tts_node_ttfb",
    "e2e_latency",
)


def build_stt(settings: Settings) -> stt.STT:
    """Deepgram Nova-3 in multilingual mode, so callers can switch to Spanish mid-call."""
    return deepgram.STT(
        model=settings.deepgram_stt_model,
        language="multi",
        smart_format=True,
        numerals=True,
        api_key=_secret(settings.deepgram_api_key, "DEEPGRAM_API_KEY"),
    )


def build_llm(settings: Settings) -> llm.LLM:
    """LiveKit Inference, falling back to Groq; one tool call at a time."""
    primary = inference.LLM(
        model=settings.llm_primary_model,
        extra_kwargs={"temperature": TEMPERATURE, "parallel_tool_calls": False},
    )
    fallback = groq.LLM(
        model=settings.llm_fallback_model,
        temperature=TEMPERATURE,
        parallel_tool_calls=False,
        api_key=_secret(settings.groq_api_key, "GROQ_API_KEY"),
    )
    adapter = llm.FallbackAdapter([primary, fallback])
    adapter.on("llm_availability_changed", _on_llm_availability)
    return adapter


@dataclass(frozen=True)
class Voices:
    """The call's text-to-speech, and how ``set_language`` switches it."""

    tts: tts.TTS
    switch: Callable[[SpokenLanguage], None]


def build_voices(settings: Settings) -> Voices:
    """Cartesia Sonic, falling back to Deepgram Aura-2, each with an English and a Spanish voice.

    Deepgram's voice name includes its language (``aura-2-<voice>-es``); without a
    Spanish one configured, the fallback voice stays English.
    """
    primary = cartesia.TTS(
        model=settings.cartesia_tts_model,
        language="en",
        api_key=_secret(settings.cartesia_api_key, "CARTESIA_API_KEY"),
        **_voice(settings.cartesia_voice_en),
    )
    backup = deepgram.TTS(
        api_key=_secret(settings.deepgram_api_key, "DEEPGRAM_API_KEY"),
        **_model(settings.deepgram_tts_voice_en),
    )
    adapter = tts.FallbackAdapter([primary, backup])
    adapter.on("tts_availability_changed", _on_tts_availability)

    def switch(language: SpokenLanguage) -> None:
        # The fallback adapter has no update_options, so each voice is updated directly.
        spanish = language == "Spanish"
        voice = settings.cartesia_voice_es if spanish else settings.cartesia_voice_en
        primary.update_options(language="es" if spanish else "en", **_voice(voice))
        backup_voice = settings.deepgram_tts_voice_es if spanish else settings.deepgram_tts_voice_en
        if backup_voice:
            backup.update_options(model=backup_voice)

    return Voices(tts=adapter, switch=switch)


def summarizer(model: llm.LLM) -> Summarizer:
    """A one-off LLM call that summarizes a finished call for staff."""

    async def summarize(transcript: list[TranscriptEntry]) -> str:
        chat = llm.ChatContext()
        chat.add_message(role="system", content=scripts.SUMMARY)
        chat.add_message(role="user", content="\n".join(f"{e.role}: {e.text}" for e in transcript))
        parts = []
        async with model.chat(chat_ctx=chat) as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    parts.append(chunk.delta.content)
        return "".join(parts)

    return summarize


async def entrypoint(ctx: JobContext) -> None:
    """Run one call: open its calls row, start the session, greet, and close it on shutdown."""
    settings = get_settings()
    configure_agent_logging()
    started_at = time.monotonic()
    engine = make_engine(_secret(settings.database_url, "DATABASE_URL"))
    services = build_services(engine, settings)
    channel, caller_number = await _caller(ctx)
    # Console runs share one fake room; each gets its own calls row.
    room_name = f"console-{uuid4().hex[:12]}" if ctx.is_fake_job() else ctx.room.name
    state = await open_call(
        services, room_name=room_name, channel=channel, caller_number=caller_number
    )
    voices = build_voices(settings)
    model = build_llm(settings)
    console = channel == "console"  # in the terminal, silence is someone typing
    session = AgentSession[CallState](
        userdata=state,
        stt=build_stt(settings),
        llm=model,
        tts=voices.tts,
        stt_context_options=STTContextOptions(keyterms=[settings.clinic_name, *KEYTERMS]),
        turn_handling=TurnHandlingOptions(turn_detection=inference.TurnDetector()),
        user_away_timeout=None if console else SILENCE_SECONDS,
    )
    session.on("conversation_item_added", _log_turn_metrics)
    if not console:
        watch_silence(session)
    time_limit = asyncio.create_task(limit_call_length(session, settings.max_call_minutes))

    async def close(_reason: str) -> None:
        time_limit.cancel()
        try:
            await close_call(
                services,
                state,
                session.history,
                started_at=started_at,
                fallback_reason="disconnected",
                summarize=summarizer(model),
            )
        except Exception:
            log.exception("call.not_closed")
        finally:
            await engine.dispose()

    ctx.add_shutdown_callback(close)
    prompt = render_prompt(
        agent_name=settings.agent_persona_name,
        clinic_name=settings.clinic_name,
        today=clinic_today(utc_now(), settings.clinic_zone),
        timezone=settings.clinic_timezone,
        caller_number=caller_number,
    )
    deps = AgentDeps(services=services, settings=settings, switch_voice=voices.switch)
    await session.start(
        agent=IntakeAgent(instructions=prompt, deps=deps),
        room=ctx.room,
        # Closing the session (end_call, silence) deletes the room, which hangs up the phone.
        room_options=room_io.RoomOptions(delete_room_on_close=True),
    )
    greet(session, settings)


def watch_silence(
    session: AgentSession[CallState], *, wait_seconds: float = SILENCE_SECONDS
) -> None:
    """Check in once when the caller goes quiet; if the silence goes on, say goodbye and hang up.

    The session reports the caller as ``away`` after ``user_away_timeout`` seconds of
    silence; anything else they do (speaking) cancels the check-in.
    """
    check_in: asyncio.Task[None] | None = None

    async def still_there() -> None:
        state = session.userdata
        state.silence_prompts += 1
        await session.say(scripts.STILL_THERE[state.language])
        await asyncio.sleep(wait_seconds)
        state.end_reason = state.end_reason or "no_response"
        session.say(scripts.SILENCE_GOODBYE[state.language], allow_interruptions=False)
        session.shutdown(drain=True)

    def on_user_state(event: UserStateChangedEvent) -> None:
        nonlocal check_in
        if event.new_state == "away":
            if check_in is None or check_in.done():
                check_in = asyncio.create_task(still_there())
        elif check_in is not None:
            check_in.cancel()
            check_in = None

    session.on("user_state_changed", on_user_state)


async def limit_call_length(
    session: AgentSession[CallState],
    minutes: float,
    *,
    grace_seconds: float = WRAP_UP_GRACE_SECONDS,
) -> None:
    """At the time limit, have the agent wrap up; end the call if it hasn't after a grace period."""
    await asyncio.sleep(minutes * 60)
    state = session.userdata
    state.end_reason = state.end_reason or "time_limit"
    log.info("call.time_limit", minutes=minutes)
    session.generate_reply(instructions=scripts.TIME_LIMIT)
    await asyncio.sleep(grace_seconds)
    session.shutdown(drain=True)


def greet(session: AgentSession[CallState], settings: Settings) -> None:
    """The fixed greeting; its opener (clinic, virtual assistant) can't be interrupted."""
    opener, rest = scripts.greeting(
        session.userdata.language,
        clinic_name=settings.clinic_name,
        agent_name=settings.agent_persona_name,
    )
    session.say(opener, allow_interruptions=False)
    session.say(rest)


def build_server(settings: Settings) -> AgentServer:
    """The agent server; LiveKit dispatches calls to it explicitly, by ``AGENT_NAME``."""
    export_livekit_env(settings)  # before registering: the agent name is read from it
    server = AgentServer()
    server.rtc_session(entrypoint)
    return server


def export_livekit_env(settings: Settings) -> None:
    """Hand LiveKit the settings it reads from the environment, unless already set there."""
    values = {
        "LIVEKIT_URL": settings.livekit_url,
        "LIVEKIT_API_KEY": _optional_secret(settings.livekit_api_key),
        "LIVEKIT_API_SECRET": _optional_secret(settings.livekit_api_secret),
        "LIVEKIT_AGENT_NAME": settings.agent_name,
    }
    for name, value in values.items():
        if value:
            os.environ.setdefault(name, value)


async def _caller(ctx: JobContext) -> tuple[Channel, str | None]:
    """How the caller reached us, and their number if it's a phone call."""
    if ctx.is_fake_job():
        return "console", None
    participant = await ctx.wait_for_participant()
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return "web", None
    number = participant.attributes.get(SIP_CALLER_NUMBER)
    if not number:
        return "phone", None  # withheld caller ID
    try:
        return "phone", normalize_phone(number)
    except Invalid:
        return "phone", number  # not a US number: kept as the carrier sent it


def _log_turn_metrics(event: ConversationItemAddedEvent) -> None:
    """Per-turn latencies (STT, end of turn, LLM, TTS), in seconds, at debug level."""
    if not isinstance(event.item, llm.ChatMessage):
        return
    metrics = event.item.metrics
    latencies = {key: round(metrics[key], 3) for key in TURN_LATENCIES if key in metrics}
    if latencies:
        log.debug("turn.metrics", role=event.item.role, **latencies)


def _on_llm_availability(event: llm.AvailabilityChangedEvent) -> None:
    _log_fallback("llm.fallback_used", event.llm, available=event.available)


def _on_tts_availability(event: tts.AvailabilityChangedEvent) -> None:
    _log_fallback("tts.fallback_used", event.tts, available=event.available)


def _log_fallback(event_name: str, model: llm.LLM | tts.TTS, *, available: bool) -> None:
    # available=False: this model just failed and the next one in line takes over.
    log.warning(event_name, provider=model.provider, model=model.model, available=available)


def _secret(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise RuntimeError(f"{name} is not set")
    return value.get_secret_value()


def _optional_secret(value: SecretStr | None) -> str | None:
    return None if value is None else value.get_secret_value()


def _voice(voice_id: str | None) -> dict[str, str]:
    return {"voice": voice_id} if voice_id else {}


def _model(model: str | None) -> dict[str, str]:
    return {"model": model} if model else {}
