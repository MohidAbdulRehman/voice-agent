"""The nine tools on the test database, called the way the LLM calls them (testing.md §4)."""

import json
from uuid import uuid4

import pytest

from intake.agent.state import CallState, SlotRef
from intake.agent.tools import IntakeAgent, PatientFields
from intake.core.models import CallStatus
from intake.core.services import Services
from intake.logging import configure_logging
from tests.agent.conftest import JANE, AgentFactory, FakeRunContext
from tests.db.helpers import AVERY, upcoming

pytestmark = pytest.mark.usefixtures("seeded")  # 2 patients, 3 doctors with schedules


def jane(**changes: str | None) -> PatientFields:
    return JANE.model_copy(update=changes)


async def prepared(agent: IntakeAgent, call: FakeRunContext, fields: PatientFields = JANE) -> str:
    result = await agent.prepare_record(call, action="create", fields=fields)
    assert result["status"] == "ok", result
    return result["draft_id"]


async def saved(agent: IntakeAgent, call: FakeRunContext) -> None:
    draft_id = await prepared(agent, call)
    result = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)
    assert result["status"] == "saved", result


async def patients_with(services: Services, phone: str) -> int:
    return len(await services.patients.find_by_phone(phone))


# --- lookup_patient_by_phone -------------------------------------------------------


async def test_lookup_finds_an_active_patient_by_any_phone_format(
    agent: IntakeAgent, call: FakeRunContext
):
    result = await agent.lookup_patient_by_phone(call, phone_number="+1 (212) 555-0143")

    assert result == {
        "status": "found",
        "patient": {"first_name": "Avery", "last_name": "Collins"},
        "match_count": 1,
    }
    assert call.userdata.matched_patient_id == AVERY  # remembered, never shown to the LLM


async def test_lookup_reports_an_unknown_or_invalid_number(
    agent: IntakeAgent, call: FakeRunContext
):
    unknown = await agent.lookup_patient_by_phone(call, phone_number="512-555-0199")
    invalid = await agent.lookup_patient_by_phone(call, phone_number="555-0100")

    assert unknown == {"status": "not_found"}
    assert invalid["status"] == "invalid"
    assert [e["code"] for e in invalid["errors"]] == ["invalid_phone"]


# --- prepare_record ----------------------------------------------------------------


async def test_prepare_lists_what_is_missing(agent: IntakeAgent, call: FakeRunContext):
    result = await agent.prepare_record(
        call, action="create", fields=PatientFields(first_name="Jane", zip_code="787")
    )

    assert result["status"] == "incomplete"
    assert result["missing"] == [
        "last_name",
        "date_of_birth",
        "sex",
        "phone_number",
        "address_line_1",
        "city",
        "state",
    ]
    assert [e["code"] for e in result["errors"]] == ["invalid_zip"]


async def test_prepare_rejects_a_future_birth_date_only(agent: IntakeAgent, call: FakeRunContext):
    result = await agent.prepare_record(
        call, action="create", fields=jane(date_of_birth="01/01/2030")
    )

    assert result == {
        "status": "invalid",
        "errors": [
            {
                "field": "date_of_birth",
                "code": "in_future",
                "message": "Date of birth can't be in the future.",
            }
        ],
    }


