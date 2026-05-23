import { describe, it, expect } from "vitest";
import { groupEvents } from "../grouping";
import type { UniversalEvent } from "@/types";

function evt(overrides: {
  type?: string;
  item_id?: string;
  item_kind?: string;
  item_status?: string;
  content?: { type: string; tool_name?: string; call_id?: string; text?: string; tool_input?: string }[];
  delta?: string;
  tool_kind?: string;
  metadata?: Record<string, unknown>;
  event_type?: string;
} = {}): UniversalEvent {
  const { type, event_type, item_id, item_kind, item_status, content, delta, tool_kind, metadata } = overrides;
  return {
    type: type ?? event_type ?? "item.delta",
    timestamp: "2026-01-01T00:00:00Z",
    message: {
      event_id: `evt-${Math.random().toString(36).slice(2, 8)}`,
      sequence: 1,
      session_id: "sess-1",
      item_id,
      item_kind,
      item_status,
      content,
      delta,
      tool_kind,
      metadata,
    },
  };
}

describe("groupEvents", () => {
  it("returns empty array for empty input", () => {
    expect(groupEvents([])).toEqual([]);
  });

  it("groups consecutive message deltas by itemId", () => {
    const events = [
      evt({ item_id: "msg-1", item_kind: "message", delta: "Hello" }),
      evt({ item_id: "msg-1", item_kind: "message", delta: " world" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("message");
    if (groups[0].type === "message") {
      expect(groups[0].deltas).toHaveLength(2);
      expect(groups[0].itemId).toBe("msg-1");
    }
  });

  it("creates separate groups for different message itemIds", () => {
    const events = [
      evt({ item_id: "msg-1", item_kind: "message", delta: "First" }),
      evt({ item_id: "msg-2", item_kind: "message", delta: "Second" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(2);
    expect(groups[0].type).toBe("message");
    expect(groups[1].type).toBe("message");
  });

  it("groups tool_call and tool_result by call_id", () => {
    const events = [
      evt({ item_id: "call-1", item_kind: "tool_call", content: [{ type: "tool_use", tool_name: "read" }] }),
      evt({ item_id: "result-1", item_kind: "tool_result", content: [{ type: "tool_result", call_id: "call-1", text: "done" }] }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("tool_call");
    if (groups[0].type === "tool_call") {
      expect(groups[0].events).toHaveLength(2);
    }
  });

  it("groups reasoning events by itemId", () => {
    const events = [
      evt({ item_id: "think-1", item_kind: "reasoning", delta: "Let me think..." }),
      evt({ item_id: "think-1", item_kind: "reasoning", delta: " about this." }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("reasoning");
    if (groups[0].type === "reasoning") {
      expect(groups[0].events).toHaveLength(2);
    }
  });

  it("emits standalone events for known singleton types", () => {
    const events = [
      evt({ event_type: "session.started" }),
      evt({ event_type: "turn.ended" }),
      evt({ event_type: "error" }),
      evt({ event_type: "permission.requested" }),
      evt({ event_type: "session.ended" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(5);
    for (const g of groups) {
      expect(g.type).toBe("single");
    }
  });

  it("skips events without itemId/kind that are not standalone types", () => {
    const events = [
      evt({ event_type: "status" }),
      evt({ event_type: "some.unknown" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(0);
  });

  it("handles unknown item_kind as single event", () => {
    const events = [
      evt({ item_id: "x-1", item_kind: "unknown_kind" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("single");
  });

  it("handles interleaved messages and tool calls", () => {
    const events = [
      evt({ item_id: "msg-1", item_kind: "message", delta: "I'll read the file" }),
      evt({ item_id: "call-1", item_kind: "tool_call", content: [{ type: "tool_use", tool_name: "read" }] }),
      evt({ item_id: "msg-1", item_kind: "message", delta: " now." }),
      evt({ item_id: "result-1", item_kind: "tool_result", content: [{ type: "tool_result", call_id: "call-1", text: "contents" }] }),
      evt({ item_id: "msg-2", item_kind: "message", delta: "Here's what I found" }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(3);
    expect(groups[0].type).toBe("message");
    expect(groups[1].type).toBe("tool_call");
    expect(groups[2].type).toBe("message");
    if (groups[0].type === "message") {
      expect(groups[0].deltas).toHaveLength(2);
    }
    if (groups[1].type === "tool_call") {
      expect(groups[1].events).toHaveLength(2);
    }
  });

  it("tool_result without matching call_id creates a new group", () => {
    const events = [
      evt({ item_id: "result-orphan", item_kind: "tool_result", content: [{ type: "tool_result", call_id: "no-match" }] }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("tool_call");
    if (groups[0].type === "tool_call") {
      expect(groups[0].itemId).toBe("no-match");
    }
  });

  it("renders api.retry as standalone single event", () => {
    const events = [
      evt({ event_type: "api.retry", item_id: undefined, item_kind: undefined, metadata: { attempt: 1, max_retries: 3 } }),
    ];
    const groups = groupEvents(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].type).toBe("single");
    if (groups[0].type === "single") {
      expect(groups[0].event.type).toBe("api.retry");
    }
  });
});
