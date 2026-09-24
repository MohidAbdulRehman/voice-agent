import { useEffect, useRef, type ReactNode } from "react";
import { api } from "../api";
import { callStatusLabel, formatDateTime, formatPhone } from "../format";
import type { Appointment, Call, CallStatus, Patient } from "../types";
import { useApi, type Loadable } from "../useApi";

interface PatientDetailProps {
  patient: Patient;
  timeZone: string;
  /** Changes whenever the dashboard is refreshed, to reload calls and appointments. */
  refreshes: number;
}

export function PatientDetail({ patient, timeZone, refreshes }: PatientDetailProps) {
  const id = patient.patient_id;
  const heading = useRef<HTMLHeadingElement>(null);
  // Move focus to the chosen patient, which also scrolls the panel into view on phones.
  useEffect(() => heading.current?.focus(), [id]);
  const calls = useApi((signal) => api.calls(id, signal), `calls:${id}:${refreshes}`);
  const appointments = useApi(
    (signal) => api.appointments(id, signal),
    `appointments:${id}:${refreshes}`,
  );
  const fields: [string, string | null][] = [
    ["Date of birth", patient.date_of_birth],
    ["Sex", patient.sex],
    ["Phone", formatPhone(patient.phone_number)],
    ["Email", patient.email],
    ["Address", [patient.address_line_1, patient.address_line_2].filter(Boolean).join(", ")],
    ["City, state, ZIP", `${patient.city}, ${patient.state} ${patient.zip_code}`],
    ["Insurance", patient.insurance_provider],
    ["Member ID", patient.insurance_member_id],
    ["Preferred language", patient.preferred_language],
    ["Emergency contact", patient.emergency_contact_name],
    [
      "Emergency phone",
      patient.emergency_contact_phone ? formatPhone(patient.emergency_contact_phone) : null,
    ],
    ["Registered", formatDateTime(patient.created_at, timeZone)],
    ["Last updated", formatDateTime(patient.updated_at, timeZone)],
  ];

  return (
    <section
      aria-labelledby="patient-heading"
      className="space-y-6 rounded-lg border border-slate-200 bg-white p-4"
    >
      <h2
        id="patient-heading"
        ref={heading}
        tabIndex={-1}
        className="text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
      >
        {patient.first_name} {patient.last_name}
      </h2>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        {fields.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="font-medium text-slate-600">{label}</dt>
            <dd className="break-words text-slate-900">{value || "Not given"}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-2">
        <h3 className="font-semibold">Calls</h3>
        <Loaded result={calls} what="calls" empty="No calls yet.">
          {(items) => items.map((call) => <CallItem key={call.call_id} call={call} timeZone={timeZone} />)}
        </Loaded>
      </div>
      <div className="space-y-2">
        <h3 className="font-semibold">Appointments</h3>
        <Loaded result={appointments} what="appointments" empty="No appointments.">
          {(items) =>
            items.map((appointment) => (
              <AppointmentItem
                key={appointment.appointment_id}
                appointment={appointment}
                timeZone={timeZone}
              />
            ))
          }
        </Loaded>
      </div>
    </section>
  );
}

function Loaded<T>({
  result,
  what,
  empty,
  children,
}: {
  result: Loadable<T[]>;
  what: string;
  empty: string;
  children: (items: T[]) => ReactNode;
}) {
  if (result.state === "loading") {
    return <p className="text-sm text-slate-600">Loading {what}...</p>;
  }
  if (result.state === "error") {
    return (
      <p role="alert" className="text-sm text-red-700">
        Couldn't load {what}: {result.error.message}
      </p>
    );
  }
  if (result.data.length === 0) {
    return <p className="text-sm text-slate-600">{empty}</p>;
  }
  return <ul className="space-y-3">{children(result.data)}</ul>;
}

const STATUS_STYLES: Record<CallStatus, string> = {
  in_progress: "bg-indigo-100 text-indigo-900",
  registered: "bg-green-100 text-green-900",
  updated: "bg-sky-100 text-sky-900",
  no_action: "bg-slate-100 text-slate-800",
  abandoned: "bg-amber-100 text-amber-900",
  failed: "bg-red-100 text-red-900",
};

function CallItem({ call, timeZone }: { call: Call; timeZone: string }) {
  return (
    <li className="rounded-md border border-slate-200 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold ${STATUS_STYLES[call.status]}`}>
          {callStatusLabel(call.status)}
        </span>
        <span className="text-slate-700">{formatDateTime(call.started_at, timeZone)}</span>
        <span className="text-slate-600">
          {call.language}, {call.channel}
        </span>
      </div>
      {call.summary ? <p className="mt-2 text-slate-900">{call.summary}</p> : null}
      {call.transcript.length > 0 ? (
        <details className="mt-2">
          <summary className="cursor-pointer font-medium text-teal-800 focus-visible:outline-2 focus-visible:outline-teal-700">
            Transcript ({call.transcript.length} turns)
          </summary>
          <ol className="mt-2 space-y-1">
            {call.transcript.map((turn, index) => (
              <li key={index}>
                <span className="font-semibold">
                  {turn.role === "assistant" ? "Assistant" : "Caller"}:
                </span>{" "}
                {turn.text}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}

function AppointmentItem({
  appointment,
  timeZone,
}: {
  appointment: Appointment;
  timeZone: string;
}) {
  return (
    <li className="rounded-md border border-slate-200 p-3 text-sm">
      <p className="font-medium">{formatDateTime(appointment.starts_at, timeZone)}</p>
      <p className="text-slate-700">
        {appointment.doctor_name}
        {appointment.status === "cancelled" ? " (cancelled)" : ""}
      </p>
    </li>
  );
}
