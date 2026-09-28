import type { CallStatus, Channel } from "./types";

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

/** How long a call lasted, e.g. "3 min 12 s", or null if it hasn't ended. */
export function formatDuration(startedAt: string, endedAt: string | null): string | null {
  if (!endedAt) {
    return null;
  }
  const seconds = Math.max(0, Math.round((Date.parse(endedAt) - Date.parse(startedAt)) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} min ${seconds % 60} s` : `${seconds} s`;
}

const CHANNEL_LABELS: Record<Channel, string> = {
  phone: "Phone",
  web: "Web",
  console: "Console",
};

export function channelLabel(channel: Channel): string {
  return CHANNEL_LABELS[channel];
}

// The reasons the agent records (src/intake/agent: end_call, the time limit, a hang-up).
const END_REASON_LABELS: Record<string, string> = {
  completed: "Finished normally",
  caller_request: "The caller asked to stop",
  no_response: "The caller stopped answering",
  emergency: "Emergency: told to call 911",
  out_of_scope: "Not something the assistant handles",
  time_limit: "Reached the call time limit",
  disconnected: "The caller hung up",
};

/** Why a call ended, for people; an unknown reason is shown as recorded. */
export function endReasonLabel(reason: string): string {
  return END_REASON_LABELS[reason] ?? reason.replaceAll("_", " ");
}
