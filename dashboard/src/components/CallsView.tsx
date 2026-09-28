import { useState } from "react";
import { api, CALLS_SHOWN } from "../api";
import { callStatusLabel } from "../format";
import type { CallStatus } from "../types";
import { useApi } from "../useApi";
import { CallDetail } from "./CallDetail";
import { CallsTable } from "./CallsTable";
import { ListHeading } from "./ListHeading";

const STATUSES: readonly CallStatus[] = [
  "in_progress",
  "registered",
  "updated",
  "no_action",
  "abandoned",
  "failed",
];

interface CallsViewProps {
  timeZone: string;
  /** Goes up on every poll and on Refresh. */
  refresh: number;
  onRefresh: () => void;
}

/** The calls tab: the newest calls, of one status if chosen, and the chosen call's transcript. */
export function CallsView({ timeZone, refresh, onRefresh }: CallsViewProps) {
  const [status, setStatus] = useState<CallStatus | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const calls = useApi((signal) => api.calls(status, signal), `calls:${status}`, refresh);

  const listed = calls.state === "ready" ? calls.data : [];
  const selected = listed.find((call) => call.call_id === selectedId) ?? null;

  return (
    <>
      <section aria-labelledby="calls-heading" className="space-y-4">
        <ListHeading
          id="calls-heading"
          title="Calls"
          result={calls}
          timeZone={timeZone}
          onRefresh={onRefresh}
        />
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-slate-200 bg-white p-4">
          <label className="grid gap-1 text-sm">
            <span className="font-medium text-slate-700">Status</span>
            <select
              value={status}
              onChange={(event) =>
                setStatus(STATUSES.find((value) => value === event.target.value) ?? "")
              }
              className="rounded-md border border-slate-300 bg-white px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
            >
              <option value="">All calls</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {callStatusLabel(value)}
                </option>
              ))}
            </select>
          </label>
          <p className="text-sm text-slate-600">
            The newest {CALLS_SHOWN}. Caller IDs show only their last 4 digits.
          </p>
        </div>
        {calls.state === "loading" ? (
          <p role="status" className="text-sm text-slate-600">
            Loading calls...
          </p>
        ) : null}
        {calls.state === "error" ? (
          <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">
            {calls.error.message}
          </p>
        ) : null}
        {calls.state === "ready" ? (
          <CallsTable
            calls={calls.data}
            selectedId={selectedId}
            timeZone={timeZone}
            onSelect={setSelectedId}
          />
        ) : null}
      </section>
      <aside aria-label="Call details" className="lg:sticky lg:top-6 lg:self-start">
        {selected ? (
          <CallDetail key={selected.call_id} call={selected} timeZone={timeZone} refresh={refresh} />
        ) : (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
            Select a call to see its summary, transcript and patient.
          </p>
        )}
      </aside>
    </>
  );
}
