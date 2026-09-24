-- =============================================================================
-- 0001_init.sql — Patient Intake schema (PostgreSQL 15+, tested on 16)
--
-- This file is the source of truth for the data model. The Python validators
-- in src/intake/core/validation.py mirror these rules to give callers and API
-- clients friendly, field-specific errors. These constraints are the last line
-- of defence. NEVER loosen a constraint to make a test pass; fix the code.
--
-- Applied by `python -m intake.db.migrate`, which wraps each file in a
-- transaction and records it in schema_migrations.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;  -- GiST support for "=" on uuid (exclusion constraints)

-- -----------------------------------------------------------------------------
-- Enumerations
-- -----------------------------------------------------------------------------
CREATE TYPE sex_type AS ENUM ('Male', 'Female', 'Other', 'Decline to Answer');

CREATE TYPE call_status AS ENUM (
  'in_progress',  -- call is live
  'registered',   -- a new patient was created
  'updated',      -- an existing patient was updated
  'no_action',    -- call ended normally without a write (e.g. caller only asked a question)
  'abandoned',    -- caller hung up / connection dropped before confirming
  'failed'        -- caller confirmed but the write failed (payload kept for staff follow-up)
);

CREATE TYPE appointment_status AS ENUM ('scheduled', 'cancelled');

-- -----------------------------------------------------------------------------
-- Shared trigger functions
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- Tiny change notification for the dashboard's live updates (API LISTENs on
-- 'intake_changes' and fans out over WebSocket). Carries NO patient data.
CREATE OR REPLACE FUNCTION notify_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_notify('intake_changes',
                    json_build_object('table', TG_TABLE_NAME, 'op', TG_OP)::text);
  RETURN NULL;  -- statement-level AFTER trigger: return value is ignored
END;
$$;

