"""/patients: every route and status code, against the test database (testing.md §3)."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

import asyncpg
import httpx
import pytest

from intake.core.services import Services
from tests.api.envelope import expect
from tests.cases import VALID_INPUT
from tests.db.helpers import AVERY, SHAH, upcoming

PATIENT_KEYS = {
    "patient_id",
    "first_name",
    "last_name",
    "date_of_birth",
    "sex",
    "phone_number",
    "email",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "zip_code",
    "insurance_provider",
    "insurance_member_id",
    "preferred_language",
    "emergency_contact_name",
    "emergency_contact_phone",
    "created_at",
    "updated_at",
}
JOHN = {
    **VALID_INPUT,
    "first_name": "John",
    "last_name": "Smith",
    "date_of_birth": "01/02/1980",
    "phone_number": "212-555-0101",
}


async def _create(client: httpx.AsyncClient, data: dict[str, object] = VALID_INPUT) -> dict:
    return expect(await client.post("/patients", json=data), 201)


def _codes(error: dict) -> list[tuple[str | None, str]]:
    return [(detail["field"], detail["code"]) for detail in error["details"]]


# --- POST ---------------------------------------------------------------------


async def test_post_creates_a_normalized_patient(client: httpx.AsyncClient):
    response = await client.post("/patients", json=VALID_INPUT)

    patient = expect(response, 201)
    assert response.headers["location"] == f"/patients/{patient['patient_id']}"
    assert set(patient) == PATIENT_KEYS
    assert patient["phone_number"] == "5125550100"
    assert patient["date_of_birth"] == "03/05/1990"
    assert patient["preferred_language"] == "English"
    assert patient["email"] is None
    assert patient["created_at"] == patient["updated_at"]
    assert expect(await client.get(response.headers["location"]), 200) == patient


async def test_post_stores_every_optional_field_normalized(client: httpx.AsyncClient):
    patient = await _create(
        client,
        {
            **VALID_INPUT,
            "first_name": "maría-josé",
            "email": "Jane.Doe@Example.COM",
            "address_line_2": "  Apt   4 ",
            "zip_code": "787011234",
            "insurance_provider": "Aetna",
            "insurance_member_id": "w12-345 678",
            "preferred_language": "español",
            "emergency_contact_name": "John O\N{RIGHT SINGLE QUOTATION MARK}Neil Jr.",
            "emergency_contact_phone": "+1 (512) 555-0101",
        },
    )

    assert patient["first_name"] == "María-José"
    assert patient["email"] == "Jane.Doe@example.com"
    assert patient["address_line_2"] == "Apt 4"
    assert patient["zip_code"] == "78701-1234"
    assert patient["insurance_member_id"] == "W12345678"
    assert patient["preferred_language"] == "Spanish"
    assert patient["emergency_contact_name"] == "John O'Neil Jr."
    assert patient["emergency_contact_phone"] == "5125550101"


async def test_post_reports_every_invalid_field(client: httpx.AsyncClient):
    data = {**VALID_INPUT, "date_of_birth": "09/25/2026"}  # tomorrow at the clinic
    del data["last_name"]

    error = expect(await client.post("/patients", json=data), 422)

    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "2 fields are invalid."
    assert _codes(error) == [("last_name", "required"), ("date_of_birth", "in_future")]
    assert expect(await client.get("/patients"), 200) == []


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"favorite_color": "blue"}, "unknown_field"),
        ({"patient_id": str(uuid4())}, "read_only"),
        ({"created_at": "2026-09-24T15:04:05Z"}, "read_only"),
    ],
)
async def test_post_rejects_unknown_and_read_only_fields(
    client: httpx.AsyncClient, extra: dict, code: str
):
    error = expect(await client.post("/patients", json={**VALID_INPUT, **extra}), 422)

    assert _codes(error) == [(next(iter(extra)), code)]


async def test_post_rejects_values_that_are_not_strings(client: httpx.AsyncClient):
    error = expect(
        await client.post("/patients", json={**VALID_INPUT, "phone_number": 5125550100}), 422
    )

    assert _codes(error) == [("phone_number", "invalid_type")]


@pytest.mark.parametrize(
    ("content", "headers", "message"),
    [
        (b'{"first_name": ', {"content-type": "application/json"}, "isn't valid JSON"),
        (json.dumps([VALID_INPUT]), {"content-type": "application/json"}, "must be a JSON object"),
        (b"null", {"content-type": "application/json"}, "must be a JSON object"),
        (json.dumps(VALID_INPUT), {"content-type": "text/plain"}, "must be a JSON object"),
        (b"", {"content-type": "application/json"}, "must be a JSON object"),
    ],
    ids=["malformed", "array", "null", "not-json-content-type", "empty"],
)
async def test_malformed_bodies_are_bad_requests(
    client: httpx.AsyncClient, content: bytes | str, headers: dict, message: str
):
    error = expect(await client.post("/patients", content=content, headers=headers), 400)

    assert error["code"] == "BAD_REQUEST"
    assert message in error["message"]
    assert _codes(error) == [(None, "invalid_body")]


async def test_bodies_over_32_kb_are_refused(client: httpx.AsyncClient):
    oversized = {**VALID_INPUT, "address_line_1": "x" * (33 * 1024)}

    error = expect(await client.post("/patients", json=oversized), 413)

    assert error["code"] == "PAYLOAD_TOO_LARGE"


async def test_streamed_bodies_are_counted_as_they_arrive(client: httpx.AsyncClient):
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(40):
            yield b" " * 1024  # no Content-Length: the size is only known by reading

    error = expect(await client.post("/patients", content=chunks()), 413)

    assert error["code"] == "PAYLOAD_TOO_LARGE"


# --- GET list -----------------------------------------------------------------


async def test_list_is_newest_first_and_pages(client: httpx.AsyncClient):
    jane = await _create(client)
    john = await _create(client, JOHN)

    listed = expect(await client.get("/patients"), 200)
    paged = expect(await client.get("/patients", params={"limit": 1, "offset": 1}), 200)

    assert [p["patient_id"] for p in listed] == [john["patient_id"], jane["patient_id"]]
    assert [p["patient_id"] for p in paged] == [jane["patient_id"]]


@pytest.mark.parametrize(
    "params",
    [
        {"last_name": "doe"},
        {"last_name": "DOE"},
        {"date_of_birth": "03/05/1990"},
        {"phone_number": "(512) 555-0100"},
        {"phone_number": "+1 512.555.0100"},
        {"last_name": "Doe", "date_of_birth": "03/05/1990", "phone_number": "5125550100"},
        {"last_name": "Doe", "phone_number": "   "},  # a blank filter is ignored
    ],
)
async def test_filters_normalize_and_combine(client: httpx.AsyncClient, params: dict):
    jane = await _create(client)
    await _create(client, JOHN)

    matches = expect(await client.get("/patients", params=params), 200)

    assert [p["patient_id"] for p in matches] == [jane["patient_id"]]


@pytest.mark.parametrize(
    ("params", "field", "code"),
    [
        ({"date_of_birth": "1990-03-05"}, "date_of_birth", "invalid_format"),
        ({"date_of_birth": "02/30/1990"}, "date_of_birth", "not_a_real_date"),
        ({"phone_number": "555-0100"}, "phone_number", "invalid_phone"),
        ({"last_name": "Doe2"}, "last_name", "invalid_characters"),
        ({"limit": "abc"}, "limit", "invalid_parameter"),
        ({"limit": "0"}, "limit", "invalid_parameter"),
        ({"limit": "201"}, "limit", "invalid_parameter"),
        ({"offset": "-1"}, "offset", "invalid_parameter"),
    ],
)
async def test_bad_query_parameters_are_bad_requests(
    client: httpx.AsyncClient, params: dict, field: str, code: str
):
    error = expect(await client.get("/patients", params=params), 400)

    assert error["code"] == "BAD_REQUEST"
    assert _codes(error) == [(field, code)]


async def test_several_bad_parameters_are_all_reported(client: httpx.AsyncClient):
    error = expect(await client.get("/patients", params={"limit": "abc", "offset": "-1"}), 400)

    assert error["message"] == "2 parts of the request are malformed."
    assert _codes(error) == [("limit", "invalid_parameter"), ("offset", "invalid_parameter")]


# --- GET one ------------------------------------------------------------------


async def test_get_by_id(client: httpx.AsyncClient):
    patient = await _create(client)

    assert expect(await client.get(f"/patients/{patient['patient_id']}"), 200) == patient


async def test_a_malformed_id_is_a_bad_request(client: httpx.AsyncClient):
    error = expect(await client.get("/patients/not-a-uuid"), 400)

    assert error["message"] == "patient_id must be a UUID."
    assert _codes(error) == [("patient_id", "invalid_parameter")]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_an_unknown_id_is_not_found(client: httpx.AsyncClient, method: str):
    body = {"city": "Dallas"} if method == "PUT" else None

    error = expect(await client.request(method, f"/patients/{uuid4()}", json=body), 404)

    assert error == {"code": "NOT_FOUND", "message": "Patient not found.", "details": []}


# --- PUT ----------------------------------------------------------------------


async def test_put_changes_only_the_fields_given(client: httpx.AsyncClient):
    patient = await _create(client)

    updated = expect(
        await client.put(f"/patients/{patient['patient_id']}", json={"city": "Dallas"}), 200
    )

    assert updated["city"] == "Dallas"
    unchanged = {key: value for key, value in patient.items() if key not in {"city", "updated_at"}}
    assert {key: updated[key] for key in unchanged} == unchanged
    assert datetime.fromisoformat(updated["updated_at"]) > datetime.fromisoformat(
        patient["updated_at"]
    )


async def test_put_null_clears_an_optional_field(client: httpx.AsyncClient):
    patient = await _create(client, {**VALID_INPUT, "email": "jane@example.com"})

    updated = expect(
        await client.put(f"/patients/{patient['patient_id']}", json={"email": None}), 200
    )

    assert updated["email"] is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, [(None, "empty_update")]),
        ({"last_name": None}, [("last_name", "required")]),
        ({"preferred_language": None}, [("preferred_language", "required")]),
        ({"state": "Texas"}, [("state", "invalid_state")]),
        ({"updated_at": "2026-09-24T15:04:05Z"}, [("updated_at", "read_only")]),
        ({"nickname": "JD"}, [("nickname", "unknown_field")]),
    ],
)
async def test_put_rejects_invalid_changes(
    client: httpx.AsyncClient, changes: dict, expected: list[tuple[str | None, str]]
):
    patient = await _create(client)

    error = expect(await client.put(f"/patients/{patient['patient_id']}", json=changes), 422)

    assert error["code"] == "VALIDATION_ERROR"
    assert _codes(error) == expected
    assert expect(await client.get(f"/patients/{patient['patient_id']}"), 200) == patient


async def test_an_empty_put_says_what_to_send(client: httpx.AsyncClient):
    patient = await _create(client)

    error = expect(await client.put(f"/patients/{patient['patient_id']}", json={}), 422)

    assert error["message"] == "Provide at least one field to change."


# --- DELETE -------------------------------------------------------------------


async def test_delete_is_a_soft_delete(client: httpx.AsyncClient, raw: asyncpg.Connection):
    patient = await _create(client)
    url = f"/patients/{patient['patient_id']}"

    deleted = expect(await client.delete(url), 200)

    assert set(deleted) == PATIENT_KEYS | {"deleted_at"}
    assert deleted["patient_id"] == patient["patient_id"]
    assert deleted["deleted_at"] == deleted["updated_at"]  # the soft delete is the last change
    expect(await client.get(url), 404)
    expect(await client.put(url, json={"city": "Dallas"}), 404)
    expect(await client.delete(url), 404)
    assert expect(await client.get("/patients"), 200) == []
    assert expect(await client.get("/patients", params={"phone_number": "5125550100"}), 200) == []
    assert await raw.fetchval(
        "SELECT deleted_at IS NOT NULL FROM patients WHERE patient_id = $1", patient["patient_id"]
    )


# --- A patient's calls and appointments ---------------------------------------


@pytest.mark.usefixtures("seeded")
async def test_a_patients_calls_come_with_transcripts(
    client: httpx.AsyncClient, services: Services
):
    call_id = await services.calls.start(
        room_name="room-1", channel="phone", caller_number="+12125550143"
    )
    await services.patients.update(AVERY, {"city": "Brooklyn"}, call_id=call_id)

    (call,) = expect(await client.get(f"/patients/{AVERY}/calls"), 200)

    assert call["call_id"] == str(call_id)
    assert call["status"] == "updated"
    assert call["caller_number"] == "***-***-0143"
    assert call["transcript"] == []


@pytest.mark.usefixtures("seeded")
async def test_a_patients_appointments_name_the_doctor(
    client: httpx.AsyncClient, services: Services
):
    slot = (await services.scheduling.open_slots(start=upcoming(0), days=1, doctor_id=SHAH))[0]
    await services.scheduling.book(
        patient_id=AVERY, doctor_id=SHAH, starts_at=slot.starts_at, booked_via="api"
    )

    (appointment,) = expect(await client.get(f"/patients/{AVERY}/appointments"), 200)

    assert appointment["doctor_name"] == "Dr. Priya Shah"
    assert appointment["status"] == "scheduled"
    assert datetime.fromisoformat(appointment["starts_at"]) == slot.starts_at


@pytest.mark.parametrize("related", ["calls", "appointments"])
async def test_related_records_of_a_missing_patient_are_not_found(
    client: httpx.AsyncClient, related: str
):
    patient = await _create(client)
    await client.delete(f"/patients/{patient['patient_id']}")

    expect(await client.get(f"/patients/{patient['patient_id']}/{related}"), 404)
    expect(await client.get(f"/patients/{uuid4()}/{related}"), 404)
