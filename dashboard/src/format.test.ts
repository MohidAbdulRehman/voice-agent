import { describe, expect, it } from "vitest";
import {
  callStatusLabel,
  formatClock,
  formatDateTime,
  formatDialNumber,
  formatPhone,
} from "./format";

describe("formatPhone", () => {
  it("groups a stored 10-digit number", () => {
    expect(formatPhone("5125550100")).toBe("(512) 555-0100");
  });

  it("leaves anything else as it is", () => {
    expect(formatPhone("555-0100")).toBe("555-0100");
  });
});

describe("formatDialNumber", () => {
  it("shows an E.164 US number with its country code", () => {
    expect(formatDialNumber("+15125550100")).toBe("+1 (512) 555-0100");
  });

  it("leaves a number it can't read as it is", () => {
    expect(formatDialNumber("+44 20 7946 0000")).toBe("+44 20 7946 0000");
  });
});

describe("formatDateTime", () => {
  const plain = (text: string) => text.replace(/\s/g, " "); // ICU puts a narrow space before AM/PM

  it("shows the time in the clinic's time zone", () => {
    expect(plain(formatDateTime("2026-09-24T16:00:00.000000Z", "America/New_York"))).toBe(
      "Sep 24, 2026, 12:00 PM EDT",
    );
  });

  it("follows daylight saving time", () => {
    expect(plain(formatDateTime("2026-12-01T17:30:00.000000Z", "America/New_York"))).toBe(
      "Dec 1, 2026, 12:30 PM EST",
    );
  });
});

describe("formatClock", () => {
  it("shows a time of day with seconds in the clinic's time zone", () => {
    const noonEastern = Date.UTC(2026, 8, 24, 16, 0, 5);

    expect(formatClock(noonEastern, "America/New_York").replace(/\s/g, " ")).toBe(
      "12:00:05 PM EDT",
    );
  });
});

describe("callStatusLabel", () => {
  it("names each status for people", () => {
    expect(callStatusLabel("no_action")).toBe("No action");
    expect(callStatusLabel("in_progress")).toBe("In progress");
  });
});
