// Response shapes from the API (docs/specs/api.md). Timestamps are ISO 8601 UTC
// strings ending in Z; dates of birth are MM/DD/YYYY.

export type Sex = "Male" | "Female" | "Other" | "Decline to Answer";

export interface Patient {
  patient_id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  sex: Sex;
  phone_number: string;
  email: string | null;
  address_line_1: string;
  address_line_2: string | null;
  city: string;
  state: string;
  zip_code: string;
  insurance_provider: string | null;
  insurance_member_id: string | null;
  preferred_language: string;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  created_at: string;
  updated_at: string;
}

export type CallStatus =
  | "in_progress"
  | "registered"
  | "updated"
  | "no_action"
  | "abandoned"
  | "failed";

export interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
  at: string;
}

export interface Call {
  call_id: string;
  channel: "phone" | "web" | "console";
  caller_number: string | null;
  status: CallStatus;
  language: string;
  patient_id: string | null;
  summary: string | null;
  end_reason: string | null;
  started_at: string;
  ended_at: string | null;
  final_payload: Record<string, unknown> | null;
  transcript: TranscriptEntry[];
}

export interface Appointment {
  appointment_id: string;
  doctor_id: string;
  doctor_name: string;
  starts_at: string;
  ends_at: string;
  status: "scheduled" | "cancelled";
  booked_via: "voice_agent" | "api" | "dashboard";
  created_at: string;
}

export interface DashboardConfig {
  clinic_name: string;
  assistant_name: string;
  phone_number: string | null;
  clinic_timezone: string;
}

/** The three filters of GET /patients, as typed into the search form. */
export interface PatientSearch {
  last_name: string;
  date_of_birth: string;
  phone_number: string;
}
