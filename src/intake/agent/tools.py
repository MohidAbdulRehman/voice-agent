"""The intake agent and its nine tools (docs/specs/agent.md §4).

Every tool follows the same rules:
- It returns facts, a dict with a ``status`` key, never sentences. The LLM phrases
  everything, and read-backs come verbatim from ``intake.core.speech``.
- It never raises to the LLM: an unexpected error becomes ``{"status": "system_error"}``
  and is logged with its stack trace.
- It never puts an internal id in its result.

The tools call the ``intake.core`` services in-process, never the REST API.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
from livekit.agents import Agent, RunContext, function_tool
from livekit.agents.llm import ToolResult
from pydantic import BaseModel, Field

from intake.agent.state import CallState, Draft, Mode, SlotRef
from intake.config import Settings
from intake.core.models import (
    DuplicateSourceCall,
    FieldError,
    NotFound,
    Patient,
    PersistenceError,
    Slot,
    SlotTaken,
    ValidationFailed,
)
from intake.core.services import Services, utc_now
from intake.core.speech import (
    ReadbackGroup,
    SpokenLanguage,
    readback,
    say_booking,
    say_slot,
    update_readback,
)
from intake.core.validation import Invalid, as_input, clinic_today, parse_date

log = structlog.stdlib.get_logger("intake.agent")

RETRY_BACKOFF_SECONDS = 0.25  # between the two write attempts inside one commit_record call
MAX_COMMIT_FAILURES = 2  # failed commit_record calls before the call is marked failed
MAX_SLOTS = 3
SLOT_SEARCH_DAYS = 14
AFTERNOON_STARTS_AT = 12  # hour at the clinic

TimeOfDay = Literal["morning", "afternoon", "any"]
EndReason = Literal["completed", "caller_request", "no_response", "emergency", "out_of_scope"]


class Facts(dict[str, Any]):
    """A tool result: a plain dict to code, JSON to the LLM (which is sent ``str(result)``)."""

    def __str__(self) -> str:
        return json.dumps(self, ensure_ascii=False)


class PatientFields(BaseModel):
    """Patient details exactly as the caller gave them; leave out anything not given."""

    first_name: str | None = None
    last_name: str | None = Field(None, description="Spelled letters joined: D-A-V-I-S is Davis")
    date_of_birth: str | None = Field(None, description="MM/DD/YYYY")
    sex: str | None = Field(None, description="Male, Female, Other, or Decline to Answer")
    phone_number: str | None = Field(None, description="10-digit US number, any format")
    email: str | None = None
    address_line_1: str | None = Field(None, description="Street number and name")
    address_line_2: str | None = Field(None, description="Apartment, suite, or unit")
    city: str | None = None
    state: str | None = Field(None, description="US state, as a two-letter code or full name")
    zip_code: str | None = Field(None, description="5 digits, or ZIP+4")
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = Field(None, description="For example English or Spanish")
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


@dataclass(frozen=True)
class AgentDeps:
    """What the tools need besides the call state."""

    services: Services
    settings: Settings
    switch_voice: Callable[[SpokenLanguage], None]  # point the TTS at a language's voice
    clock: Callable[[], datetime] = utc_now


class IntakeAgent(Agent):
    """Maya: one agent with the same nine tools for the whole call."""

    def __init__(self, *, instructions: str, deps: AgentDeps) -> None:
        super().__init__(instructions=instructions)
        self._deps = deps
        self._services = deps.services
        self._zone = deps.settings.clinic_zone

    @function_tool()
    async def lookup_patient_by_phone(
        self, context: RunContext[CallState], phone_number: str
    ) -> Facts:
        """Check whether this phone number already belongs to a registered patient.

        Call it as soon as the caller gives their phone number.

        Args:
            phone_number: The number the caller gave, in any format, e.g. 512-555-0100.
        """
        return await self._run(
            "lookup_patient_by_phone", self._lookup(context.userdata, phone_number)
        )

    @function_tool()
    async def prepare_record(
        self, context: RunContext[CallState], action: Mode, fields: PatientFields
    ) -> Facts:
        """Check the details and get the exact read-back text. Saves nothing.

        Use action create for a new patient, with everything collected so far.
        Use action update only after acknowledge_duplicate with update, with only the
        changed details. Call it again after any correction: each call replaces the
        previous draft_id.

        Args:
            action: create or update.
            fields: The patient details, as the caller gave them.
        """
        return await self._run("prepare_record", self._prepare(context.userdata, action, fields))

    @function_tool()
    async def acknowledge_duplicate(
        self, context: RunContext[CallState], choice: Literal["update", "create_new"]
    ) -> Facts:
        """Record the caller's answer after a phone number matched an existing patient.

        Args:
            choice: update to change the existing record, create_new for a new patient
                (for example a family member who shares the number).
        """
        return await self._run("acknowledge_duplicate", self._acknowledge(context.userdata, choice))

    @function_tool()
    async def commit_record(
        self, context: RunContext[CallState], draft_id: str, caller_confirmed: bool
    ) -> Facts:
        """Save the prepared record. Only after the caller clearly said the read-back is correct.

        Args:
            draft_id: The draft_id from the latest prepare_record result.
            caller_confirmed: True only if the caller confirmed every detail.
        """
        context.disallow_interruptions()
        return await self._run(
            "commit_record", self._commit(context.userdata, draft_id, caller_confirmed)
        )

    @function_tool()
    async def start_over(self, context: RunContext[CallState]) -> Facts:
        """Forget the details collected so far, when the caller asks to start over."""
        return await self._run("start_over", self._start_over(context.userdata))

    @function_tool()
    async def find_appointment_slots(
        self,
        context: RunContext[CallState],
        preferred_date: str | None = None,
        time_of_day: TimeOfDay = "any",
    ) -> Facts:
        """Find up to three open appointment times in the next two weeks, after a successful save.

        Args:
            preferred_date: The day the caller would like, as MM/DD/YYYY, if any.
            time_of_day: morning, afternoon, or any.
        """
        return await self._run(
            "find_appointment_slots",
            self._find_slots(context.userdata, preferred_date, time_of_day),
        )

    @function_tool()
    async def book_appointment(self, context: RunContext[CallState], slot_id: str) -> Facts:
        """Book one of the offered appointment times.

        Args:
            slot_id: The slot_id of the time the caller chose.
        """
        context.disallow_interruptions()
        return await self._run("book_appointment", self._book(context.userdata, slot_id))

    @function_tool()
    async def set_language(
        self, context: RunContext[CallState], language: Literal["English", "Spanish"]
    ) -> Facts:
        """Switch the voice and the read-backs to English or Spanish.

        Args:
            language: The language the caller wants to speak.
        """
        return await self._run("set_language", self._set_language(context.userdata, language))

    @function_tool()
    async def end_call(self, context: RunContext[CallState], reason: EndReason) -> ToolResult:
        """Hang up. Say your goodbye first: the call ends once it has been spoken.

        Args:
            reason: completed when everything is done; caller_request when they want to go;
                no_response when they stopped answering; emergency after the 911 advice;
                out_of_scope when they only needed something you can't help with.
        """
        facts = await self._run("end_call", self._end(context, reason))
        return ToolResult(facts, reply_required=facts["status"] != "ending")

    # --- implementation ----------------------------------------------------------

    async def _run(self, tool: str, work: Awaitable[dict[str, Any]]) -> Facts:
        started = time.perf_counter()
        try:
            result = Facts(await work)
        except Exception:
            log.exception("tool.failed", tool=tool)
            result = Facts(status="system_error")
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        log.info("tool.called", tool=tool, status=result["status"], latency_ms=latency_ms)
        return result

    async def _lookup(self, state: CallState, phone_number: str) -> dict[str, Any]:
        try:
            matches = await self._services.patients.find_by_phone(phone_number)
        except ValidationFailed as failed:
            return {"status": "invalid", "errors": _errors(failed.errors)}
        if not matches:
            state.matched_patient_id = None
            return {"status": "not_found"}
        state.matched_patient_id = matches[0].patient_id  # the most recently updated
        return {"status": "found", "patient": _name(matches[0]), "match_count": len(matches)}

    async def _prepare(
        self, state: CallState, action: Mode, fields: PatientFields
    ) -> dict[str, Any]:
        state.draft = None  # whatever happens, an earlier draft can no longer be committed
        data = fields.model_dump(exclude_none=True)
        if action == "create":
            return await self._prepare_create(state, data)
        return await self._prepare_update(state, data)

    async def _prepare_create(self, state: CallState, data: dict[str, Any]) -> dict[str, Any]:
        if state.committed_patient_id is not None:
            return _refused(
                "already_registered",
                "This caller was already saved on this call; use action update for changes.",
            )
        if state.mode == "update":
            return _refused(
                "updating_existing_record",
                "The caller chose to update their existing record; use action update.",
            )
        patients = self._services.patients
        try:
            patient = patients.validate_new(data, accept_state_names=True)
        except ValidationFailed as failed:
            await self._keep_payload(state, data)
            missing = [error.field for error in failed.errors if error.code == "required"]
            others = [error for error in failed.errors if error.code != "required"]
            if missing:
                return {"status": "incomplete", "missing": missing, "errors": _errors(others)}
            return {"status": "invalid", "errors": _errors(others)}
        matches = await patients.find_by_phone(patient.phone_number)
        if matches and not state.duplicate_acknowledged:
            state.matched_patient_id = matches[0].patient_id
            return {"status": "duplicate", "patient": _name(matches[0])}
        draft = self._new_draft(state, "create", as_input(patient))
        await self._keep_payload(state, draft.payload)
        groups = readback(patient, state.language, language_given="preferred_language" in data)
        return {"status": "ok", "draft_id": draft.draft_id, "readback": _groups(groups)}

    async def _prepare_update(self, state: CallState, data: dict[str, Any]) -> dict[str, Any]:
        if state.mode != "update" or state.target_patient_id is None:
            return _refused(
                "no_patient_to_update",
                "Update only after the caller chose to update their existing record.",
            )
        try:
            changes = self._services.patients.validate_changes(data, accept_state_names=True)
        except ValidationFailed as failed:
            return {"status": "invalid", "errors": _errors(failed.errors)}
        draft = self._new_draft(state, "update", as_input(changes), state.target_patient_id)
        await self._keep_payload(state, draft.payload)
        groups = update_readback(changes, state.language)
        return {"status": "ok", "draft_id": draft.draft_id, "readback": _groups(groups)}

    def _new_draft(
        self,
        state: CallState,
        action: Mode,
        payload: dict[str, Any],
        patient_id: UUID | None = None,
    ) -> Draft:
        taken = {state.saved[0]} if state.saved else set()
        draft_id = f"d-{uuid4().hex[:4]}"
        while draft_id in taken:
            draft_id = f"d-{uuid4().hex[:4]}"
        state.draft = Draft(
            draft_id=draft_id, action=action, payload=payload, patient_id=patient_id
        )
        return state.draft

    async def _keep_payload(self, state: CallState, payload: dict[str, Any]) -> None:
        """Keep the latest data on the calls row, so an unfinished call leaves a trace."""
        try:
            await self._services.calls.save_payload(state.call_id, payload)
        except Exception:
            log.warning("call.payload_not_saved", exc_info=True)

    async def _acknowledge(
        self, state: CallState, choice: Literal["update", "create_new"]
    ) -> dict[str, Any]:
        state.draft = None
        if choice == "update":
            if state.matched_patient_id is None:
                return {"status": "not_found"}
            state.mode, state.target_patient_id = "update", state.matched_patient_id
            return {"status": "ok", "mode": "update"}
        state.mode, state.target_patient_id = "create", None
        state.duplicate_acknowledged = True
        return {"status": "ok", "mode": "create"}

    async def _commit(
        self, state: CallState, draft_id: str, caller_confirmed: bool
    ) -> dict[str, Any]:
        if not caller_confirmed:
            return {"status": "not_confirmed"}
        if state.saved is not None and state.saved[0] == draft_id:
            return state.saved[1]  # the same draft again: same answer, nothing written twice
        draft = state.draft
        if draft is None or draft.draft_id != draft_id:
            return {"status": "stale_draft"}
        if state.commit_failures >= MAX_COMMIT_FAILURES:
            return {"status": "system_error", "retryable": False}
        try:
            patient = await self._write(state, draft)
        except ValidationFailed as failed:
            return {"status": "invalid", "errors": _errors(failed.errors)}
        except NotFound:
            return {"status": "not_found"}
        except PersistenceError as error:
            return await self._failed(state, draft, error)
        state.committed_patient_id = patient.patient_id
        # Later corrections on this call update the saved record.
        state.mode, state.target_patient_id = "update", patient.patient_id
        result = {"status": "saved", "action": draft.action, "first_name": patient.first_name}
        state.saved = (draft.draft_id, result)
        log.info(
            "registration.committed",
            payload=as_input(patient),
            action=draft.action,
            patient_id=str(patient.patient_id),
        )
        return result

    async def _write(self, state: CallState, draft: Draft) -> Patient:
        """Write the draft, retrying once after a short pause if the database fails."""
        try:
            return await self._write_once(state, draft)
        except PersistenceError:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            return await self._write_once(state, draft)

    async def _write_once(self, state: CallState, draft: Draft) -> Patient:
        patients = self._services.patients
        if draft.action == "create":
            try:
                return await patients.create(
                    draft.payload, call_id=state.call_id, accept_state_names=True
                )
            except DuplicateSourceCall:
                # The database says this call already created its patient: report that one.
                call = await self._services.calls.get(state.call_id)
                if call.patient_id is None:
                    raise
                return await patients.get(call.patient_id)
        if draft.patient_id is None:
            raise NotFound("patient")
        # A correction to the patient this call registered keeps the call "registered".
        link = None if draft.patient_id == state.committed_patient_id else state.call_id
        return await patients.update(
            draft.patient_id, draft.payload, call_id=link, accept_state_names=True
        )

    async def _failed(
        self, state: CallState, draft: Draft, error: PersistenceError
    ) -> dict[str, Any]:
        state.commit_failures += 1
        if state.commit_failures < MAX_COMMIT_FAILURES:
            return {"status": "system_error", "retryable": True}
        # The payload is logged in full so staff can re-enter it, even if marking the call fails.
        log.error(
            "registration.failed",
            payload=draft.payload,
            action=draft.action,
            error=type(error).__name__,
        )
        try:
            await self._services.calls.mark_failed(state.call_id)
        except Exception:
            log.exception("call.not_marked_failed")
        return {"status": "system_error", "retryable": False}

    async def _start_over(self, state: CallState) -> dict[str, Any]:
        state.draft = None
        state.mode, state.target_patient_id = "create", None
        state.duplicate_acknowledged = False
        state.matched_patient_id = None
        state.offered_slots.clear()
        return {"status": "cleared"}

    async def _find_slots(
        self, state: CallState, preferred_date: str | None, time_of_day: TimeOfDay
    ) -> dict[str, Any]:
        if state.committed_patient_id is None:
            return {"status": "not_registered"}
        wanted = None
        if preferred_date:
            try:
                wanted = parse_date(preferred_date.strip())
            except Invalid as problem:
                error = FieldError(
                    field="preferred_date",
                    code=problem.code,
                    message=f"Preferred date {problem.message}",
                )
                return {"status": "invalid", "errors": _errors([error])}
        slots = await self._open_slots(state, time_of_day)
        chosen = [s for s in slots if wanted is None or self._day(s) == wanted]
        if not chosen:
            fallback = slots or await self._open_slots(state, "any")
            return {"status": "none", "next_available": self._offer(state, fallback)}
        return {"status": "ok", "slots": self._offer(state, chosen)}

    async def _open_slots(self, state: CallState, time_of_day: TimeOfDay) -> list[Slot]:
        """Open slots in the search window, Spanish-speaking doctors first for Spanish callers."""
        scheduling = self._services.scheduling
        today = clinic_today(self._deps.clock(), self._zone)
        slots = await scheduling.open_slots(start=today, days=SLOT_SEARCH_DAYS)
        if time_of_day != "any":
            afternoon = time_of_day == "afternoon"
            slots = [
                s
                for s in slots
                if (s.starts_at.astimezone(self._zone).hour >= AFTERNOON_STARTS_AT) == afternoon
            ]
        if state.language == "Spanish":
            speakers = {d.doctor_id for d in await scheduling.doctors() if "Spanish" in d.languages}
            slots.sort(
                key=lambda slot: slot.doctor_id not in speakers
            )  # stable: still earliest first
        return slots

    def _day(self, slot: Slot) -> date:
        return slot.starts_at.astimezone(self._zone).date()

    def _offer(self, state: CallState, slots: list[Slot]) -> list[dict[str, str]]:
        offered = []
        for slot in slots[:MAX_SLOTS]:
            slot_id = f"s{len(state.offered_slots) + 1}"
            state.offered_slots[slot_id] = SlotRef(slot.doctor_id, slot.doctor_name, slot.starts_at)
            spoken = say_slot(slot.starts_at, self._zone, state.language)
            offered.append({"slot_id": slot_id, "doctor": slot.doctor_name, "spoken": spoken})
        return offered

    async def _book(self, state: CallState, slot_id: str) -> dict[str, Any]:
        if state.committed_patient_id is None:
            return {"status": "not_registered"}
        slot = state.offered_slots.get(slot_id)
        if slot is None:
            return {"status": "unknown_slot"}
        try:
            appointment = await self._services.scheduling.book(
                patient_id=state.committed_patient_id,
                doctor_id=slot.doctor_id,
                starts_at=slot.starts_at,
                booked_via="voice_agent",
                call_id=state.call_id,
            )
        except SlotTaken:
            alternatives = self._offer(state, await self._open_slots(state, "any"))
            return {"status": "slot_taken", "alternatives": alternatives}
        state.appointment_id = appointment.appointment_id
        spoken = say_booking(
            appointment.starts_at, appointment.doctor_name, self._zone, state.language
        )
        return {"status": "booked", "spoken": spoken}

    async def _set_language(
        self, state: CallState, language: Literal["English", "Spanish"]
    ) -> dict[str, Any]:
        state.language = language
        self._deps.switch_voice(language)
        try:
            await self._services.calls.set_language(state.call_id, language)
        except Exception:
            log.warning("call.language_not_saved", exc_info=True)
        return {"status": "ok", "language": language}

    async def _end(self, context: RunContext[CallState], reason: EndReason) -> dict[str, Any]:
        state = context.userdata
        state.end_reason = state.end_reason or reason  # a reason set earlier (time limit) wins
        await context.wait_for_playout()  # let the goodbye finish
        context.session.shutdown(drain=True)
        return {"status": "ending"}


def _errors(errors: list[FieldError]) -> list[dict[str, Any]]:
    return [error.model_dump() for error in errors]


def _refused(code: str, message: str) -> dict[str, Any]:
    return {"status": "invalid", "errors": [{"field": None, "code": code, "message": message}]}


def _name(patient: Patient) -> dict[str, str]:
    return {"first_name": patient.first_name, "last_name": patient.last_name}


def _groups(groups: list[ReadbackGroup]) -> list[dict[str, str]]:
    return [group.model_dump() for group in groups]