-- -----------------------------------------------------------------------------
-- calls — one row per conversation (phone, web playground, or console)
-- Created first because patients.source_call_id references it; the reverse
-- FK (calls.patient_id -> patients) is added after patients exists.
-- -----------------------------------------------------------------------------
CREATE TABLE calls (
  call_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  room_name      text        NOT NULL UNIQUE,
  channel        text        NOT NULL DEFAULT 'phone'
                             CHECK (channel IN ('phone', 'web', 'console')),
  caller_number  text,                         -- carrier-reported caller ID (E.164); may be withheld
  status         call_status NOT NULL DEFAULT 'in_progress',
  language       text        NOT NULL DEFAULT 'English',
  patient_id     uuid,                         -- FK added below
  final_payload  jsonb,                        -- last prepared/committed data (kept even if unconfirmed)
  transcript     jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [{role, text, at}]
  summary        text,                         -- short LLM summary, generated after the call
  end_reason     text,
  started_at     timestamptz NOT NULL DEFAULT now(),
  ended_at       timestamptz,
  CONSTRAINT call_end_after_start CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- -----------------------------------------------------------------------------
-- patients — the assessment's demographic data model
-- -----------------------------------------------------------------------------
CREATE TABLE patients (
  patient_id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name              text        NOT NULL,
  last_name               text        NOT NULL,
  date_of_birth           date        NOT NULL,   -- API renders/accepts MM/DD/YYYY
  sex                     sex_type    NOT NULL,
  phone_number            text        NOT NULL,   -- 10 digits, no formatting
  email                   text,
  address_line_1          text        NOT NULL,
  address_line_2          text,
  city                    text        NOT NULL,
  state                   text        NOT NULL,   -- USPS 2-letter code
  zip_code                text        NOT NULL,   -- 12345 or 12345-6789
  insurance_provider      text,
  insurance_member_id     text,
  preferred_language      text        NOT NULL DEFAULT 'English',
  emergency_contact_name  text,
  emergency_contact_phone text,
  -- Idempotency: one call can create at most one patient (NULL for API-created rows).
  source_call_id          uuid        UNIQUE REFERENCES calls (call_id) ON DELETE SET NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  deleted_at              timestamptz,            -- soft delete; rows are never hard-deleted

  -- Names: 1–50 chars; letters (incl. accented, e.g. José), hyphens, apostrophes.
  -- The class below rejects digits, whitespace and every ASCII punctuation mark
  -- except ' and - . It is locale-independent (Supabase and local Docker may
  -- differ in ctype). Full Unicode-letter checking happens in the core layer.
  CONSTRAINT first_name_valid CHECK (
        char_length(first_name) BETWEEN 1 AND 50
    AND first_name !~ '[0-9[:space:]!"#$%&()*+,./:;<=>?@\[\\\]^_`{|}~]'
    AND first_name !~ '^[''-]|[''-]$'
  ),
  CONSTRAINT last_name_valid CHECK (
        char_length(last_name) BETWEEN 1 AND 50
    AND last_name !~ '[0-9[:space:]!"#$%&()*+,./:;<=>?@\[\\\]^_`{|}~]'
    AND last_name !~ '^[''-]|[''-]$'
  ),

  -- Not in the future, and a sane lower bound. CURRENT_DATE is UTC on the
  -- server; the app applies the stricter clinic-time-zone check first.
  CONSTRAINT dob_valid CHECK (
    date_of_birth BETWEEN DATE '1900-01-01' AND CURRENT_DATE
  ),

  -- US 10-digit numbers following NANP rules (area code and exchange start 2–9).
  CONSTRAINT phone_valid CHECK (phone_number ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$'),

  CONSTRAINT email_valid CHECK (
    email IS NULL OR (
          char_length(email) <= 254
      AND email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
    )
  ),

  CONSTRAINT address_line_1_valid CHECK (
    char_length(address_line_1) BETWEEN 1 AND 200 AND address_line_1 = btrim(address_line_1)
  ),
  CONSTRAINT address_line_2_valid CHECK (
    address_line_2 IS NULL OR (
      char_length(address_line_2) BETWEEN 1 AND 100 AND address_line_2 = btrim(address_line_2)
    )
  ),
  CONSTRAINT city_valid CHECK (
    char_length(city) BETWEEN 1 AND 100 AND city = btrim(city)
  ),

  -- 50 states + DC + inhabited US territories (documented decision).
  CONSTRAINT state_valid CHECK (state IN (
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
    'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
    'VA','WA','WV','WI','WY',
    'DC',
    'AS','GU','MP','PR','VI'
  )),

  CONSTRAINT zip_valid CHECK (zip_code ~ '^[0-9]{5}(-[0-9]{4})?$'),

  CONSTRAINT insurance_provider_valid CHECK (
    insurance_provider IS NULL OR char_length(insurance_provider) BETWEEN 1 AND 100
  ),
  -- Alphanumeric only; the app strips spaces/dashes the caller says and uppercases.
  CONSTRAINT insurance_member_id_valid CHECK (
    insurance_member_id IS NULL OR insurance_member_id ~ '^[A-Za-z0-9]{1,30}$'
  ),

  CONSTRAINT preferred_language_valid CHECK (
    char_length(preferred_language) BETWEEN 1 AND 50
  ),

  -- Full name: like a name, but spaces and periods allowed ("Mary-Ann O'Neil Jr.").
  CONSTRAINT emergency_contact_name_valid CHECK (
    emergency_contact_name IS NULL OR (
          char_length(emergency_contact_name) BETWEEN 1 AND 100
      AND emergency_contact_name = btrim(emergency_contact_name)
      AND emergency_contact_name !~ '[0-9!"#$%&()*+,/:;<=>?@\[\\\]^_`{|}~]'
    )
  ),
  CONSTRAINT emergency_contact_phone_valid CHECK (
    emergency_contact_phone IS NULL
    OR emergency_contact_phone ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$'
  ),

  CONSTRAINT deleted_after_created CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

-- Partial indexes: every read path excludes soft-deleted rows.
CREATE INDEX patients_last_name_idx ON patients (lower(last_name)) WHERE deleted_at IS NULL;
CREATE INDEX patients_phone_idx     ON patients (phone_number)     WHERE deleted_at IS NULL;
CREATE INDEX patients_dob_idx       ON patients (date_of_birth)    WHERE deleted_at IS NULL;
CREATE INDEX patients_created_idx   ON patients (created_at DESC)  WHERE deleted_at IS NULL;

CREATE TRIGGER patients_set_updated_at
  BEFORE UPDATE ON patients
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER patients_notify
  AFTER INSERT OR UPDATE OR DELETE ON patients
  FOR EACH STATEMENT EXECUTE FUNCTION notify_change();

-- Now that patients exists, close the calls -> patients reference.
ALTER TABLE calls
  ADD CONSTRAINT calls_patient_fk
  FOREIGN KEY (patient_id) REFERENCES patients (patient_id) ON DELETE SET NULL;

CREATE INDEX calls_patient_idx ON calls (patient_id);
CREATE INDEX calls_started_idx ON calls (started_at DESC);

CREATE TRIGGER calls_notify
  AFTER INSERT OR UPDATE ON calls
  FOR EACH STATEMENT EXECUTE FUNCTION notify_change();

-- -----------------------------------------------------------------------------
-- Scheduling (bonus): mock doctors, weekly schedules, appointments
-- -----------------------------------------------------------------------------
CREATE TABLE doctors (
  doctor_id  uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name  text    NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 100),
  specialty  text    NOT NULL CHECK (char_length(specialty) BETWEEN 1 AND 100),
  languages  text[]  NOT NULL DEFAULT ARRAY['English'],
  is_active  boolean NOT NULL DEFAULT true
);

CREATE TABLE doctor_schedules (
  schedule_id  uuid     PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id    uuid     NOT NULL REFERENCES doctors (doctor_id) ON DELETE CASCADE,
  day_of_week  smallint NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),  -- ISO: 1 = Monday
  start_time   time     NOT NULL,                                       -- clinic local time
  end_time     time     NOT NULL,
  slot_minutes smallint NOT NULL DEFAULT 30 CHECK (slot_minutes IN (15, 20, 30, 45, 60)),
  CONSTRAINT schedule_window_valid CHECK (end_time > start_time)
);

