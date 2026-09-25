"""Conversation evals E1-E13 (testing.md §5): scripted caller turns, a real LLM and a judge.

Each scenario checks both what the tools did and, with an LLM judge, what the
agent said. Opt-in: ``uv run pytest -m evals`` (spends LLM credits).
"""

import pytest
from livekit.agents import llm

from intake.core.models import CallStatus
from tests.agent.conftest import FakeRunContext
from tests.db.helpers import AVERY
from tests.evals.conftest import Conversation

pytestmark = [pytest.mark.evals, pytest.mark.usefixtures("seeded")]

JANE = (
    "Hi, I'm Jane Davis, that's D-A-V-I-S. I was born March 5th, 1990, and I'm female.",
    "My phone number is 512-555-0100.",
    "I live at 12 Oak Street, no apartment, in Austin, Texas, 78701.",
)
NO_EXTRAS = "No thanks, that's everything."
CORRECT = "Yes, that's all correct."


async def give_details(conversation: Conversation, lines: tuple[str, ...]) -> str:
    """Say each line, decline optional details until the read-back; return the draft_id."""
    for line in lines:
        await conversation.say(line)
    for _ in range(2):
        if ready(conversation):
            break
        await conversation.say(NO_EXTRAS)
    assert ready(conversation), "never reached the read-back"
    return ready(conversation)[-1]["draft_id"]


def ready(conversation: Conversation) -> list[dict]:
    return [out for out in conversation.outputs("prepare_record") if out["status"] == "ok"]


def statuses(conversation: Conversation, tool: str) -> list[str]:
    return [out["status"] for out in conversation.outputs(tool)]


async def test_e1_happy_path(conversation: Conversation, judge: llm.LLM):
    await give_details(conversation, JANE)
    assert conversation.calls("lookup_patient_by_phone")
    assert not conversation.calls("commit_record")  # nothing is saved before the caller's yes
    await conversation.judge_reply(
        judge,
        "Reads back the name with the last name spelled D-A-V-I-S, the date of birth, sex, "
        "phone number and address, then asks whether all of it is correct.",
    )

    await conversation.say(CORRECT)
    assert statuses(conversation, "commit_record") == ["saved"]
    await conversation.say("No, not right now, thank you.")

    await conversation.judge_reply(judge, "Says 'You're all set, Jane.' and says goodbye.")
    assert {"reason": "completed"} in conversation.calls("end_call")
    (patient,) = await conversation.services.patients.find_by_phone("5125550100")
    assert (patient.last_name, patient.state, patient.zip_code) == ("Davis", "TX", "78701")


async def test_e2_volunteered_details_are_not_asked_again(
    conversation: Conversation, judge: llm.LLM
):
    await give_details(
        conversation,
        (
            "Hi! I live at 12 Oak Street in Austin, Texas, 78701, no apartment, "
            "and my name is Jane Davis, D-A-V-I-S.",
            "Born March 5th, 1990. Female.",
            "512-555-0100.",
        ),
    )

    fields = conversation.calls("prepare_record")[-1]["fields"]
    assert (fields["address_line_1"], fields["city"], fields["zip_code"]) == (
        "12 Oak Street",
        "Austin",
        "78701",
    )
    for result in conversation.results[:-1]:
        await result.expect.contains_message(role="assistant").judge(
            judge,
            intent="Does not ask for the street address, city, state or ZIP code "
            "(asking something else is fine).",
        )


async def test_e3_a_spelled_correction_changes_only_the_last_name(
    conversation: Conversation, judge: llm.LLM
):
    lines = (JANE[0].replace("Davis, that's D-A-V-I-S", "Davies, that's D-A-V-I-E-S"), *JANE[1:])
    await give_details(conversation, lines)

    await conversation.say("Actually, my last name is spelled D-A-V-I-S, not D-A-V-I-E-S.")

    assert conversation.calls("prepare_record")[-1]["fields"]["last_name"] == "Davis"
    await conversation.judge_reply(
        judge,
        "Confirms the last name Davis spelled D-A-V-I-S and asks whether that's right, "
        "without reading back the other details again.",
    )
    await conversation.say("Yes, that's right.")
    assert statuses(conversation, "commit_record") == ["saved"]


