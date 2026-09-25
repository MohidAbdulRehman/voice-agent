"""The calls row: opened at session start, settled by the shutdown handler (agent.md §5)."""

import json
import time

import pytest
from livekit.agents import llm

from intake.agent.lifecycle import close_call, last_four, mask_digits, open_call, transcript_from
from intake.agent.tools import IntakeAgent
from intake.core.models import CallStatus, TranscriptEntry
from intake.core.services import Services
from intake.logging import configure_logging
from tests.agent.conftest import JANE, FakeRunContext


def conversation(*turns: tuple[str, str]) -> llm.ChatContext:
    history = llm.ChatContext()
    for role, text in turns:
        history.add_message(role=role, content=text)
    return history


TWO_TURNS = conversation(
    ("assistant", "Hi, thanks for calling. What's your first and last name?"),
    ("user", "Jane Davis."),
    ("assistant", "Thanks, Jane. What's your date of birth?"),
    ("user", "Sorry, I have to go."),
)


async def test_a_call_dropped_after_a_draft_is_abandoned_and_saves_no_patient(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    prepared = await agent.prepare_record(call, action="create", fields=JANE)
    assert prepared["status"] == "ok"

    status = await close_call(
        services,
        call.userdata,
        TWO_TURNS,
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=None,
    )

    stored = await services.calls.get(call.userdata.call_id)
    assert status == stored.status == CallStatus.ABANDONED
    assert stored.end_reason == "disconnected"
    assert stored.ended_at is not None
    assert [(e.role, e.text) for e in stored.transcript] == [
        ("assistant", "Hi, thanks for calling. What's your first and last name?"),
        ("user", "Jane Davis."),
        ("assistant", "Thanks, Jane. What's your date of birth?"),
        ("user", "Sorry, I have to go."),
    ]
    assert stored.final_payload["last_name"] == "Davis"  # the trace staff can follow up on
    assert await services.patients.find_by_phone("5125550100") == []


async def test_a_call_that_collected_nothing_is_no_action(call: FakeRunContext, services: Services):
    status = await close_call(
        services,
        call.userdata,
        conversation(("assistant", "Hi!")),
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=None,
    )

    assert status == CallStatus.NO_ACTION


async def test_the_reason_given_to_end_call_wins_over_the_fallback(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    await agent.end_call(call, reason="caller_request")

    await close_call(
        services,
        call.userdata,
        TWO_TURNS,
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=None,
    )

    assert (await services.calls.get(call.userdata.call_id)).end_reason == "caller_request"


async def test_a_summary_is_saved_once_the_caller_spoke_twice(
    call: FakeRunContext, services: Services
):
    seen: list[list[TranscriptEntry]] = []

    async def summarize(transcript: list[TranscriptEntry]) -> str:
        seen.append(transcript)
        return "  Jane Davis called to register and hung up before finishing.  "

    await close_call(
        services,
        call.userdata,
        TWO_TURNS,
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=summarize,
    )

    stored = await services.calls.get(call.userdata.call_id)
    assert stored.summary == "Jane Davis called to register and hung up before finishing."
    assert len(seen[0]) == 4


async def test_a_short_call_gets_no_summary_and_a_failing_one_is_ignored(
    call: FakeRunContext, services: Services
):
    async def broken(_transcript: list[TranscriptEntry]) -> str:
        raise RuntimeError("the LLM is down")

    short = conversation(("assistant", "Hi!"), ("user", "Hello?"))
    status = await close_call(
        services,
        call.userdata,
        short,
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=broken,  # not even called: one caller turn
    )
    await close_call(
        services,
        call.userdata,
        TWO_TURNS,
        started_at=time.monotonic(),
        fallback_reason="disconnected",
        summarize=broken,
    )

    assert status == CallStatus.NO_ACTION
    assert (await services.calls.get(call.userdata.call_id)).summary is None


def test_the_transcript_keeps_only_spoken_turns():
    history = conversation(("system", "You are Maya."), ("user", "Hi"), ("assistant", "Hello!"))
    history.add_message(role="assistant", content="")

    entries = transcript_from(history)

    assert [(e.role, e.text) for e in entries] == [("user", "Hi"), ("assistant", "Hello!")]
    assert all(e.at.tzinfo is not None for e in entries)


@pytest.mark.usefixtures("restore_logging")
async def test_opening_a_call_logs_only_the_last_four_digits(
    services: Services, capsys: pytest.CaptureFixture[str]
):
    configure_logging("INFO")

    state = await open_call(
        services,
        room_name="call-_+15125550143_AbCd",
        channel="phone",
        caller_number="5125550143",
    )

    (line,) = [json.loads(out) for out in capsys.readouterr().out.splitlines()]
    assert line["event"] == "call.started"
    assert line["call_id"] == str(state.call_id)
    assert line["caller_number"] == "0143"
    assert line["room"] == "call-_+*******0143_AbCd"
    assert "5125550143" not in json.dumps(line)


def test_masking_helpers():
    assert last_four("5125550143") == "0143"
    assert last_four(None) is None
    assert mask_digits("room-12345678901") == "room-*******8901"
    assert mask_digits("console-181c1234567e") == "console-181c1234567e"  # a random id