async def test_prepare_reads_back_normalized_details_and_keeps_them_on_the_call(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    result = await agent.prepare_record(call, action="create", fields=JANE)

    assert result["status"] == "ok"
    assert result["draft_id"].startswith("d-")
    assert result["readback"] == [
        {"group": "name", "spoken": "Jane Davis, that's D-A-V-I-S."},
        {"group": "dob_sex", "spoken": "Date of birth March 5th, 1990. Sex: Female."},
        {
            "group": "phone_email",
            "spoken": "Phone five one two, five five five, zero one zero zero.",
        },
        {
            "group": "address",
            "spoken": "Address 12 Oak Street, Austin, Texas, seven eight seven zero one.",
        },
    ]
    stored = await services.calls.get(call.userdata.call_id)
    assert stored.status == CallStatus.IN_PROGRESS
    assert stored.final_payload == {
        "first_name": "Jane",
        "last_name": "Davis",
        "date_of_birth": "03/05/1990",
        "sex": "Female",
        "phone_number": "5125550100",
        "email": None,
        "address_line_1": "12 Oak Street",
        "address_line_2": None,
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "insurance_provider": None,
        "insurance_member_id": None,
        "preferred_language": "English",
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
    }


async def test_prepare_reads_back_in_the_session_language(
    agent: IntakeAgent, call: FakeRunContext, voices: list[str], services: Services
):
    switched = await agent.set_language(call, language="Spanish")
    result = await agent.prepare_record(
        call, action="create", fields=jane(preferred_language="español")
    )

    assert switched == {"status": "ok", "language": "Spanish"}
    assert voices == ["Spanish"]
    assert (await services.calls.get(call.userdata.call_id)).language == "Spanish"
    assert result["readback"][0] == {"group": "name", "spoken": "Jane Davis, se escribe D-A-V-I-S."}
    assert result["readback"][-1] == {"group": "language", "spoken": "Idioma preferido español."}


async def test_a_known_phone_number_is_a_duplicate_until_the_caller_answers(
    agent: IntakeAgent, call: FakeRunContext
):
    avery_phone = jane(phone_number="212-555-0143")

    duplicate = await agent.prepare_record(call, action="create", fields=avery_phone)
    answered = await agent.acknowledge_duplicate(call, choice="create_new")
    again = await agent.prepare_record(call, action="create", fields=avery_phone)

    assert duplicate == {
        "status": "duplicate",
        "patient": {"first_name": "Avery", "last_name": "Collins"},
    }
    assert answered == {"status": "ok", "mode": "create"}
    assert again["status"] == "ok"


# --- commit_record -----------------------------------------------------------------


async def test_commit_needs_the_callers_yes_and_the_latest_draft(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    first = await prepared(agent, call)
    latest = await prepared(agent, call, jane(city="Round Rock"))

    unconfirmed = await agent.commit_record(call, draft_id=latest, caller_confirmed=False)
    stale = await agent.commit_record(call, draft_id=first, caller_confirmed=True)

    assert unconfirmed == {"status": "not_confirmed"}
    assert stale == {"status": "stale_draft"}
    assert await patients_with(services, "5125550100") == 0
    assert call.interruptible is False  # a save isn't cut off by the caller speaking


async def test_committing_the_same_draft_twice_saves_one_patient(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    draft_id = await prepared(agent, call)

    first = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)
    second = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)

    assert first == second == {"status": "saved", "action": "create", "first_name": "Jane"}
    (patient,) = await services.patients.find_by_phone("5125550100")
    stored = await services.calls.get(call.userdata.call_id)
    assert stored.status == CallStatus.REGISTERED
    assert stored.patient_id == patient.patient_id == call.userdata.committed_patient_id
    assert (patient.state, patient.sex) == ("TX", "Female")


@pytest.mark.usefixtures("restore_logging")
async def test_a_save_logs_the_final_payload(
    agent: IntakeAgent, call: FakeRunContext, capsys: pytest.CaptureFixture[str]
):
    configure_logging("INFO")

    await saved(agent, call)

    (committed,) = [line for line in logged(capsys) if line["event"] == "registration.committed"]
    assert committed["action"] == "create"
    assert committed["patient_id"] == str(call.userdata.committed_patient_id)
    assert committed["payload"]["last_name"] == "Davis"
    assert committed["payload"]["phone_number"] == "5125550100"  # the full record, as saved


@pytest.mark.usefixtures("restore_logging")
async def test_a_failing_database_gets_one_retry_offer_then_the_call_is_failed(
    make_agent: AgentFactory,
    call: FakeRunContext,
    services: Services,
    capsys: pytest.CaptureFixture[str],
):
    configure_logging("INFO")
    agent = make_agent(simulate_db_failure=True)
    draft_id = await prepared(agent, call)

    first = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)
    second = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)
    third = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)

    assert first == {"status": "system_error", "retryable": True}
    assert second == third == {"status": "system_error", "retryable": False}
    stored = await services.calls.get(call.userdata.call_id)
    assert stored.status == CallStatus.FAILED
    assert stored.final_payload["last_name"] == "Davis"  # kept for staff to follow up
    assert await patients_with(services, "5125550100") == 0
    (failure,) = [line for line in logged(capsys) if line["event"] == "registration.failed"]
    assert failure["level"] == "error"
    assert failure["error"] == "PersistenceError"
    assert failure["payload"]["phone_number"] == "5125550100"  # for staff to re-enter


