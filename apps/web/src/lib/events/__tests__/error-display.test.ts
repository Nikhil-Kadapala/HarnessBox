import { describe, expect, it } from "vitest";
import { isAuthenticationFailure } from "../error-display";
import type { UniversalEvent } from "@/types";

function errorEvent(
  error: string,
  errorMessage?: string,
): UniversalEvent {
  return {
    type: "error",
    timestamp: "2026-01-01T00:00:00Z",
    message: {
      event_id: "error-1",
      sequence: 1,
      session_id: "sess-1",
      error_message: errorMessage,
      metadata: { error },
    },
  };
}

describe("isAuthenticationFailure", () => {
  it("recognizes provider authentication error codes", () => {
    expect(isAuthenticationFailure(errorEvent("authentication_failed"))).toBe(true);
    expect(isAuthenticationFailure(errorEvent("invalid_api_key"))).toBe(true);
  });

  it("recognizes an HTTP 401 in the terminal error text", () => {
    expect(isAuthenticationFailure(errorEvent("unknown", "Request failed with status 401"))).toBe(true);
  });

  it("does not classify unrelated errors as authentication failures", () => {
    expect(isAuthenticationFailure(errorEvent("rate_limit_exceeded"))).toBe(false);
  });
});
