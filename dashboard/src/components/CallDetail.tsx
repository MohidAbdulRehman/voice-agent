import { useEffect, useRef } from "react";
import { api } from "../api";
import {
  channelLabel,
  endReasonLabel,
  formatDateTime,
  formatDuration,
} from "../format";
import type { CallSummary } from "../types";
import { useApi } from "../useApi";
import { CallStatusBadge, Transcript } from "./CallParts";

interface CallDetailProps {
  call: CallSummary;
  timeZone: string;
  /** Goes up whenever the dashboard refreshes, to reload the transcript quietly. */
  refresh: number;
}

export function CallDetail({ call, timeZone, refresh }: CallDetailProps) {
  const id = call.call_id;
  const heading = useRef<HTMLHeadingElement>(null);
  // Move focus to the chosen call, which also scrolls the panel into view on phones.
  useEffect(() => heading.current?.focus(), [id]);
  const full = useApi((signal) => api.call(id, signal), `call:${id}`, refresh);
  const fields: [string, string][] = [
    ["Started", formatDateTime(call.started_at, timeZone)],
    ["Length", formatDuration(call.started_at, call.ended_at) ?? "Not ended"],
    ["Ended because", call.end_reason ? endReasonLabel(call.end_reason) : "Not ended"],
    ["Channel", channelLabel(call.channel)],
    ["Language", call.language],
    ["Caller ID", call.caller_number ?? "None"],
  ];

  return (
    <section
      aria-labelledby="call-heading"
      className="space-y-6 rounded-lg border border-slate-200 bg-white p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2
          id="call-heading"
          ref={heading}
          tabIndex={-1}
          className="text-lg font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
        >
          Call
        </h2>
        <CallStatusBadge status={call.status} />
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        {fields.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="font-medium text-slate-600">{label}</dt>
            <dd className="break-words text-slate-900">{value}</dd>
          </div>
        ))}
        <div className="contents">
          <dt className="font-medium text-slate-600">Patient</dt>
          <dd className="break-words text-slate-900">
            {call.patient_id ? <PatientName patientId={call.patient_id} /> : "None saved"}
          </dd>
        </div>
      </dl>
      <div className="space-y-2">
        <h3 className="font-semibold">Summary</h3>
        <p className="text-sm text-slate-900">{call.summary ?? "No summary saved."}</p>
      </div>
      <div className="space-y-2">
        <h3 className="font-semibold">Transcript</h3>
        <div className="text-sm">
          {full.state === "loading" ? (
            <p className="text-slate-600">Loading transcript...</p>
          ) : null}
          {full.state === "error" ? (
            <p role="alert" className="text-red-700">
              Couldn't load the transcript: {full.error.message}
            </p>
          ) : null}
          {full.state === "ready" && full.data.transcript.length === 0 ? (
            <p className="text-slate-600">No transcript yet. It's saved when the call ends.</p>
          ) : null}
          {full.state === "ready" && full.data.transcript.length > 0 ? (
            <Transcript turns={full.data.transcript} />
          ) : null}
        </div>
      </div>
    </section>
  );
}

/** The name of the patient a call registered or updated. */
function PatientName({ patientId }: { patientId: string }) {
  const patient = useApi((signal) => api.patient(patientId, signal), `patient:${patientId}`);
  if (patient.state === "loading") {
    return <>Loading...</>;
  }
  if (patient.state === "error") {
    return <>{patient.error.status === 404 ? "No longer on file" : "Couldn't load the name"}</>;
  }
  return (
    <>
      {patient.data.first_name} {patient.data.last_name}
    </>
  );
}
