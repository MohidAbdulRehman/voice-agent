"""Normalization and validation rules for patient data (docs/specs/data-model.md).

The REST API and the voice agent both call this module, so there is exactly one
set of rules. db/migrations/0001_init.sql enforces the same rules as the last
line of defence; tests/db/test_parity.py checks that the two agree.
"""

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from email_validator import EmailNotValidError, validate_email

from intake.core.models import FieldError, PatientCreate, PatientUpdate, Sex, ValidationFailed
from intake.core.states import STATE_NAMES, state_code_for

READ_ONLY_FIELDS = frozenset({"patient_id", "created_at", "updated_at", "deleted_at"})
OLDEST_DATE_OF_BIRTH = date(1900, 1, 1)

LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "date_of_birth": "Date of birth",
    "sex": "Sex",
    "phone_number": "Phone number",
    "email": "Email",
    "address_line_1": "Address line 1",
    "address_line_2": "Address line 2",
    "city": "City",
    "state": "State",
    "zip_code": "ZIP code",
    "insurance_provider": "Insurance provider",
    "insurance_member_id": "Insurance member ID",
    "preferred_language": "Preferred language",
    "emergency_contact_name": "Emergency contact name",
    "emergency_contact_phone": "Emergency contact phone",
}

_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_DATE = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_ZIP = re.compile(r"[0-9]{5}(-[0-9]{4})?")
_MEMBER_ID = re.compile(r"[A-Z0-9]{1,30}")
_SEX_BY_KEY = {sex.value.casefold(): sex for sex in Sex}
_LANGUAGE_ALIASES = {
    "english": "English",
    "inglés": "English",
    "ingles": "English",
    "spanish": "Spanish",
    "español": "Spanish",
    "espanol": "Spanish",
}
_CONTACT_NAME_PUNCTUATION = frozenset(" -'.")
_CURLY_APOSTROPHE = "\N{RIGHT SINGLE QUOTATION MARK}"  # as typed by phones; stored as '
# Optional, but never null: it defaults to English (send "English" to reset it).
_NOT_CLEARABLE = frozenset({"preferred_language"})


class Invalid(Exception):
    """A single field broke a rule. ``message`` completes a sentence that starts with the label."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidationContext:
    """What some rules need besides the value itself."""

    today: date  # "today" in the clinic's time zone
    accept_state_names: bool = False  # the voice agent may pass "Texas" instead of "TX"


def clinic_today(now: datetime, zone: ZoneInfo) -> date:
    """Return the calendar date at ``now`` in the clinic's time zone."""
    return now.astimezone(zone).date()


def normalize_text(value: str) -> str:
    """Apply NFC, trim, and collapse whitespace runs to one space.

    Raises:
        Invalid: ``invalid_characters`` if a control character remains.
    """
    text = " ".join(unicodedata.normalize("NFC", value).split())
    if _CONTROL_CHARACTER.search(text):
        raise Invalid("invalid_characters", "contains control characters.")
    return text


def parse_date(text: str) -> date:
    """Parse strict ``MM/DD/YYYY`` (zero-padded) into a real calendar date.

    Raises:
        Invalid: ``invalid_format`` or ``not_a_real_date``.
    """
    match = _DATE.fullmatch(text)
    if match is None:
        raise Invalid("invalid_format", "must be in MM/DD/YYYY format.")
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        raise Invalid("not_a_real_date", "isn't a real calendar date.") from None


def normalize_phone(text: str) -> str:
    """Reduce a US phone number in any format to 10 digits, e.g. ``(512) 555-0100`` → ``5125550100``.

    Raises:
        Invalid: ``invalid_phone`` or ``invalid_area_code``.
    """
    digits = "".join(char for char in text if char in "0123456789")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise Invalid("invalid_phone", "must be a 10-digit US phone number.")
    if digits[0] in "01":
        raise Invalid("invalid_area_code", "has an invalid area code (it can't start with 0 or 1).")
    if digits[3] in "01":
        raise Invalid(
            "invalid_phone", "isn't a valid US number (the exchange can't start with 0 or 1)."
        )
    return digits


def _max_length(limit: int) -> Callable[[str, ValidationContext], str]:
    def check(text: str, _ctx: ValidationContext) -> str:
        if len(text) > limit:
            raise Invalid("too_long", f"must be at most {limit} characters.")
        return text

    return check


