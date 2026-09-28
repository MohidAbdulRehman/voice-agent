import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { unwrap, type Envelope } from "../api";
import type { CallSummary } from "../types";
import { CallDetail } from "./CallDetail";
import { CallsTable } from "./CallsTable";

const CALL_ID = "00000000-0000-4000-8000-00000000c001";

// A GET /calls response, as the API sends it.
const RESPONSE: Envelope<CallSummary[]> = {
  data: [
    {
      call_id: CALL_ID,
      channel: "phone",
      caller_number: "***-***-0143",
      status: "registered",
      language: "English",
      patient_id: "00000000-0000-4000-8000-000000000001",
      summary: "Avery Collins registered as a new patient and booked a visit.",
      end_reason: "completed",
      started_at: "2026-09-24T16:00:00.000000Z",
      ended_at: "2026-09-24T16:03:12.400000Z",
    },
    {
      call_id: "00000000-0000-4000-8000-00000000c002",
      channel: "web",
      caller_number: null,
      status: "in_progress",
      language: "English",
      patient_id: null,
      summary: null,
      end_reason: null,
      started_at: "2026-09-24T16:10:00.000000Z",
      ended_at: null,
    },
  ],
  error: null,
};

const TIME_ZONE = "America/New_York";

function renderTable(calls: CallSummary[], selectedId: string | null = null): string {
  return renderToStaticMarkup(
    <CallsTable calls={calls} selectedId={selectedId} timeZone={TIME_ZONE} onSelect={() => {}} />,
  );
}

describe("CallsTable", () => {
  it("renders one row per call from the API envelope", () => {
    const html = renderTable(unwrap(200, RESPONSE));

    expect(html.match(/<tr/g)).toHaveLength(3); // the header row and two calls
    expect(html).toContain("Sep 24, 2026");
    expect(html).toContain("Registered");
    expect(html).toContain("3 min 12 s");
    expect(html).toContain("Phone, English");
    expect(html).toContain("***-***-0143");
    expect(html).toContain("Avery Collins registered as a new patient");
  });

  it("shows a call that hasn't ended, with no caller ID", () => {
    const html = renderTable(unwrap(200, RESPONSE));

    expect(html).toContain("In progress");
    expect(html).toContain("Not ended");
    expect(html).toContain("None");
    expect(html).toContain("No summary");
  });

  it("marks the selected call", () => {
    expect(renderTable(unwrap(200, RESPONSE), CALL_ID)).toContain('aria-pressed="true"');
  });

  it("says so when there are no calls", () => {
    expect(renderTable([])).toContain("No calls to show.");
  });
});

describe("CallDetail", () => {
  it("shows the call's details and summary while its transcript loads", () => {
    const [call] = unwrap(200, RESPONSE);
    const html = renderToStaticMarkup(
      <CallDetail call={call!} timeZone={TIME_ZONE} refresh={0} />,
    );

    expect(html).toContain("Finished normally");
    expect(html).toContain("3 min 12 s");
    expect(html).toContain("***-***-0143");
    expect(html).toContain("Avery Collins registered as a new patient and booked a visit.");
    expect(html).toContain("Loading transcript...");
  });
});
