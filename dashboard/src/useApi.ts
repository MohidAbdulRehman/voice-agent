import { useEffect, useState } from "react";
import { ApiError } from "./api";

export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | {
      state: "ready";
      data: T;
      /** When the data last arrived (milliseconds since the epoch). */
      updatedAt: number;
      /** The last background refresh failed; `data` is from the refresh before it. */
      refreshError: ApiError | null;
    };

export type Outcome<T> = { ok: true; data: T; at: number } | { ok: false; error: ApiError };

/** The next state after a request settles. A failed refresh keeps the data already shown. */
export function settle<T>(previous: Loadable<T>, outcome: Outcome<T>): Loadable<T> {
  if (outcome.ok) {
    return { state: "ready", data: outcome.data, updatedAt: outcome.at, refreshError: null };
  }
  if (previous.state === "ready") {
    return { ...previous, refreshError: outcome.error };
  }
  return { state: "error", error: outcome.error };
}

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError(0, { code: "CLIENT_ERROR", message: String(error), details: [] });
}

/**
 * Load data for `key`, and load it again quietly whenever `refresh` changes.
 * A new `key` (another search, another patient) starts over from "loading";
 * a new `refresh` keeps showing the current data until the new data arrives.
 */
export function useApi<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
  refresh = 0,
): Loadable<T> {
  const [result, setResult] = useState<Loadable<T>>({ state: "loading" });

  useEffect(() => setResult({ state: "loading" }), [key]);

  useEffect(() => {
    const controller = new AbortController();
    const apply = (outcome: Outcome<T>) => {
      if (!controller.signal.aborted) {
        setResult((previous) => settle(previous, outcome));
      }
    };
    load(controller.signal).then(
      (data) => apply({ ok: true, data, at: Date.now() }),
      (error: unknown) => apply({ ok: false, error: asApiError(error) }),
    );
    return () => controller.abort();
  }, [key, refresh]); // `key` stands for `load`, which is a new function on every render.

  return result;
}
