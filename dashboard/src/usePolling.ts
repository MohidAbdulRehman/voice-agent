import { useEffect, useState } from "react";

/**
 * A counter that goes up every `intervalMs` while the page is visible, to reload
 * data on a schedule. It pauses in a background tab and ticks as soon as the
 * page is shown again, so a returning viewer sees fresh data at once.
 *
 * The dashboard polls rather than holding a WebSocket open: the API runs as a
 * Vercel Function, and those don't keep long-lived connections.
 */
export function usePolling(intervalMs: number): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let timer: number | undefined;
    const next = () => setTick((count) => count + 1);
    const stop = () => {
      window.clearInterval(timer);
      timer = undefined;
    };
    const start = () => {
      stop();
      timer = window.setInterval(next, intervalMs);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        next();
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") {
      start();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [intervalMs]);

  return tick;
}