def _capitalize_segments(name: str) -> str:
    return re.sub(r"[^'-]+", lambda segment: segment.group().capitalize(), name)


def _clean_name(text: str, _ctx: ValidationContext) -> str:
    name = text.replace(_CURLY_APOSTROPHE, "'")
    if name.islower() or name.isupper():
        name = _capitalize_segments(name)
    if len(name) > 50:
        raise Invalid("too_long", "must be at most 50 characters.")
    # Letter runs joined by single hyphens or apostrophes: "-Jane", "Jane--Doe" and "Van Buren" fail.
    if not all(part.isalpha() for part in re.split(r"['-]", name)):
        raise Invalid(
            "invalid_characters",
            "can only contain letters, with a hyphen or apostrophe between letters.",
        )
    return name


def _clean_date_of_birth(text: str, ctx: ValidationContext) -> date:
    born = parse_date(text)
    if born > ctx.today:
        raise Invalid("in_future", "can't be in the future.")
    if born < OLDEST_DATE_OF_BIRTH:
        raise Invalid("too_old", "must be on or after 01/01/1900.")
    return born


def _clean_sex(text: str, _ctx: ValidationContext) -> Sex:
    try:
        return _SEX_BY_KEY[text.casefold()]
    except KeyError:
        raise Invalid(
            "invalid_value", "must be one of Male, Female, Other, or Decline to Answer."
        ) from None


def _clean_phone(text: str, _ctx: ValidationContext) -> str:
    return normalize_phone(text)


def _clean_email(text: str, _ctx: ValidationContext) -> str:
    try:
        email = validate_email(text, check_deliverability=False).normalized
    except EmailNotValidError:
        raise Invalid("invalid_email", "isn't a valid email address.") from None
    if len(email) > 254:
        raise Invalid("invalid_email", "must be at most 254 characters.")
    return email


def _clean_state(text: str, ctx: ValidationContext) -> str:
    code = text.upper()
    if code in STATE_NAMES:
        return code
    named = state_code_for(text) if ctx.accept_state_names else None
    if named is None:
        raise Invalid("invalid_state", "must be a US state or territory code, like TX.")
    return named


def _clean_zip(text: str, _ctx: ValidationContext) -> str:
    zip_code = text.replace(" ", "")
    if len(zip_code) == 9 and zip_code.isascii() and zip_code.isdigit():
        zip_code = f"{zip_code[:5]}-{zip_code[5:]}"
    if not _ZIP.fullmatch(zip_code):
        raise Invalid("invalid_zip", "must be 5 digits or ZIP+4, like 12345-6789.")
    return zip_code


def _clean_member_id(text: str, _ctx: ValidationContext) -> str:
    member_id = text.replace(" ", "").replace("-", "").upper()
    if not _MEMBER_ID.fullmatch(member_id):
        raise Invalid("invalid_member_id", "must be 1 to 30 letters or digits.")
    return member_id


def _clean_language(text: str, _ctx: ValidationContext) -> str:
    language = _LANGUAGE_ALIASES.get(text.casefold(), text.title())
    if len(language) > 50:
        raise Invalid("too_long", "must be at most 50 characters.")
    return language


def _clean_contact_name(text: str, _ctx: ValidationContext) -> str:
    name = text.replace(_CURLY_APOSTROPHE, "'")
    if len(name) > 100:
        raise Invalid("too_long", "must be at most 100 characters.")
    if not any(char.isalpha() for char in name) or not all(
        char.isalpha() or char in _CONTACT_NAME_PUNCTUATION for char in name
    ):
        raise Invalid(
            "invalid_characters",
            "can only contain letters, spaces, hyphens, apostrophes and periods.",
        )
    return name


@dataclass(frozen=True)
class _Rule:
    clean: Callable[[str, ValidationContext], object]
    required: bool = False


