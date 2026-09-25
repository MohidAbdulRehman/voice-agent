# Data model & validation rules

Two layers enforce these rules, and they must agree:

1. **`db/migrations/0001_init.sql`**: database constraints, the last line of defence (already written and tested on Postgres 16).
2. **`src/intake/core/validation.py`**: normalizes input and returns friendly, field-specific errors. Both the REST API and the voice agent call it, so there is exactly one set of rules.

A parity test (see `testing.md`) inserts each invalid example directly into the database, bypassing Python, and asserts the constraint rejects it.

## Normalization (runs before validation, in this order)

These apply to every string field:
- Apply Unicode NFC.
- Strip leading and trailing whitespace.
- Collapse internal whitespace runs to a single space.
- Reject control characters (U+0000–U+001F, U+007F) with the error code `invalid_characters`.
- Empty strings on optional fields become `null`.

## Field rules

| Field | Req | Field-specific normalization | Rule | Error codes |
|---|---|---|---|---|
| `first_name`, `last_name` | ✔ | `’` → `'`. If the value is all-lowercase or all-uppercase, capitalize each segment split on `-`/`'` (`o'brien` → `O'Brien`). Otherwise keep the caller's casing. | 1–50 chars. Letters only (Unicode letters: `str.isalpha()`), plus `-` and `'` *between* letters. No spaces, digits or other punctuation (assessment spec). | `required`, `too_long`, `invalid_characters` |
| `date_of_birth` | ✔ | none | Strict `MM/DD/YYYY` (zero-padded) on input. Must be a real calendar date, `>= 01/01/1900`, and not after **today in `CLINIC_TIMEZONE`**. Stored as `DATE`. | `required`, `invalid_format`, `not_a_real_date`, `in_future`, `too_old` |
| `sex` | ✔ | Case-insensitive match to canonical casing | One of `Male`, `Female`, `Other`, `Decline to Answer` | `required`, `invalid_value` |
| `phone_number` | ✔ | Keep digits only. Drop a leading `1` if 11 digits. | Exactly 10 digits. Area code and exchange must not start with 0 or 1 (US numbering rules). Stored as `5125550100`. | `required`, `invalid_phone`, `invalid_area_code` |
| `email` | | Lowercase the domain part | Syntax check via `email-validator` (`check_deliverability=False`), ≤ 254 chars | `invalid_email` |
| `address_line_1` | ✔ | none | 1–200 chars | `required`, `too_long` |
| `address_line_2` | | none | 1–100 chars | `too_long` |
| `city` | ✔ | none | 1–100 chars | `required`, `too_long` |
| `state` | ✔ | Uppercase. The **agent path only** also maps full names ("texas" → `TX`, "Puerto Rico" → `PR`). | 50 states + DC + AS, GU, MP, PR, VI | `required`, `invalid_state` |
| `zip_code` | ✔ | Remove spaces. `123456789` → `12345-6789`. | `^\d{5}(-\d{4})?$` | `required`, `invalid_zip` |
| `insurance_provider` | | none | 1–100 chars | `too_long` |
| `insurance_member_id` | | Remove spaces and `-`, uppercase | `^[A-Z0-9]{1,30}$` | `invalid_member_id` |
| `preferred_language` | | Map common forms: "español"/"spanish" → `Spanish`, "english"/"inglés" → `English`. Otherwise title-case. | 1–50 chars. **Default `English`** when omitted. | `too_long` |
| `emergency_contact_name` | | Same apostrophe handling as names | 1–100 chars. Letters, spaces, `-`, `'`, `.`; no digits. | `too_long`, `invalid_characters` |
| `emergency_contact_phone` | | Same as `phone_number` | Same as `phone_number` | `invalid_phone`, `invalid_area_code` |
| `patient_id`, `created_at`, `updated_at`, `deleted_at` | auto | none | **Read-only**. The API rejects them in request bodies with `read_only`. | `read_only` |

Documented decisions (these belong in the README's trade-offs section):
- **Names with spaces are rejected.** The assessment specifies alphabetic plus hyphens/apostrophes, so "Van Buren" and "Mary Ann" fail. The agent asks whether a hyphenated form is how they'd like it recorded; it never alters a name silently.
- **Accented letters are allowed.** They're alphabetic, and the Spanish bonus needs names like José and Núñez.
- **Phone numbers are not unique.** Families share numbers, so duplicate detection is a conversational check, not a constraint.
- **US territories are accepted** as valid state codes.

## Error object

Every validation error, in both the API and the agent tools, has this shape:

```json
{ "field": "date_of_birth", "code": "in_future", "message": "Date of birth can't be in the future." }
```

`message` is plain English for API clients and logs. The voice agent uses `code` plus `message` to re-prompt in the caller's language; it never reads `message` verbatim.

## Spoken forms (generated in `core/speech.py`, never by the LLM)

The read-back is generated in code, not by the LLM, so digits and spellings are always exact. Both languages are required.

| Field | English | Spanish |
|---|---|---|
| Name | `Jane Davis, that's D-A-V-I-S` | `Jane Davis, se escribe D-A-V-I-S` |
| Date of birth | `March 5th, 1990` | `5 de marzo de 1990` |
| Sex | `Female` / `Decline to answer` | `Femenino` / `Masculino` / `Otro` / `Prefiere no decirlo` |
| Phone | `five one two, five five five, zero one zero zero` | `cinco uno dos, cinco cinco cinco, cero uno cero cero` |
| Email | `jane dot doe at example dot com` (`_` underscore, `-` dash) | `jane punto doe arroba example punto com` (guion bajo, guion) |
| Address | `410 West 57th Street, apartment 12B` | `410 West 57th Street, apartamento 12B` |
| City/State/ZIP | `Austin, Texas, seven eight seven zero one` | `Austin, Texas, siete ocho siete cero uno` |
| Member ID | `W, one, two, three…` (characters separated) | `W, uno, dos, tres…` |
| Language | `English` | `inglés` / `español` |

### Read-back groups

`prepare_record` returns the read-back as ordered groups. The agent reads them one group per breath:
1. Name, with the last name spelled.
2. Date of birth and sex.
3. Phone, plus email if given.
4. Address.
5. Insurance, if given.
6. Emergency contact, if given.
7. Preferred language, only if not the default or the caller provided it.

For an update, the read-back contains only the changed fields.

## Tables beyond `patients`

| Table | Purpose | Key constraints |
|---|---|---|
| `calls` | One row per conversation: transcript, summary, status, final payload | `room_name` unique; `patients.source_call_id` is **unique**, so one call can create at most one patient (idempotency) |
| `doctors`, `doctor_schedules` | Mock data for scheduling | ISO day of week, time windows valid |
| `appointments` | Booked slots | Two GiST **exclusion constraints**: no overlapping scheduled appointments per doctor, and none per patient |
| `available_slots()` | SQL function that derives free slots from schedules minus bookings | Slots start ≥ 1 hour from now, in the clinic time zone |

The `notify_change` trigger sends `{"table": ..., "op": ...}` on the `intake_changes` channel. It carries no patient data. Nothing listens today: the API runs as serverless Vercel Functions, which can't hold a `LISTEN` connection, so the dashboard polls instead (`api.md`). The trigger stays for a future push channel.
