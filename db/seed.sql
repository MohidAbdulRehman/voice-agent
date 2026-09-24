-- =============================================================================
-- seed.sql — demo data. Every person here is FICTIONAL. Phone numbers use the
-- 555-01XX range reserved for fictional use. Safe to run repeatedly
-- (fixed UUIDs + ON CONFLICT DO NOTHING). Applied by `python -m intake.db.seed`.
-- =============================================================================

-- Two seed patients (assessment: "optionally include 1–2 seed patient records").
INSERT INTO patients (
  patient_id, first_name, last_name, date_of_birth, sex, phone_number, email,
  address_line_1, address_line_2, city, state, zip_code,
  insurance_provider, insurance_member_id, preferred_language,
  emergency_contact_name, emergency_contact_phone
) VALUES
  ('00000000-0000-4000-8000-000000000001', 'Avery', 'Collins', DATE '1988-04-12', 'Female',
   '2125550143', 'avery.collins@example.com',
   '410 West 57th Street', 'Apt 12B', 'New York', 'NY', '10019',
   'Aetna', 'W123456789', 'English',
   'Jordan Collins', '2125550187'),
  ('00000000-0000-4000-8000-000000000002', 'Luis', 'Ortega', DATE '1975-11-03', 'Male',
   '3055550178', NULL,
   '1200 Brickell Avenue', NULL, 'Miami', 'FL', '33131',
   NULL, NULL, 'Spanish',
   NULL, NULL)
ON CONFLICT (patient_id) DO NOTHING;

-- Mock doctors for the appointment-scheduling bonus.
INSERT INTO doctors (doctor_id, full_name, specialty, languages) VALUES
  ('00000000-0000-4000-8000-0000000000d1', 'Dr. Priya Shah',  'Family Medicine',   ARRAY['English']),
  ('00000000-0000-4000-8000-0000000000d2', 'Dr. Marcus Reed', 'Internal Medicine', ARRAY['English']),
  ('00000000-0000-4000-8000-0000000000d3', 'Dr. Elena Ruiz',  'Family Medicine',   ARRAY['English', 'Spanish'])
ON CONFLICT (doctor_id) DO NOTHING;

-- Weekly schedules (clinic local time). Only inserted when a doctor has none.
-- Shah & Reed: Mon–Fri, 9:00–12:00 and 13:00–17:00. Ruiz: Tue & Thu, 9:00–16:00.
INSERT INTO doctor_schedules (doctor_id, day_of_week, start_time, end_time, slot_minutes)
SELECT v.doctor_id::uuid, v.dow, v.start_t::time, v.end_t::time, 30
FROM (
  SELECT '00000000-0000-4000-8000-0000000000d1' AS doctor_id, dow, '09:00' AS start_t, '12:00' AS end_t FROM generate_series(1, 5) AS dow
  UNION ALL
  SELECT '00000000-0000-4000-8000-0000000000d1', dow, '13:00', '17:00' FROM generate_series(1, 5) AS dow
  UNION ALL
  SELECT '00000000-0000-4000-8000-0000000000d2', dow, '09:00', '12:00' FROM generate_series(1, 5) AS dow
  UNION ALL
  SELECT '00000000-0000-4000-8000-0000000000d2', dow, '13:00', '17:00' FROM generate_series(1, 5) AS dow
  UNION ALL
  SELECT '00000000-0000-4000-8000-0000000000d3', dow, '09:00', '16:00' FROM unnest(ARRAY[2, 4]) AS dow
) AS v
WHERE NOT EXISTS (
  SELECT 1 FROM doctor_schedules s WHERE s.doctor_id = v.doctor_id::uuid
);
