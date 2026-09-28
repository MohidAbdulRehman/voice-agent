import { POLL_MS } from "../usePolling";
import type { Loadable } from "../useApi";
import { LiveStatus } from "./LiveStatus";

interface ListHeadingProps {
  id: string;
  title: string;
  result: Loadable<unknown>;
  timeZone: string;
  onRefresh: () => void;
}

/** A list's heading, when its data last arrived, and a button to reload it now. */
export function ListHeading({ id, title, result, timeZone, onRefresh }: ListHeadingProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        <LiveStatus result={result} timeZone={timeZone} pollMs={POLL_MS} />
      </div>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
      >
        Refresh
      </button>
    </div>
  );
}