# --- the update path ---------------------------------------------------------------


async def test_an_update_writes_only_the_changes_and_links_the_call(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    before = await services.patients.get(AVERY)
    await agent.lookup_patient_by_phone(call, phone_number="2125550143")
    chosen = await agent.acknowledge_duplicate(call, choice="update")
    prepared_update = await agent.prepare_record(
        call, action="update", fields=PatientFields(city="Brooklyn", zip_code="11201")
    )
    result = await agent.commit_record(
        call, draft_id=prepared_update["draft_id"], caller_confirmed=True
    )

    assert chosen == {"status": "ok", "mode": "update"}
    assert prepared_update["readback"] == [
        {"group": "address", "spoken": "City Brooklyn. ZIP code one one two zero one."}
    ]
    assert result == {"status": "saved", "action": "update", "first_name": "Avery"}
    after = await services.patients.get(AVERY)
    assert (after.city, after.zip_code) == ("Brooklyn", "11201")
    unchanged = after.model_dump(exclude={"city", "zip_code", "updated_at"})
    assert unchanged == before.model_dump(exclude={"city", "zip_code", "updated_at"})
    stored = await services.calls.get(call.userdata.call_id)
    assert (stored.status, stored.patient_id) == (CallStatus.UPDATED, AVERY)


async def test_an_update_needs_the_caller_to_choose_it_first(
    agent: IntakeAgent, call: FakeRunContext
):
    result = await agent.prepare_record(
        call, action="update", fields=PatientFields(city="Brooklyn")
    )

    assert result["status"] == "invalid"
    assert result["errors"][0]["code"] == "no_patient_to_update"


async def test_a_correction_after_saving_updates_the_new_record(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    await saved(agent, call)

    again = await agent.prepare_record(call, action="create", fields=JANE)
    fix = await agent.prepare_record(call, action="update", fields=PatientFields(city="Dallas"))
    result = await agent.commit_record(call, draft_id=fix["draft_id"], caller_confirmed=True)

    assert again["errors"][0]["code"] == "already_registered"
    assert result["status"] == "saved"
    (patient,) = await services.patients.find_by_phone("5125550100")
    assert patient.city == "Dallas"
    stored = await services.calls.get(call.userdata.call_id)
    assert stored.status == CallStatus.REGISTERED  # still the call that registered her


# --- start_over --------------------------------------------------------------------


async def test_start_over_forgets_the_draft_but_not_the_call(
    agent: IntakeAgent, call: FakeRunContext
):
    await agent.set_language(call, language="Spanish")
    draft_id = await prepared(agent, call)
    call_id = call.userdata.call_id

    cleared = await agent.start_over(call)
    commit = await agent.commit_record(call, draft_id=draft_id, caller_confirmed=True)

    assert cleared == {"status": "cleared"}
    assert commit == {"status": "stale_draft"}
    assert (call.userdata.call_id, call.userdata.language) == (call_id, "Spanish")


# --- appointments ------------------------------------------------------------------


async def test_slots_need_a_saved_patient(agent: IntakeAgent, call: FakeRunContext):
    result = await agent.find_appointment_slots(call)

    assert result == {"status": "not_registered"}


async def test_up_to_three_slots_are_offered_by_opaque_id(agent: IntakeAgent, call: FakeRunContext):
    await saved(agent, call)

    result = await agent.find_appointment_slots(call, time_of_day="afternoon")

    assert result["status"] == "ok"
    assert [slot["slot_id"] for slot in result["slots"]] == ["s1", "s2", "s3"]
    assert all(" PM" in slot["spoken"] for slot in result["slots"])
    assert set(call.userdata.offered_slots) == {"s1", "s2", "s3"}


async def test_spanish_callers_are_offered_a_spanish_speaking_doctor_first(
    agent: IntakeAgent, call: FakeRunContext
):
    await agent.set_language(call, language="Spanish")
    await saved(agent, call)

    result = await agent.find_appointment_slots(call)

    assert result["slots"][0]["doctor"] == "Dr. Elena Ruiz"
    assert " de la " in result["slots"][0]["spoken"]


async def test_a_day_without_openings_offers_the_next_available(
    agent: IntakeAgent, call: FakeRunContext
):
    await saved(agent, call)
    sunday = upcoming(6).strftime("%m/%d/%Y")

    result = await agent.find_appointment_slots(call, preferred_date=sunday)
    invalid = await agent.find_appointment_slots(call, preferred_date="2026-10-01")

    assert result["status"] == "none"
    assert len(result["next_available"]) == 3
    assert invalid["status"] == "invalid"


async def test_booking_a_slot_someone_just_took_offers_alternatives(
    agent: IntakeAgent, call: FakeRunContext, services: Services
):
    await saved(agent, call)
    offered = await agent.find_appointment_slots(call)
    slot = call.userdata.offered_slots["s1"]
    rival = await _rival_call(services, slot)

    booked = await agent.book_appointment(call, slot_id="s1")
    taken = await agent.book_appointment(rival, slot_id="s1")

    assert booked == {
        "status": "booked",
        "spoken": f"{offered['slots'][0]['spoken']} with {slot.doctor_name}",
    }
    assert taken["status"] == "slot_taken"
    assert 1 <= len(taken["alternatives"]) <= 3
    assert taken["alternatives"][0]["slot_id"] == "s2"  # new ids, scoped to the rival's call
    appointments = await services.scheduling.appointments_for(call.userdata.committed_patient_id)
    assert [a.call_id for a in appointments] == [call.userdata.call_id]


async def test_an_unknown_slot_id_is_refused(agent: IntakeAgent, call: FakeRunContext):
    await saved(agent, call)

    result = await agent.book_appointment(call, slot_id="s9")

    assert result == {"status": "unknown_slot"}


async def _rival_call(services: Services, slot: SlotRef) -> FakeRunContext:
    """Another call whose saved caller was offered the same slot."""
    call_id = await services.calls.start(room_name="rival", channel="phone", caller_number=None)
    rival = await services.patients.create(
        JANE.model_dump(exclude_none=True) | {"first_name": "Rita", "state": "TX"}
    )
    state = CallState(call_id=call_id, channel="phone", caller_number=None)
    state.committed_patient_id = rival.patient_id
    state.offered_slots["s1"] = slot
    return FakeRunContext(state)


# --- end_call, and the rules every tool follows ------------------------------------


async def test_end_call_hangs_up_only_after_the_goodbye_is_spoken(
    agent: IntakeAgent, call: FakeRunContext
):
    result = await agent.end_call(call, reason="completed")

    assert result == {"status": "ending"}  # the LLM answers it with the goodbye
    assert call.session.shutdowns == []  # still speaking
    call.speech_handle.finish()  # the reply, goodbye included, has played
    assert call.session.shutdowns == [True]
    assert call.userdata.end_reason == "completed"


async def test_an_earlier_end_reason_is_kept(agent: IntakeAgent, call: FakeRunContext):
    call.userdata.end_reason = "time_limit"

    await agent.end_call(call, reason="completed")

    assert call.userdata.end_reason == "time_limit"


@pytest.mark.usefixtures("restore_logging")
async def test_a_tool_never_raises_to_the_llm(
    unreachable_agent: IntakeAgent, capsys: pytest.CaptureFixture[str]
):
    configure_logging("INFO")
    call = FakeRunContext(CallState(call_id=uuid4(), channel="console", caller_number=None))

    result = await unreachable_agent.lookup_patient_by_phone(call, phone_number="512-555-0100")

    assert result == {"status": "system_error"}
    lines = logged(capsys)
    (failure,) = [line for line in lines if line["event"] == "tool.failed"]
    assert "ConnectionRefusedError" in failure["exception"]  # the stack trace is logged
    (called,) = [line for line in lines if line["event"] == "tool.called"]
    assert (called["tool"], called["status"]) == ("lookup_patient_by_phone", "system_error")


def logged(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]