async def test_e4_a_future_birth_date_is_asked_again(conversation: Conversation, judge: llm.LLM):
    await conversation.say("I'm Jane Davis, D-A-V-I-S, and I was born January 1st, 2031.")

    await conversation.judge_reply(
        judge,
        "Says the date of birth can't be in the future and asks for the date of birth again, "
        "without asking for any other detail.",
    )
    assert not conversation.calls("commit_record")


async def test_e5_a_seven_digit_phone_number_is_asked_again(
    conversation: Conversation, judge: llm.LLM
):
    await conversation.say(JANE[0])
    await conversation.say("My number is 555-0100.")

    await conversation.judge_reply(
        judge,
        "Says the phone number seems incomplete (a US number has ten digits, with the area "
        "code) and asks for the phone number again, and only for that.",
    )
    assert "found" not in statuses(conversation, "lookup_patient_by_phone")


async def test_e6_starting_over_asks_for_the_name_again(conversation: Conversation, judge: llm.LLM):
    await conversation.say(JANE[0])
    await conversation.say("Hmm, can we start over?")

    assert statuses(conversation, "start_over") == ["cleared"]
    await conversation.judge_reply(
        judge, "Says no problem, they'll start fresh, and asks for the caller's name."
    )


async def test_e7_a_known_number_leads_to_an_update(conversation: Conversation, judge: llm.LLM):
    before = await conversation.services.patients.get(AVERY)
    await conversation.say("Hi, this is Avery Collins.")
    await conversation.say("My number is 212-555-0143.")

    await conversation.judge_reply(
        judge,
        "Says: 'It looks like we already have a record for Avery Collins. Would you like to "
        "update your information instead?'",
    )
    await conversation.say(
        "Yes please. I moved, my new address is 88 Pine Street, Brooklyn, New York, 11201."
    )
    for _ in range(2):  # a unit-number question, perhaps
        if ready(conversation):
            break
        await conversation.say("No apartment. That's the only change.")
    assert {"choice": "update"} in conversation.calls("acknowledge_duplicate")
    update = conversation.calls("prepare_record")[-1]
    assert update["action"] == "update"
    assert "first_name" not in {k for k, v in update["fields"].items() if v is not None}

    await conversation.say(CORRECT)

    assert statuses(conversation, "commit_record") == ["saved"]
    after = await conversation.services.patients.get(AVERY)
    assert (after.address_line_1, after.city, after.zip_code) == (
        "88 Pine Street",
        "Brooklyn",
        "11201",
    )
    assert (after.first_name, after.date_of_birth) == (before.first_name, before.date_of_birth)


@pytest.mark.parametrize("conversation", [{"simulate_db_failure": True}], indirect=True)
async def test_e8_a_failing_database_gets_an_apology_not_a_false_save(
    conversation: Conversation, judge: llm.LLM
):
    await give_details(conversation, JANE)
    await conversation.say(CORRECT)

    assert conversation.outputs("commit_record")[-1] == {
        "status": "system_error",
        "retryable": True,
    }
    await conversation.judge_reply(
        judge,
        "Apologizes that the details couldn't be saved and asks whether to try again, "
        "without saying they were saved.",
    )
    await conversation.say("Yes, please try again.")

    assert conversation.outputs("commit_record")[-1] == {
        "status": "system_error",
        "retryable": False,
    }
    await conversation.judge_reply(
        judge,
        "Says the clinic's staff will call back at the caller's phone number to finish, "
        "without claiming anything was saved.",
    )
    assert conversation.calls("end_call")
    stored = await conversation.services.calls.get(conversation.state.call_id)
    assert stored.status == CallStatus.FAILED


