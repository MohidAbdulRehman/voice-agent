import { useEffect, useState } from "react";
import { ApiError } from "./api";

export type Loadable<T> =
  | { state: "loading" }
  | { state: "error"; error: ApiError }
  | { state: "ready"; data: T };

/**
 * Load data whenever `key` changes, cancelling the previous request.
 * `key` must identify the request, e.g. its URL plus a refresh counter.
 */
export function useApi<T>(load: (signal: AbortSignal) => Promise<T>, key: string): Loadable<T> {
  const [result, setResult] = useState<Loadable<T>>({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setResult({ state: "loading" });
    load(controller.signal).then(
      (data) => setResult({ state: "ready", data }),
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const failure =
          error instanceof ApiError
            ? error
            : new ApiError(0, { code: "CLIENT_ERROR", message: String(error), details: [] });
        setResult({ state: "error", error: failure });
      },
    );
    return () => controller.abort();
  }, [key]); // `key` stands for `load`, which is a new function on every render.

  return result;
}
