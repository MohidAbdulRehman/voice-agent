import type {
  Appointment,
  Call,
  CallStatus,
  CallSummary,
  DashboardConfig,
  Patient,
  PatientSearch,
} from "./types";

/** How many of the newest calls the calls tab lists. */
export const CALLS_SHOWN = 50;

export interface FieldError {
  field: string | null;
  code: string;
  message: string;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: FieldError[];
}

/** Every API response: `data` on success, `error` on failure. */
export type Envelope<T> = { data: T; error: null } | { data: null; error: ErrorBody };

/** An error envelope from the API, or status 0 when the API couldn't be reached. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: ErrorBody;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

const UNREACHABLE: ErrorBody = {
  code: "UNREACHABLE",
  message:
    "The API didn't answer. On the free hosting plan it can take a minute to wake up, so try again shortly.",
  details: [],
};

/** The envelope's `data`, or its `error` thrown as an ApiError. */
export function unwrap<T>(status: number, body: Envelope<T>): T {
  if (body.error !== null) {
    throw new ApiError(status, body.error);
  }
  return body.data;
}

/** A query string with the filters that aren't blank, e.g. "?last_name=doe". */
export function searchQuery(search: PatientSearch): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(search)) {
    if (value.trim()) {
      params.set(name, value.trim());
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The query string for GET /calls: the newest calls, of one status if one is chosen. */
export function callsQuery(status: CallStatus | ""): string {
  const params = new URLSearchParams({ limit: String(CALLS_SHOWN) });
  if (status) {
    params.set("status", status);
  }
  return `?${params.toString()}`;
}

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  let response: Response;
  let body: Envelope<T>;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" }, signal });
    body = (await response.json()) as Envelope<T>;
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    throw new ApiError(0, UNREACHABLE);
  }
  return unwrap(response.status, body);
}

export const api = {
  config: (signal: AbortSignal) => get<DashboardConfig>("/dashboard/config", signal),
  patients: (search: PatientSearch, signal: AbortSignal) =>
    get<Patient[]>(`/patients${searchQuery(search)}`, signal),
  patient: (patientId: string, signal: AbortSignal) =>
    get<Patient>(`/patients/${patientId}`, signal),
  patientCalls: (patientId: string, signal: AbortSignal) =>
    get<Call[]>(`/patients/${patientId}/calls`, signal),
  appointments: (patientId: string, signal: AbortSignal) =>
    get<Appointment[]>(`/patients/${patientId}/appointments`, signal),
  calls: (status: CallStatus | "", signal: AbortSignal) =>
    get<CallSummary[]>(`/calls${callsQuery(status)}`, signal),
  call: (callId: string, signal: AbortSignal) => get<Call>(`/calls/${callId}`, signal),
};
