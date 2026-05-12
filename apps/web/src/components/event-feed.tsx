import { memo, useEffect, useMemo, useRef } from "react";
import { LazyMotion, domAnimation, m } from "framer-motion";
import { EventGroupCard } from "@/components/event-card";
import { UserMessage } from "@/components/event/user-message";
import type { UniversalEvent } from "@/types";

interface UserPrompt {
  id: string;
  text: string;
  timestamp: string;
}

export type EventGroup =
  | { type: "message"; itemId: string; deltas: UniversalEvent[] }
  | { type: "tool_call"; itemId: string; events: UniversalEvent[] }
  | { type: "reasoning"; itemId: string; events: UniversalEvent[] }
  | { type: "single"; event: UniversalEvent };

function groupEvents(events: UniversalEvent[]): EventGroup[] {
  const groups: EventGroup[] = [];
  const openGroups = new Map<string, EventGroup>();

  for (const event of events) {
    const itemId = event.item_id;
    const kind = event.item_kind;

    if (!itemId || !kind) {
      if (event.event_type === "turn.ended" || event.event_type === "session.started" ||
          event.event_type === "session.ended" || event.event_type === "error" ||
          event.event_type === "permission.requested") {
        groups.push({ type: "single", event });
      }
      continue;
    }

    if (kind === "tool_call" || kind === "tool_result") {
      const groupKey = kind === "tool_result" ? (event.content?.[0]?.call_id ?? itemId) : itemId;
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

const cardVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" } },
} as const;

interface EventFeedProps {
  events: UniversalEvent[];
  userPrompts?: UserPrompt[];
  sessionId?: string;
  onPermissionRespond?: (requestId: string, behavior: "allow" | "deny") => void;
}

export const EventFeed = memo(function EventFeed({ events, userPrompts = [], sessionId, onPermissionRespond }: EventFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => groupEvents(events), [events]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, userPrompts.length]);

  useEffect(() => {
    console.log('[EventFeed] Received events:', events.length, events.slice(-3));
    console.log('[EventFeed] User prompts:', userPrompts.length);
    console.log('[EventFeed] Grouped into:', groups.length, 'groups');
  }, [events, groups, userPrompts]);

  if (events.length === 0 && userPrompts.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-0">
        <span className="text-sm text-muted-foreground">
          Send a prompt to start streaming events
        </span>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto min-h-0">
      <LazyMotion features={domAnimation}>
        <div className="p-4 space-y-2">
          {/* Interleave user prompts and assistant responses */}
          {userPrompts.map((prompt, idx) => (
            <div key={prompt.id}>
              <m.div
                variants={cardVariants}
                initial="hidden"
                animate="visible"
              >
                <UserMessage text={prompt.text} timestamp={prompt.timestamp} />
              </m.div>

              {/* Show assistant response groups that came after this prompt */}
              {groups.slice(idx * 10, (idx + 1) * 10).map((group, i) => (
                <m.div
                  key={group.type === "single" ? group.event.event_id : `${group.type}-${group.itemId}`}
                  variants={cardVariants}
                  initial="hidden"
                  animate="visible"
                >
                  <EventGroupCard
                    group={group}
                    sessionId={sessionId}
                    onPermissionRespond={onPermissionRespond}
                  />
                </m.div>
              ))}
            </div>
          ))}

          {/* Show remaining groups if any */}
          {groups.slice(userPrompts.length * 10).map((group, i) => (
            <m.div
              key={group.type === "single" ? group.event.event_id : `${group.type}-${group.itemId}`}
              variants={cardVariants}
              initial="hidden"
              animate="visible"
            >
              <EventGroupCard
                group={group}
                sessionId={sessionId}
                onPermissionRespond={onPermissionRespond}
              />
            </m.div>
          ))}

          <div ref={bottomRef} />
        </div>
      </LazyMotion>
    </div>
  );
});