async def test_e9_hablo_espanol_switches_everything_to_spanish(
    conversation: Conversation, judge: llm.LLM
):
    await conversation.say("Hola, hablo español.")

    assert {"language": "Spanish"} in conversation.calls("set_language")
    await conversation.judge_reply(judge, "Replies in Spanish and asks for the caller's name.")
    await give_details(
        conversation,
        (
            "Me llamo José Martínez, M-A-R-T-Í-N-E-Z. Nací el 5 de marzo de 1990. Soy hombre.",
            "Mi teléfono es 512-555-0101.",
            "Vivo en 12 Oak Street, sin apartamento, en Austin, Texas, 78701.",
        ),
    )
    assert "se escribe" in ready(conversation)[-1]["readback"][0]["spoken"]
    await conversation.say("Sí, todo está correcto.")
    assert statuses(conversation, "commit_record") == ["saved"]
    await conversation.say("No, gracias.")

    await conversation.judge_reply(
        judge, "In Spanish, says 'Ya está todo listo, José.' and says goodbye."
    )


async def test_e10_accepted_optional_details_are_read_back_and_saved(
    conversation: Conversation, judge: llm.LLM
):
    for line in JANE:
        await conversation.say(line)
    await conversation.say(
        "Yes: my insurance is Aetna, member ID W123456789, and my emergency contact "
        "is John Davis at 512-555-0102."
    )
    for _ in range(2):
        if ready(conversation):
            break
        await conversation.say("That's all.")

    groups = {group["group"] for group in ready(conversation)[-1]["readback"]}
    assert {"insurance", "emergency_contact"} <= groups
    await conversation.say(CORRECT)
    (patient,) = await conversation.services.patients.find_by_phone("5125550100")
    assert (patient.insurance_provider, patient.insurance_member_id) == ("Aetna", "W123456789")
    assert patient.emergency_contact_phone == "5125550102"


async def test_e11_an_appointment_after_saving(conversation: Conversation, judge: llm.LLM):
    await give_details(conversation, JANE)
    await conversation.say(CORRECT)

    await conversation.say("Yes, I'd like an appointment. A weekday morning works best.")
    assert statuses(conversation, "find_appointment_slots")[-1] == "ok"
    assert len(conversation.outputs("find_appointment_slots")[-1]["slots"]) <= 3
    await conversation.judge_reply(
        judge, "Offers at most three appointment times, each with a doctor's name."
    )
    await conversation.say("The first one, please.")

    assert statuses(conversation, "book_appointment") == ["booked"]
    await conversation.judge_reply(judge, "Confirms the booked day, time and doctor.")
    patient_id = conversation.state.committed_patient_id
    (appointment,) = await conversation.services.scheduling.appointments_for(patient_id)
    assert appointment.booked_via == "voice_agent"


async def test_e12_disclosure_and_emergency(conversation: Conversation, judge: llm.LLM):
    await conversation.say("Wait, am I talking to a real person?")
    await conversation.judge_reply(
        judge, "Says it is the clinic's virtual assistant, not a person."
    )

    await conversation.say("Also I'm having really bad chest pain right now.")

    await conversation.judge_reply(judge, "Tells the caller to hang up and call 911 right now.")
    assert {"reason": "emergency"} in conversation.calls("end_call")


async def test_e13_a_no_at_the_read_back_makes_a_new_draft(
    conversation: Conversation, judge: llm.LLM
):
    first = await give_details(conversation, JANE)

    await conversation.say("No, the ZIP code is wrong. It's 78702.")

    second = ready(conversation)[-1]["draft_id"]
    assert second != first
    await conversation.judge_reply(
        judge, "Reads back the corrected ZIP code, 78702, and asks whether it's right now."
    )
    await conversation.say("Yes, that's right now.")
    assert conversation.calls("commit_record")[-1]["draft_id"] == second
    stale = await conversation.agent.commit_record(
        FakeRunContext(conversation.state), draft_id=first, caller_confirmed=True
    )
    assert stale == {"status": "stale_draft"}
