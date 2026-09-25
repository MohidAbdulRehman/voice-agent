"""What the agent remembers during one call: ``session.userdata`` (agent.md §3)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from intake.core.models import Channel
from intake.core.speech import SpokenLanguage

Mode = Literal["create", "update"]


@dataclass(frozen=True)
class Draft:
    """The latest prepared record; only this one can be committed."""

    draft_id: str  # opaque, e.g. "d-7f3a"
    action: Mode
    # Normalized, in input form (dates as MM/DD/YYYY); for an update, only the changes.
    payload: dict[str, Any]
    patient_id: UUID | None = None  # the patient an update changes


@dataclass(frozen=True)
class SlotRef:
    """An appointment slot offered to the caller, behind an opaque ``slot_id``."""

    doctor_id: UUID
    doctor_name: str
    starts_at: datetime


@dataclass
class CallState:
    """Per-call state. The tools read and change it; none of it is spoken as is."""

    call_id: UUID  # the calls row created when the session starts
    channel: Channel
    caller_number: str | None  # 10 digits if a US number, else as the carrier sent it
    language: SpokenLanguage = "English"
    mode: Mode = "create"
    target_patient_id: UUID | None = None  # the patient an update changes
    duplicate_acknowledged: bool = False  # the caller chose a new record despite a match
    draft: Draft | None = None
    committed_patient_id: UUID | None = None
    commit_failures: int = 0
    offered_slots: dict[str, SlotRef] = field(default_factory=dict)
    appointment_id: UUID | None = None
    silence_prompts: int = 0
    # Beyond agent.md §3:
    matched_patient_id: UUID | None = None  # the most recently updated match of the last lookup
    saved: tuple[str, dict[str, Any]] | None = None  # (draft_id, result) of the successful commit
    end_reason: str | None = None  # why the call is ending, for the shutdown handler
