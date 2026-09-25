"""Session behavior that needs no LiveKit room: greeting, silence, the time limit, caller ID."""

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from livekit import rtc
from livekit.agents import llm, tts

from intake.agent import scripts
from intake.agent.session import (
    _caller,
    build_llm,
    build_stt,
    build_voices,
    export_livekit_env,
    greet,
    limit_call_length,
    watch_silence,
)
from intake.agent.state import CallState
from intake.config import Settings


@dataclass
class FakeSession:
    """Records what the session was asked to do; ``emit`` plays an event to its handlers."""

    userdata: CallState
    said: list[tuple[str, Any]] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    shutdowns: list[bool] = field(default_factory=list)
    handlers: dict[str, Callable[[Any], None]] = field(default_factory=dict)

    def on(self, event: str, handler: Callable[[Any], None]) -> None:
        self.handlers[event] = handler

    def emit(self, event: str, payload: Any) -> None:
        self.handlers[event](payload)

    def say(self, text: str, *, allow_interruptions: Any = None) -> asyncio.Future[None]:
        self.said.append((text, allow_interruptions))
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)  # awaitable, like a SpeechHandle that has finished playing
        return done

    def generate_reply(self, *, instructions: str) -> None:
        self.replies.append(instructions)

    def shutdown(self, *, drain: bool = True) -> None:
        self.shutdowns.append(drain)


def fake_session(language: str = "English") -> FakeSession:
    state = CallState(call_id=uuid4(), channel="phone", caller_number="5125550143")
    state.language = language
    return FakeSession(state)


def away() -> SimpleNamespace:
    return SimpleNamespace(new_state="away")


async def test_silence_gets_one_check_in_then_a_goodbye():
    session = fake_session()
    watch_silence(session, wait_seconds=0.01)

    session.emit("user_state_changed", away())
    await asyncio.sleep(0.05)

    assert session.said == [
        ("Are you still there?", None),
        (scripts.SILENCE_GOODBYE["English"], False),
    ]
    assert session.shutdowns == [True]  # the goodbye is spoken before hanging up
    assert session.userdata.end_reason == "no_response"
    assert session.userdata.silence_prompts == 1


async def test_speaking_again_cancels_the_goodbye():
    session = fake_session()
    watch_silence(session, wait_seconds=0.05)

    session.emit("user_state_changed", away())
    await asyncio.sleep(0.01)
    session.emit("user_state_changed", SimpleNamespace(new_state="speaking"))
    await asyncio.sleep(0.1)

    assert session.said == [("Are you still there?", None)]
    assert session.shutdowns == []
    assert session.userdata.end_reason is None


async def test_the_silence_lines_follow_the_callers_language():
    session = fake_session("Spanish")
    watch_silence(session, wait_seconds=0.01)

    session.emit("user_state_changed", away())
    await asyncio.sleep(0.05)

    assert [text for text, _ in session.said] == ["¿Sigue ahí?", scripts.SILENCE_GOODBYE["Spanish"]]


async def test_the_time_limit_asks_for_a_wrap_up_then_ends_the_call():
    session = fake_session()

    await limit_call_length(session, minutes=0.0001, grace_seconds=0.01)

    assert session.replies == [scripts.TIME_LIMIT]
    assert session.shutdowns == [True]
    assert session.userdata.end_reason == "time_limit"


async def test_an_earlier_end_reason_is_kept_at_the_time_limit():
    session = fake_session()
    session.userdata.end_reason = "completed"

    await limit_call_length(session, minutes=0.0001, grace_seconds=0.01)

    assert session.userdata.end_reason == "completed"


async def test_the_greeting_opener_cannot_be_interrupted():
    session = fake_session()

    greet(session, Settings(_env_file=None))

    assert session.said == [
        (
            "Hi, thanks for calling Riverside Family Clinic. "
            "This is Maya, the clinic's virtual assistant.",
            False,
        ),
        (
            "I can get you registered as a new patient in just a few minutes. "
            "To start, what's your first and last name?",
            None,
        ),
    ]


@dataclass
class FakeJob:
    """The parts of JobContext that identify the caller."""

    fake: bool = False
    participant: SimpleNamespace | None = None

    def is_fake_job(self) -> bool:
        return self.fake

    async def wait_for_participant(self) -> SimpleNamespace:
        assert self.participant is not None
        return self.participant


def sip(**attributes: str) -> SimpleNamespace:
    return SimpleNamespace(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP, attributes=attributes)


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (FakeJob(fake=True), ("console", None)),
        (
            FakeJob(
                participant=SimpleNamespace(
                    kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, attributes={}
                )
            ),
            ("web", None),
        ),
        (FakeJob(participant=sip(**{"sip.phoneNumber": "+15125550143"})), ("phone", "5125550143")),
        (
            FakeJob(participant=sip(**{"sip.phoneNumber": "+442079460000"})),
            ("phone", "+442079460000"),
        ),
        (FakeJob(participant=sip()), ("phone", None)),  # caller ID withheld
    ],
)
async def test_the_channel_and_caller_number_come_from_the_participant(
    job: FakeJob, expected: tuple[str, str | None]
):
    assert await _caller(job) == expected


async def test_the_voice_pipeline_builds_from_settings(monkeypatch: pytest.MonkeyPatch):
    # Constructing the plugins checks every argument name; no request is sent.
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "x" * 40)  # long enough to sign a token with
    settings = Settings(
        _env_file=None,
        deepgram_api_key="dg-key",
        cartesia_api_key="cartesia-key",
        groq_api_key="groq-key",
        cartesia_voice_en="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        cartesia_voice_es="5c5ad5e7-1020-476b-8b91-fdcbe9cc313c",
        deepgram_tts_voice_en="aura-2-thalia-en",
        deepgram_tts_voice_es="aura-2-celeste-es",
    )

    speech_to_text = build_stt(settings)
    model = build_llm(settings)
    voices = build_voices(settings)
    voices.switch("Spanish")
    voices.switch("English")

    assert (speech_to_text.provider, speech_to_text.model) == ("Deepgram", "nova-3")
    assert isinstance(model, llm.FallbackAdapter)
    assert isinstance(voices.tts, tts.FallbackAdapter)


def test_a_missing_key_fails_at_start_with_its_name():
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY is not set"):
        build_stt(Settings(_env_file=None))


def test_livekit_settings_are_handed_over_without_overriding_the_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setenv(name, "")  # so pytest restores the variable's absence afterwards
        monkeypatch.delenv(name)
    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "from-the-environment")
    settings = Settings(
        _env_file=None, livekit_url="wss://example.livekit.cloud", livekit_api_key="key"
    )

    export_livekit_env(settings)

    assert os.environ["LIVEKIT_URL"] == "wss://example.livekit.cloud"
    assert os.environ["LIVEKIT_API_KEY"] == "key"
    assert "LIVEKIT_API_SECRET" not in os.environ  # not configured: left unset
    assert os.environ["LIVEKIT_AGENT_NAME"] == "from-the-environment"
