import type { CallStatus } from "./types";

/** "(512) 555-0100" for a stored 10-digit number; anything else as given. */
export function formatPhone(digits: string): string {
  const match = /^(\d{3})(\d{3})(\d{4})$/.exec(digits);
  return match ? `(${match[1]}) ${match[2]}-${match[3]}` : digits;
}

/** "+1 (512) 555-0100" for an E.164 US number such as "+15125550100". */
export function formatDialNumber(e164: string): string {
  const digits = e164.replace(/\D/g, "");
  const national = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  return national.length === 10 ? `+1 ${formatPhone(national)}` : e164;
}

/** A timestamp in the clinic's time zone, e.g. "Sep 24, 2026, 11:04 AM EDT". */
export function formatDateTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(iso));
}

/** A time of day in the clinic's time zone, e.g. "12:04:05 PM EDT". */
export function formatClock(epochMs: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(epochMs));
}

const CALL_STATUS_LABELS: Record<CallStatus, string> = {
  in_progress: "In progress",
  registered: "Registered",
  updated: "Updated",
  no_action: "No action",
  abandoned: "Abandoned",
  failed: "Failed",
};

export function callStatusLabel(status: CallStatus): string {
  return CALL_STATUS_LABELS[status];
}
