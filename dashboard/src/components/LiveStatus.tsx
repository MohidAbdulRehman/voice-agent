import { formatClock } from "../format";
import type { Loadable } from "../useApi";

interface LiveStatusProps {
  result: Loadable<unknown>;
  timeZone: string;
  pollMs: number;
}

/** When the data was last refreshed, or that refreshing is failing and still being retried. */
export function LiveStatus({ result, timeZone, pollMs }: LiveStatusProps) {
  if (result.state !== "ready") {
    return null;
  }
  const seconds = Math.round(pollMs / 1000);
  if (result.refreshError) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-amber-800">
        <span aria-hidden="true" className="inline-block size-2 rounded-full bg-amber-500" />
        Can't reach the API. Showing data from {formatClock(result.updatedAt, timeZone)};
        retrying every {seconds} seconds.
      </p>
    );
  }
  return (
    <p className="flex items-center gap-1.5 text-sm text-slate-600">
      <span aria-hidden="true" className="inline-block size-2 rounded-full bg-green-600" />
      Live: updated {formatClock(result.updatedAt, timeZone)}, refreshes every {seconds} seconds
    </p>
  );
}
