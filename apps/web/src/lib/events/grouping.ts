import type { UniversalEvent } from "@/types";

export type EventGroup =
  | { type: "message"; itemId: string; deltas: UniversalEvent[] }
  | { type: "tool_call"; itemId: string; events: UniversalEvent[] }
  | { type: "tool_calls_batch"; toolCalls: { itemId: string; events: UniversalEvent[] }[] }
  | { type: "reasoning"; itemId: string; events: UniversalEvent[] }
  | { type: "single"; event: UniversalEvent };

const STANDALONE_EVENT_TYPES = new Set([
  "error",
  "permission.requested",
  "input.requested",
  "api.retry",
]);

export function groupEvents(events: UniversalEvent[]): EventGroup[] {
  const groups: EventGroup[] = [];
  const openGroups = new Map<string, EventGroup>();

  for (const event of events) {
    const msg = event.message;
    const itemId = msg.item_id;
    const kind = msg.item_kind;

    if (!itemId || !kind) {
      if (STANDALONE_EVENT_TYPES.has(event.type)) {
        groups.push({ type: "single", event });
      }
      continue;
    }

    if (kind === "tool_call" || kind === "tool_result") {
      const groupKey =
        kind === "tool_result" ? (msg.content?.[0]?.call_id ?? itemId) : itemId;
      const existing = openGroups.get(groupKey) ?? openGroups.get(itemId);
      if (existing && existing.type === "tool_call") {
        existing.events.push(event);
      } else {
        const group: EventGroup = { type: "tool_call", itemId: groupKey, events: [event] };
        openGroups.set(groupKey, group);
        openGroups.set(itemId, group);
        groups.push(group);
      }
      continue;
    }

    if (kind === "message") {
      const existing = openGroups.get(itemId);
      if (existing && existing.type === "message") {
        existing.deltas.push(event);
      } else {
        const group: EventGroup = { type: "message", itemId, deltas: [event] };
        openGroups.set(itemId, group);
        groups.push(group);
      }
      continue;
    }

    if (kind === "reasoning") {
      const existing = openGroups.get(itemId);
      if (existing && existing.type === "reasoning") {
        existing.events.push(event);
      } else {
        const group: EventGroup = { type: "reasoning", itemId, events: [event] };
        openGroups.set(itemId, group);
        groups.push(group);
      }
      continue;
    }

    groups.push({ type: "single", event });
  }

  return collapseToolCalls(groups);
}

function isToolCallCompleted(group: EventGroup): boolean {
  if (group.type !== "tool_call") return false;
  return group.events.some(
    (e) => e.type === "item.completed" || e.message.item_kind === "tool_result",
  );
}

function collapseToolCalls(groups: EventGroup[]): EventGroup[] {
  const result: EventGroup[] = [];
  let batch: { itemId: string; events: UniversalEvent[] }[] = [];

  for (const group of groups) {
    if (group.type === "tool_call" && isToolCallCompleted(group)) {
      batch.push({ itemId: group.itemId, events: group.events });
    } else {
      if (batch.length > 1) {
        result.push({ type: "tool_calls_batch", toolCalls: batch });
      } else if (batch.length === 1) {
        result.push({ type: "tool_call", ...batch[0] });
      }
      batch = [];

      if (group.type === "tool_call") {
        // Incomplete tool call — don't batch, render inline
        result.push(group);
      } else {
        result.push(group);
      }
    }
  }

  // Flush remaining batch
  if (batch.length > 1) {
    result.push({ type: "tool_calls_batch", toolCalls: batch });
  } else if (batch.length === 1) {
    result.push({ type: "tool_call", ...batch[0] });
  }

  return result;
}