CREATE TABLE appointments (
  appointment_id uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id     uuid               NOT NULL REFERENCES patients (patient_id),
  doctor_id      uuid               NOT NULL REFERENCES doctors (doctor_id),
  starts_at      timestamptz        NOT NULL,
  ends_at        timestamptz        NOT NULL,
  status         appointment_status NOT NULL DEFAULT 'scheduled',
  booked_via     text               NOT NULL CHECK (booked_via IN ('voice_agent', 'api', 'dashboard')),
  call_id        uuid               REFERENCES calls (call_id) ON DELETE SET NULL,
  created_at     timestamptz        NOT NULL DEFAULT now(),
  updated_at     timestamptz        NOT NULL DEFAULT now(),
  CONSTRAINT appointment_window_valid CHECK (ends_at > starts_at),
  -- Double-booking is impossible, not merely unlikely: the database rejects
  -- overlapping scheduled appointments for the same doctor or the same patient.
  CONSTRAINT no_doctor_double_booking EXCLUDE USING gist (
    doctor_id WITH =, tstzrange(starts_at, ends_at) WITH &&
  ) WHERE (status = 'scheduled'),
  CONSTRAINT no_patient_double_booking EXCLUDE USING gist (
    patient_id WITH =, tstzrange(starts_at, ends_at) WITH &&
  ) WHERE (status = 'scheduled')
);

CREATE INDEX appointments_patient_idx ON appointments (patient_id, starts_at);

CREATE TRIGGER appointments_set_updated_at
  BEFORE UPDATE ON appointments
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER appointments_notify
  AFTER INSERT OR UPDATE OR DELETE ON appointments
  FOR EACH STATEMENT EXECUTE FUNCTION notify_change();

-- Free slots are derived on every read, never stored, so they can't drift out
-- of sync with schedules or bookings. Slots start at least 1 hour from now.
CREATE OR REPLACE FUNCTION available_slots(
  p_from      date,
  p_days      integer DEFAULT 7,
  p_doctor_id uuid    DEFAULT NULL,               -- NULL = all active doctors
  p_tz        text    DEFAULT 'America/New_York'  -- clinic time zone
)
RETURNS TABLE (slot_doctor_id uuid, slot_start timestamptz, slot_end timestamptz)
LANGUAGE sql STABLE AS $$
  WITH days AS (
    SELECT g::date AS day
    FROM generate_series(p_from::timestamp,
                         (p_from + (p_days - 1))::timestamp,
                         interval '1 day') AS g
  ),
  candidates AS (
    SELECT s.doctor_id,
           (t.slot_local AT TIME ZONE p_tz)                                          AS starts_at,
           ((t.slot_local + make_interval(mins => s.slot_minutes)) AT TIME ZONE p_tz) AS ends_at
    FROM days
    JOIN doctor_schedules s
      ON s.day_of_week = EXTRACT(ISODOW FROM days.day)
    JOIN doctors d
      ON d.doctor_id = s.doctor_id AND d.is_active
    CROSS JOIN LATERAL generate_series(
      days.day + s.start_time,
      days.day + s.end_time - make_interval(mins => s.slot_minutes),
      make_interval(mins => s.slot_minutes)
    ) AS t(slot_local)
    WHERE p_doctor_id IS NULL OR s.doctor_id = p_doctor_id
  )
  SELECT c.doctor_id, c.starts_at, c.ends_at
  FROM candidates c
  WHERE c.starts_at >= now() + interval '1 hour'
    AND NOT EXISTS (
      SELECT 1
      FROM appointments a
      WHERE a.doctor_id = c.doctor_id
        AND a.status = 'scheduled'
        AND tstzrange(a.starts_at, a.ends_at) && tstzrange(c.starts_at, c.ends_at)
    )
  ORDER BY c.starts_at, c.doctor_id;
$$;

-- -----------------------------------------------------------------------------
-- Supabase hardening: tables in `public` are exposed through Supabase's
-- auto-generated Data API. Enabling RLS with NO policies blocks that API for
-- anon/authenticated roles, while our backend (connecting as the table owner)
-- is unaffected. On plain local Postgres this is harmless.
-- -----------------------------------------------------------------------------
ALTER TABLE patients         ENABLE ROW LEVEL SECURITY;
ALTER TABLE calls            ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctors          ENABLE ROW LEVEL SECURITY;
ALTER TABLE doctor_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments     ENABLE ROW LEVEL SECURITY;
