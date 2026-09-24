"""/calls and /doctors: the read-only endpoints behind the dashboard."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from intake.core.models import TranscriptEntry
from intake.core.services import Services
from tests.api.envelope import expect
from tests.db.helpers import NOW

TRANSCRIPT = [
    TranscriptEntry(role="assistant", text="Hi, this is Maya.", at=NOW),
    TranscriptEntry(role="user", text="I'd like to register.", at=NOW + timedelta(seconds=3)),
]


async def _finished_call(services: Services, room: str, caller: str | None = None) -> UUID:
    call_id = await services.calls.start(room_name=room, channel="phone", caller_number=caller)
    await services.calls.save_payload(
        call_id, {"first_name": "Jane", "date_of_birth": "03/05/1990"}
    )
    await services.calls.finish(call_id, end_reason="caller_hung_up", transcript=TRANSCRIPT)
    return call_id


async def test_calls_are_listed_newest_first_without_transcripts(
    client: httpx.AsyncClient, services: Services
):
    first = await _finished_call(services, "room-1")
    second = await services.calls.start(room_name="room-2", channel="web", caller_number=None)

    calls = expect(await client.get("/calls"), 200)

    assert [call["call_id"] for call in calls] == [str(second), str(first)]
    assert "transcript" not in calls[0]
    assert "final_payload" not in calls[0]
    assert "room_name" not in calls[0]


async def test_calls_filter_by_status_and_page(client: httpx.AsyncClient, services: Services):
    abandoned = await _finished_call(services, "room-1")
    await services.calls.start(room_name="room-2", channel="web", caller_number=None)

    by_status = expect(await client.get("/calls", params={"status": "abandoned"}), 200)
    paged = expect(await client.get("/calls", params={"limit": 1, "offset": 1}), 200)

    assert [call["call_id"] for call in by_status] == [str(abandoned)]
    assert [call["call_id"] for call in paged] == [str(abandoned)]


@pytest.mark.parametrize("params", [{"status": "done"}, {"limit": "0"}, {"offset": "x"}])
async def test_bad_call_filters_are_bad_requests(client: httpx.AsyncClient, params: dict):
    error = expect(await client.get("/calls", params=params), 400)

    assert [detail["field"] for detail in error["details"]] == list(params)


async def test_a_call_comes_with_its_transcript_and_masked_caller(
    client: httpx.AsyncClient, services: Services
):
    call_id = await _finished_call(services, "room-1", caller="+12125550143")

    call = expect(await client.get(f"/calls/{call_id}"), 200)

    assert call["status"] == "abandoned"
    assert call["caller_number"] == "***-***-0143"
    assert call["final_payload"] == {"first_name": "Jane", "date_of_birth": "03/05/1990"}
    assert call["transcript"] == [
        {"role": "assistant", "text": "Hi, this is Maya.", "at": "2026-09-24T16:00:00.000000Z"},
        {"role": "user", "text": "I'd like to register.", "at": "2026-09-24T16:00:03.000000Z"},
    ]


async def test_unknown_and_malformed_call_ids(client: httpx.AsyncClient):
    missing = expect(await client.get(f"/calls/{uuid4()}"), 404)
    malformed = expect(await client.get("/calls/42"), 400)

    assert missing["message"] == "Call not found."
    assert malformed["message"] == "call_id must be a UUID."


@pytest.mark.usefixtures("seeded")
async def test_doctors_are_listed_by_name(client: httpx.AsyncClient):
    doctors = expect(await client.get("/doctors"), 200)

    assert [(d["full_name"], d["specialty"], d["languages"]) for d in doctors] == [
        ("Dr. Elena Ruiz", "Family Medicine", ["English", "Spanish"]),
        ("Dr. Marcus Reed", "Internal Medicine", ["English"]),
        ("Dr. Priya Shah", "Family Medicine", ["English"]),
    ]
