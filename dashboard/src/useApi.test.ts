import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { settle, type Loadable } from "./useApi";

const OFFLINE = new ApiError(0, { code: "UNREACHABLE", message: "offline", details: [] });

describe("settle", () => {
  it("shows the first data that arrives", () => {
    expect(settle<number[]>({ state: "loading" }, { ok: true, data: [1], at: 10 })).toEqual({
      state: "ready",
      data: [1],
      updatedAt: 10,
      refreshError: null,
    });
  });

  it("reports a failed first load as an error", () => {
    expect(settle<number[]>({ state: "loading" }, { ok: false, error: OFFLINE })).toEqual({
      state: "error",
      error: OFFLINE,
    });
  });

  it("keeps showing the last data when a refresh fails", () => {
    const shown: Loadable<number[]> = {
      state: "ready",
      data: [1],
      updatedAt: 10,
      refreshError: null,
    };

    expect(settle(shown, { ok: false, error: OFFLINE })).toEqual({
      ...shown,
      refreshError: OFFLINE,
    });
  });

  it("clears the refresh error once a refresh succeeds", () => {
    const stale: Loadable<number[]> = {
      state: "ready",
      data: [1],
      updatedAt: 10,
      refreshError: OFFLINE,
    };

    expect(settle(stale, { ok: true, data: [1, 2], at: 20 })).toEqual({
      state: "ready",
      data: [1, 2],
      updatedAt: 20,
      refreshError: null,
    });
  });
});
