import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { unwrap, type Envelope } from "../api";
import type { Patient } from "../types";
import { PatientsTable } from "./PatientsTable";

// A GET /patients response, as the API sends it.
const RESPONSE: Envelope<Patient[]> = {
  data: [
    {
      patient_id: "00000000-0000-4000-8000-000000000001",
      first_name: "Avery",
      last_name: "Collins",
      date_of_birth: "04/12/1988",
      sex: "Female",
      phone_number: "2125550143",
      email: "avery.collins@example.com",
      address_line_1: "410 West 57th Street",
      address_line_2: "Apt 12B",
      city: "New York",
      state: "NY",
      zip_code: "10019",
      insurance_provider: "Aetna",
      insurance_member_id: "W123456789",
      preferred_language: "English",
      emergency_contact_name: "Jordan Collins",
      emergency_contact_phone: "2125550187",
      created_at: "2026-09-24T16:00:00.000000Z",
      updated_at: "2026-09-24T16:00:00.000000Z",
    },
  ],
  error: null,
};

function render(patients: Patient[], selectedId: string | null = null): string {
  return renderToStaticMarkup(
    <PatientsTable
      patients={patients}
      selectedId={selectedId}
      timeZone="America/New_York"
      onSelect={() => {}}
    />,
  );
}

describe("PatientsTable", () => {
  it("renders one row per patient from the API envelope", () => {
    const html = render(unwrap(200, RESPONSE));

    expect(html.match(/<tr/g)).toHaveLength(2); // the header row and one patient
    expect(html).toContain("Collins, Avery");
    expect(html).toContain("04/12/1988");
    expect(html).toContain("(212) 555-0143");
    expect(html).toContain("New York, NY");
    expect(html).toContain("Sep 24, 2026");
  });

  it("marks the selected patient", () => {
    const html = render(unwrap(200, RESPONSE), "00000000-0000-4000-8000-000000000001");

    expect(html).toContain('aria-pressed="true"');
  });

  it("says so when nothing matches", () => {
    expect(render([])).toContain("No patients match.");
  });
});