# In data-model order, which is also the order errors are reported in.
_RULES: dict[str, _Rule] = {
    "first_name": _Rule(_clean_name, required=True),
    "last_name": _Rule(_clean_name, required=True),
    "date_of_birth": _Rule(_clean_date_of_birth, required=True),
    "sex": _Rule(_clean_sex, required=True),
    "phone_number": _Rule(_clean_phone, required=True),
    "email": _Rule(_clean_email),
    "address_line_1": _Rule(_max_length(200), required=True),
    "address_line_2": _Rule(_max_length(100)),
    "city": _Rule(_max_length(100), required=True),
    "state": _Rule(_clean_state, required=True),
    "zip_code": _Rule(_clean_zip, required=True),
    "insurance_provider": _Rule(_max_length(100)),
    "insurance_member_id": _Rule(_clean_member_id),
    "preferred_language": _Rule(_clean_language),
    "emergency_contact_name": _Rule(_clean_contact_name),
    "emergency_contact_phone": _Rule(_clean_phone),
}


def _error(field: str, problem: Invalid) -> FieldError:
    return FieldError(field=field, code=problem.code, message=f"{LABELS[field]} {problem.message}")


def _clean(raw: object, rule: _Rule, ctx: ValidationContext) -> object | None:
    """Return the cleaned value, or ``None`` when the field is missing or blank."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise Invalid("invalid_type", "must be a string.")
    text = normalize_text(raw)
    return rule.clean(text, ctx) if text else None


def _unexpected_fields(data: Mapping[str, object]) -> list[FieldError]:
    errors = []
    for field in data:
        if field in READ_ONLY_FIELDS:
            errors.append(
                FieldError(field=field, code="read_only", message=f"{field} is read-only.")
            )
        elif field not in _RULES:
            errors.append(
                FieldError(
                    field=field, code="unknown_field", message=f"{field} isn't a patient field."
                )
            )
    return errors


def clean_field(field: str, raw: object, ctx: ValidationContext) -> object | None:
    """Normalize and validate one field on its own, e.g. a phone number to look up.

    Returns:
        The cleaned value, or None for a blank optional field.

    Raises:
        ValidationFailed: with the field's error; a blank required field is ``required``.
    """
    rule = _RULES[field]
    try:
        value = _clean(raw, rule, ctx)
    except Invalid as problem:
        raise ValidationFailed([_error(field, problem)]) from None
    if value is None and rule.required:
        raise ValidationFailed([_error(field, Invalid("required", "is required."))])
    return value


def validate_new_patient(data: Mapping[str, object], ctx: ValidationContext) -> PatientCreate:
    """Normalize and validate a complete new patient.

    Raises:
        ValidationFailed: listing every problem, unexpected fields first, then in field order.
    """
    errors = _unexpected_fields(data)
    values: dict[str, object] = {}
    for field, rule in _RULES.items():
        try:
            value = _clean(data.get(field), rule, ctx)
        except Invalid as problem:
            errors.append(_error(field, problem))
            continue
        if value is not None:
            values[field] = value
        elif rule.required:
            errors.append(_error(field, Invalid("required", "is required.")))
    if errors:
        raise ValidationFailed(errors)
    return PatientCreate.model_validate(values)


def validate_patient_changes(data: Mapping[str, object], ctx: ValidationContext) -> PatientUpdate:
    """Normalize and validate a partial update; only the fields present change.

    ``None`` or a blank string clears an optional field. Required fields and
    ``preferred_language`` can't be cleared.

    Raises:
        ValidationFailed: listing every problem, or ``empty_update`` when nothing would change.
    """
    errors = _unexpected_fields(data)
    changes: dict[str, object] = {}
    for field, rule in _RULES.items():
        if field not in data:
            continue
        try:
            value = _clean(data[field], rule, ctx)
        except Invalid as problem:
            errors.append(_error(field, problem))
            continue
        if value is None and (rule.required or field in _NOT_CLEARABLE):
            errors.append(_error(field, Invalid("required", "can't be empty.")))
        else:
            changes[field] = value
    if not errors and not changes:
        errors.append(
            FieldError(
                field=None, code="empty_update", message="Provide at least one field to change."
            )
        )
    if errors:
        raise ValidationFailed(errors)
    return PatientUpdate.model_validate(changes)


def as_input(patient: PatientCreate | PatientUpdate) -> dict[str, object]:
    """Render validated data back into input form (dates as ``MM/DD/YYYY``), JSON-ready.

    Used for ``calls.final_payload`` and to re-validate a draft when it's committed.
    """
    values = patient.model_dump(mode="json", exclude_unset=isinstance(patient, PatientUpdate))
    born = getattr(patient, "date_of_birth", None)
    if "date_of_birth" in values and born is not None:
        values["date_of_birth"] = born.strftime("%m/%d/%Y")
    return values
