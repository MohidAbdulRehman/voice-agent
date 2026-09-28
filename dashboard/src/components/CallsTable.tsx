import { channelLabel, formatDateTime, formatDuration } from "../format";
import type { CallSummary } from "../types";
import { CallStatusBadge } from "./CallParts";

interface CallsTableProps {
  calls: CallSummary[];
  selectedId: string | null;
  timeZone: string;
  onSelect: (callId: string) => void;
}

export function CallsTable({ calls, selectedId, timeZone, onSelect }: CallsTableProps) {
  if (calls.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-600">
        No calls to show.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <caption className="sr-only">
          Calls, newest first. Select a call's start time for its summary and transcript.
        </caption>
        <thead className="bg-slate-50 text-slate-700">
          <tr>
            <th scope="col" className="px-4 py-3 font-semibold">Started</th>
            <th scope="col" className="px-4 py-3 font-semibold">Status</th>
            <th scope="col" className="px-4 py-3 font-semibold">Length</th>
            <th scope="col" className="hidden px-4 py-3 font-semibold md:table-cell">
              Channel
            </th>
            <th scope="col" className="hidden px-4 py-3 font-semibold md:table-cell">
              Caller ID
            </th>
            <th scope="col" className="hidden px-4 py-3 font-semibold xl:table-cell">
              Summary
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {calls.map((call) => {
            const selected = call.call_id === selectedId;
            return (
              <tr key={call.call_id} className={selected ? "bg-teal-50" : "hover:bg-slate-50"}>
                <th scope="row" className="px-4 py-3 font-medium whitespace-nowrap">
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(call.call_id)}
                    className="text-left text-teal-800 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
                  >
                    {formatDateTime(call.started_at, timeZone)}
                  </button>
                </th>
                <td className="px-4 py-3">
                  <CallStatusBadge status={call.status} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {formatDuration(call.started_at, call.ended_at) ?? "Not ended"}
                </td>
                <td className="hidden px-4 py-3 whitespace-nowrap md:table-cell">
                  {channelLabel(call.channel)}, {call.language}
                </td>
                <td className="hidden px-4 py-3 whitespace-nowrap md:table-cell">
                  {call.caller_number ?? "None"}
                </td>
                <td className="hidden max-w-sm truncate px-4 py-3 text-slate-700 xl:table-cell">
                  {call.summary ?? "No summary"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
