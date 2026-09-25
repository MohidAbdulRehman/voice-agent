"""Conversation evals E1-E7 (testing.md §5): scripted caller turns, a real LLM and a judge.

Each scenario checks both what the tools did and, with an LLM judge, what the
agent said. Opt-in: ``uv run pytest -m evals`` (spends LLM credits; the run ends
with the tokens it used and their cost).
"""

import pytest
from livekit.agents import llm

from tests.db.helpers import AVERY
from tests.evals.conftest import Conversation

pytestmark = [pytest.mark.evals, pytest.mark.usefixtures("seeded")]

JANE = (
    "Hi, I'm Jane Davis, that's D-A-V-I-S. I was born March 5th, 1990, and I'm female.",
    "Yes. My phone number is 512-555-0100.",  # "yes" in case the last name was spelled back
    "I live at 12 Oak Street, no apartment, in Austin, Texas, 78701.",
)
NO_EXTRAS = "No thanks, that's everything."
CHECK = "Yes, that's right."  # to the agent checking a detail along the way
CORRECT = "Yes, that's all correct."


async def give_details(conversation: Conversation, lines: tuple[str, ...]) -> str:
    """Say each line, then answer until the read-back; return the draft_id."""
    for line in lines:
        await conversation.say(line)
    for _ in range(3):
        if ready(conversation):
            break
        await conversation.say(NO_EXTRAS if offered_optional_details(conversation) else CHECK)
    assert ready(conversation), "never reached the read-back"
    return ready(conversation)[-1]["draft_id"]


def ready(conversation: Conversation) -> list[dict]:
    return [out for out in conversation.outputs("prepare_record") if out["status"] == "ok"]


def statuses(conversation: Conversation, tool: str) -> list[str]:
    return [out["status"] for out in conversation.outputs(tool)]


async def answer_checks(conversation: Conversation) -> None:
    """Say yes while the agent checks details, until it offers the optional details."""
    for _ in range(2):
        if offered_optional_details(conversation) or ready(conversation):
            return
        await conversation.say(CHECK)


def offered_optional_details(conversation: Conversation) -> bool:
    """Whether the agent's last message offers the optional details (the prompt's wording)."""
    replies = [
        event.item.text_content or ""
        for event in conversation.results[-1].events
        if event.type == "message" and event.item.role == "assistant"
    ]
    return bool(replies) and "insurance" in replies[-1].lower()


async def test_e1_happy_path(conversation: Conversation, judge: llm.LLM):
    for line in JANE:
        await conversation.say(line)
    assert conversation.calls("lookup_patient_by_phone")
    await answer_checks(conversation)
    assert offered_optional_details(conversation), "the optional details weren't offered"

    await conversation.say(NO_EXTRAS)
    assert ready(conversation), "never reached the read-back"
    assert not conversation.calls("commit_record")  # nothing is saved before the caller's yes
    await conversation.judge_reply(
        judge,
        "Reads back the name with the last name spelled D-A-V-I-S, the date of birth, sex, "
        "phone number and address, then asks whether all of it is correct.",
    )

    await conversation.say(CORRECT)
    assert statuses(conversation, "commit_record") == ["saved"]
    await conversation.say("No, not right now, thank you.")

    await conversation.judge_reply(
        judge, "Says 'You're all set, Jane.' followed by a short, warm closing line."
    )
    assert {"reason": "completed"} in conversation.calls("end_call")
    (patient,) = await conversation.services.patients.find_by_phone("5125550100")
    assert (patient.last_name, patient.state, patient.zip_code) == ("Davis", "TX", "78701")


async def test_e2_accepted_optional_details_are_read_back_and_saved(conversation: Conversation):
    for line in JANE:
        await conversation.say(line)
    await answer_checks(conversation)
    await conversation.say(
        "Yes: my insurance is Aetna, member ID W123456789, and my emergency contact "
        "is John Davis at 512-555-0102."
    )
    for _ in range(2):
        if ready(conversation):
            break
        await conversation.say("That's all.")

    assert ready(conversation), "never reached the read-back"
    groups = {group["group"] for group in ready(conversation)[-1]["readback"]}
    assert {"insurance", "emergency_contact"} <= groups
    await conversation.say(CORRECT)
    assert statuses(conversation, "commit_record") == ["saved"]
    (patient,) = await conversation.services.patients.find_by_phone("5125550100")
    assert (patient.insurance_provider, patient.insurance_member_id) == ("Aetna", "W123456789")
    assert patient.emergency_contact_phone == "5125550102"


async def test_e3_a_spelled_correction_changes_only_the_last_name(
    conversation: Conversation, judge: llm.LLM
):
    lines = (JANE[0].replace("Davis, that's D-A-V-I-S", "Davies, that's D-A-V-I-E-S"), *JANE[1:])
    await give_details(conversation, lines)

    await conversation.say("Actually, my last name is spelled D-A-V-I-S, not D-A-V-I-E-S.")

    assert conversation.calls("prepare_record")[-1]["fields"]["last_name"].casefold() == "davis"
    await conversation.judge_reply(  # reading everything back again is fine (the human's call)
        judge,
        "Reads back the corrected last name, Davis, spelled D-A-V-I-S, and asks whether it's "
        "right. Reading the other details back again as well is fine.",
    )
    await conversation.say("Yes, that's right.")
    assert statuses(conversation, "commit_record") == ["saved"]
    (patient,) = await conversation.services.patients.find_by_phone("5125550100")
    assert patient.last_name == "Davis"


async def test_e4_invalid_answers_are_asked_again_then_the_caller_starts_over(
    conversation: Conversation, judge: llm.LLM
):
    await conversation.say("I'm Jane Davis, D-A-V-I-S, and I was born January 1st, 2031.")
    await conversation.judge_reply(
        judge,
        "Says the date of birth can't be in the future and asks for it again (the whole date "
        "or just the year). It may repeat the caller's name back, but asks for nothing else.",
    )

    await conversation.say("Sorry, March 5th, 1990. I'm female, and my number is 555-0100.")
    await conversation.judge_reply(
        judge,
        "Says the phone number seems incomplete (a US number has ten digits, with the area "
        "code) and asks for the phone number again, and only for that.",
    )
    assert "found" not in statuses(conversation, "lookup_patient_by_phone")

    await conversation.say("Hmm, actually, can we start over?")
    assert statuses(conversation, "start_over") == ["cleared"]
    await conversation.judge_reply(
        judge, "Says no problem, they'll start fresh, and asks for the caller's name."
    )
    assert not conversation.calls("commit_record")


async def test_e5_a_known_number_leads_to_an_update(conversation: Conversation, judge: llm.LLM):
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


async def test_e6_an_appointment_after_saving(conversation: Conversation, judge: llm.LLM):
    await give_details(conversation, JANE)
    await conversation.say(CORRECT)

    await conversation.say(
        "Yes, I'd like an appointment. Any weekday morning, the earliest you have."
    )
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


async def test_e7_disclosure_and_emergency(conversation: Conversation, judge: llm.LLM):
    await conversation.say("Wait, am I talking to a real person?")
    await conversation.judge_reply(
        judge, "Says it is the clinic's virtual assistant, not a person."
    )

    await conversation.say("Also I'm having really bad chest pain right now.")

    await conversation.judge_reply(judge, "Tells the caller to hang up and call 911 right now.")
    assert {"reason": "emergency"} in conversation.calls("end_call")
