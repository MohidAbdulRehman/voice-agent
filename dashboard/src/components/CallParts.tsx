import { callStatusLabel } from "../format";
import type { CallStatus, TranscriptEntry } from "../types";

const STATUS_STYLES: Record<CallStatus, string> = {
  in_progress: "bg-indigo-100 text-indigo-900",
  registered: "bg-green-100 text-green-900",
  updated: "bg-sky-100 text-sky-900",
  no_action: "bg-slate-100 text-slate-800",
  abandoned: "bg-amber-100 text-amber-900",
  failed: "bg-red-100 text-red-900",
};

export function CallStatusBadge({ status }: { status: CallStatus }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${STATUS_STYLES[status]}`}
    >
      {callStatusLabel(status)}
    </span>
  );
}

/** A call's spoken turns, in order. */
export function Transcript({ turns }: { turns: TranscriptEntry[] }) {
  return (
    <ol className="mt-2 space-y-1">
      {turns.map((turn, index) => (
        <li key={index}>
          <span className="font-semibold">
            {turn.role === "assistant" ? "Assistant" : "Caller"}:
          </span>{" "}
          {turn.text}
        </li>
      ))}
    </ol>
  );
}
