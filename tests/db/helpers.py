"""Constants and date helpers shared by the database tests."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 24, 16, 0, tzinfo=UTC)  # noon at the clinic

# Fixed ids from db/seed.sql.
AVERY = UUID("00000000-0000-4000-8000-000000000001")
LUIS = UUID("00000000-0000-4000-8000-000000000002")
SHAH = UUID("00000000-0000-4000-8000-0000000000d1")  # Mon-Fri, 9-12 and 13-17
REED = UUID("00000000-0000-4000-8000-0000000000d2")  # Mon-Fri, 9-12 and 13-17
RUIZ = UUID("00000000-0000-4000-8000-0000000000d3")  # Tue and Thu, 9-16

INSERT_PATIENT = (
    "INSERT INTO patients (first_name, last_name, date_of_birth, sex, phone_number,"
    " address_line_1, city, state, zip_code, source_call_id)"
    " VALUES ('Jane', 'Doe', '1990-03-05', 'Female', '5125550100',"
    " '1 Main St', 'Austin', 'TX', '78701', $1)"
    " RETURNING patient_id"
)


def upcoming(weekday: int) -> date:
    """A clinic date one to two weeks away that falls on ``weekday`` (Monday is 0)."""
    start = datetime.now(UTC).astimezone(EASTERN).date() + timedelta(days=7)
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """The clinic's local time on ``day``, as an aware datetime."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=EASTERN)
