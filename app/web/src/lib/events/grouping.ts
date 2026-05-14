import type { UniversalEvent } from "@/types";

export type EventGroup =
  | { type: "message"; itemId: string; deltas: UniversalEvent[] }
  | { type: "tool_call"; itemId: string; events: UniversalEvent[] }
  | { type: "reasoning"; itemId: string; events: UniversalEvent[] }
  | { type: "single"; event: UniversalEvent };

const STANDALONE_EVENT_TYPES = new Set([
  "turn.ended",
  "session.started",
  "session.ended",
  "error",
  "permission.requested",
]);

export function groupEvents(events: UniversalEvent[]): EventGroup[] {
  const groups: EventGroup[] = [];
  const openGroups = new Map<string, EventGroup>();

  for (const event of events) {
    const itemId = event.item_id;
    const kind = event.item_kind;

    if (!itemId || !kind) {
      if (STANDALONE_EVENT_TYPES.has(event.event_type)) {
        groups.push({ type: "single", event });
      }
      continue;
    }

    if (kind === "tool_call" || kind === "tool_result") {
      const groupKey =
        kind === "tool_result" ? (event.content?.[0]?.call_id ?? itemId) : itemId;
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

  return groups;
}
