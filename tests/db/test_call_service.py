"""CallService: the calls row from start to finish."""

from uuid import uuid4

import pytest

from intake.core.models import CallStatus, NotFound, TranscriptEntry
from intake.core.services import CallService, PatientService
from tests.cases import VALID_INPUT
from tests.db.helpers import NOW

TRANSCRIPT = [
    TranscriptEntry(role="assistant", text="Hi, thanks for calling.", at=NOW),
    TranscriptEntry(role="user", text="Hi, I'd like to register.", at=NOW),
]


async def test_start_opens_an_in_progress_call(calls: CallService):
    call_id = await calls.start(room_name="room-1", channel="phone", caller_number="5125550100")

    call = await calls.get(call_id)

    assert (call.status, call.channel, call.caller_number, call.language) == (
        CallStatus.IN_PROGRESS,
        "phone",
        "5125550100",
        "English",
    )
    assert (call.final_payload, call.transcript, call.ended_at) == (None, [], None)


async def test_a_room_dispatched_again_keeps_its_call(calls: CallService):
    first = await calls.start(room_name="room-1", channel="phone", caller_number=None)

    assert await calls.start(room_name="room-1", channel="phone", caller_number=None) == first


async def test_a_call_without_collected_data_ends_as_no_action(calls: CallService):
    call_id = await calls.start(room_name="room-1", channel="console", caller_number=None)

    status = await calls.finish(call_id, end_reason="caller_request", transcript=TRANSCRIPT)

    assert status == CallStatus.NO_ACTION


async def test_a_dropped_call_keeps_its_draft_and_transcript(calls: CallService):
    call_id = await calls.start(room_name="room-1", channel="phone", caller_number=None)
    await calls.save_payload(call_id, {"first_name": "Jane", "last_name": "Doe"})

    status = await calls.finish(
        call_id, end_reason="participant_disconnected", transcript=TRANSCRIPT
    )

    call = await calls.get(call_id)
    assert status == call.status == CallStatus.ABANDONED
    assert call.final_payload == {"first_name": "Jane", "last_name": "Doe"}
    assert call.transcript == TRANSCRIPT
    assert call.end_reason == "participant_disconnected"
    assert call.ended_at is not None


async def test_registered_and_failed_calls_keep_their_status(
    calls: CallService, patients: PatientService
):
    registered = await calls.start(room_name="room-1", channel="phone", caller_number=None)
    await patients.create(VALID_INPUT, call_id=registered)
    failed = await calls.start(room_name="room-2", channel="phone", caller_number=None)
    await calls.save_payload(failed, {"first_name": "Jane"})
    await calls.mark_failed(failed)

    assert await calls.finish(registered, end_reason="completed", transcript=[]) == (
        CallStatus.REGISTERED
    )
    assert await calls.finish(failed, end_reason="completed", transcript=[]) == CallStatus.FAILED


async def test_language_and_summary_are_stored(calls: CallService):
    call_id = await calls.start(room_name="room-1", channel="web", caller_number=None)

    await calls.set_language(call_id, "Spanish")
    await calls.save_summary(call_id, "The caller registered and booked a visit.")

    call = await calls.get(call_id)
    assert (call.language, call.summary) == ("Spanish", "The caller registered and booked a visit.")


async def test_list_calls_newest_first_by_status_or_patient(
    calls: CallService, patients: PatientService
):
    first = await calls.start(room_name="room-1", channel="phone", caller_number=None)
    second = await calls.start(room_name="room-2", channel="phone", caller_number=None)
    patient = await patients.create(VALID_INPUT, call_id=second)

    assert [c.call_id for c in await calls.list_calls()] == [second, first]
    assert [c.call_id for c in await calls.list_calls(status=CallStatus.IN_PROGRESS)] == [first]
    assert [c.call_id for c in await calls.list_calls(patient_id=patient.patient_id)] == [second]


async def test_unknown_calls_are_not_found(calls: CallService):
    with pytest.raises(NotFound, match="call not found"):
        await calls.get(uuid4())
    with pytest.raises(NotFound, match="call not found"):
        await calls.save_payload(uuid4(), {"first_name": "Jane"})
    with pytest.raises(NotFound, match="call not found"):
        await calls.finish(uuid4(), end_reason="completed", transcript=[])
