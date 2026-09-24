import { describe, expect, it } from "vitest";
import { ApiError, searchQuery, unwrap, type Envelope } from "./api";

describe("unwrap", () => {
  it("returns the data of a success envelope", () => {
    expect(unwrap(200, { data: [1, 2], error: null })).toEqual([1, 2]);
  });

  it("throws the error of a failure envelope, with its status and details", () => {
    const failure: Envelope<never> = {
      data: null,
      error: {
        code: "BAD_REQUEST",
        message: "Date of birth must be in MM/DD/YYYY format.",
        details: [
          {
            field: "date_of_birth",
            code: "invalid_format",
            message: "Date of birth must be in MM/DD/YYYY format.",
          },
        ],
      },
    };

    try {
      unwrap(400, failure);
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(400);
      expect(apiError.message).toBe("Date of birth must be in MM/DD/YYYY format.");
      expect(apiError.body.details[0]?.field).toBe("date_of_birth");
    }
  });
});

describe("searchQuery", () => {
  it("keeps only the filters that aren't blank, trimmed and encoded", () => {
    expect(
      searchQuery({ last_name: " doe ", date_of_birth: "", phone_number: "(512) 555-0100" }),
    ).toBe("?last_name=doe&phone_number=%28512%29+555-0100");
  });

  it("is empty without filters", () => {
    expect(searchQuery({ last_name: "", date_of_birth: " ", phone_number: "" })).toBe("");
  });
});
