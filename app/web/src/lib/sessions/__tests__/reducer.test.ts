import { describe, it, expect } from "vitest";
import { sessionsReducer, statusFromEvent } from "../reducer";
import type { SessionEntry, UniversalEvent } from "@/types";

function makeEntry(overrides: Partial<SessionEntry> = {}): SessionEntry {
  return {
    id: "sess-1",
    harness: "claude-code",
    status: "active",
    createdAt: "2026-01-01T00:00:00Z",
    events: [],
    error: null,
    ...overrides,
  };
}

function makeEvent(overrides: {
  type?: string;
  event_type?: string;
  metadata?: Record<string, unknown>;
} = {}): UniversalEvent {
  const { type, event_type, metadata } = overrides;
  return {
    type: type ?? event_type ?? "text.delta",
    timestamp: "2026-01-01T00:00:00Z",
    message: {
      event_id: "evt-1",
      sequence: 1,
      session_id: "sess-1",
      metadata,
    },
  };
}

describe("sessionsReducer", () => {
  it("add_session inserts a new entry", () => {
    const state = new Map();
    const entry = makeEntry();
    const next = sessionsReducer(state, { type: "add_session", entry });
    expect(next.get("sess-1")).toEqual(entry);
    expect(next.size).toBe(1);
  });

  it("remove_session deletes the entry", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, { type: "remove_session", sessionId: "sess-1" });
    expect(next.size).toBe(0);
  });

  it("set_status updates session status", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, { type: "set_status", sessionId: "sess-1", status: "streaming" });
    expect(next.get("sess-1")!.status).toBe("streaming");
  });

  it("set_error sets status to error and stores message", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, { type: "set_error", sessionId: "sess-1", error: "connection lost" });
    expect(next.get("sess-1")!.status).toBe("error");
    expect(next.get("sess-1")!.error).toBe("connection lost");
  });

  it("append_event adds event to session events array", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const event = makeEvent();
    const next = sessionsReducer(state, { type: "append_event", sessionId: "sess-1", event });
    expect(next.get("sess-1")!.events).toHaveLength(1);
    expect(next.get("sess-1")!.events[0]).toEqual(event);
  });

  it("clear_events empties the events array", () => {
    const state = new Map([["sess-1", makeEntry({ events: [makeEvent()] })]]);
    const next = sessionsReducer(state, { type: "clear_events", sessionId: "sess-1" });
    expect(next.get("sess-1")!.events).toHaveLength(0);
  });

  it("rename_session updates workspaceName", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, { type: "rename_session", sessionId: "sess-1", name: "my-project" });
    expect(next.get("sess-1")!.workspaceName).toBe("my-project");
  });

  it("update_metadata merges metadata fields", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, {
      type: "update_metadata",
      sessionId: "sess-1",
      metadata: { branch: "feat/x", remote: "https://github.com/org/repo" },
    });
    expect(next.get("sess-1")!.branch).toBe("feat/x");
    expect(next.get("sess-1")!.remote).toBe("https://github.com/org/repo");
  });

  it("actions on non-existent sessions are no-ops", () => {
    const state = new Map([["sess-1", makeEntry()]]);
    const next = sessionsReducer(state, { type: "set_status", sessionId: "sess-999", status: "error" });
    expect(next.get("sess-1")!.status).toBe("active");
    expect(next.has("sess-999")).toBe(false);
  });

  it("does not mutate the original state", () => {
    const entry = makeEntry();
    const state = new Map([["sess-1", entry]]);
    const next = sessionsReducer(state, { type: "set_status", sessionId: "sess-1", status: "ended" });
    expect(state.get("sess-1")!.status).toBe("active");
    expect(next.get("sess-1")!.status).toBe("ended");
  });
});

describe("statusFromEvent", () => {
  it("maps session.started to active", () => {
    expect(statusFromEvent(makeEvent({ event_type: "session.started" }))).toBe("active");
  });

  it("maps session.ended to ended", () => {
    expect(statusFromEvent(makeEvent({ event_type: "session.ended" }))).toBe("ended");
  });

  it("maps session.ended with is_error metadata to error", () => {
    expect(
      statusFromEvent(makeEvent({ event_type: "session.ended", metadata: { is_error: true } })),
    ).toBe("error");
  });

  it("maps turn.started to streaming", () => {
    expect(statusFromEvent(makeEvent({ event_type: "turn.started" }))).toBe("streaming");
  });

  it("maps turn.ended to active", () => {
    expect(statusFromEvent(makeEvent({ event_type: "turn.ended" }))).toBe("active");
  });

  it("maps error to error", () => {
    expect(statusFromEvent(makeEvent({ event_type: "error" }))).toBe("error");
  });

  it("returns null for unrecognized event types", () => {
    expect(statusFromEvent(makeEvent({ event_type: "text.delta" }))).toBeNull();
    expect(statusFromEvent(makeEvent({ event_type: "tool_call.started" }))).toBeNull();
  });
});
