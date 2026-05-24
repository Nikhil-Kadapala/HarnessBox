import { memo, useEffect, useMemo, useRef } from "react";
import { LazyMotion, domAnimation, m } from "framer-motion";
import { EventGroupCard } from "@/components/event-card";
import { UserMessage } from "@/components/event/user-message";
import { ScrollArea } from "@/components/ui/scroll-area";
import { groupEvents } from "@/lib/events/grouping";
import type { UniversalEvent } from "@/types";

const cardVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" } },
} as const;

interface EventFeedProps {
  events: UniversalEvent[];
  sessionId?: string;
  isStreaming?: boolean;
  onPermissionRespond?: (requestId: string, behavior: "allow" | "deny") => void;
}

export const EventFeed = memo(function EventFeed({ events, sessionId, isStreaming = false, onPermissionRespond }: EventFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Split events into user prompts and agent events, preserving order
  const segments = useMemo(() => {
    const result: Array<{ type: "user"; event: UniversalEvent } | { type: "agent"; events: UniversalEvent[] }> = [];
    let currentAgent: UniversalEvent[] = [];

    for (const event of events) {
      if (event.type === "user.prompt") {
        if (currentAgent.length > 0) {
          result.push({ type: "agent", events: currentAgent });
          currentAgent = [];
        }
        result.push({ type: "user", event });
      } else {
        currentAgent.push(event);
      }
    }
    if (currentAgent.length > 0) {
      result.push({ type: "agent", events: currentAgent });
    }
    return result;
  }, [events]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-0">
        <span className="text-sm text-muted-foreground">
          Send a prompt to start streaming events
        </span>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 min-h-0">
      <LazyMotion features={domAnimation}>
        <div className="mx-auto max-w-4xl px-4 py-4 space-y-4">
          {segments.map((segment) => {
            if (segment.type === "user") {
              const text = segment.event.message.content?.[0]?.text ?? "";
              return (
                <m.div
                  key={segment.event.message.event_id}
                  variants={cardVariants}
                  initial="hidden"
                  animate="visible"
                >
                  <UserMessage text={text} timestamp={segment.event.timestamp} />
                </m.div>
              );
            }

            const groups = groupEvents(segment.events);
            return groups.map((group) => (
              <m.div
                key={group.type === "single" ? group.event.message.event_id : group.type === "tool_calls_batch" ? `batch-${group.toolCalls[0].itemId}` : `${group.type}-${group.itemId}`}
                variants={cardVariants}
                initial="hidden"
                animate="visible"
                className="max-w-[85%]"
              >
                <EventGroupCard
                  group={group}
                  sessionId={sessionId}
                  isStreaming={isStreaming}
                  onPermissionRespond={onPermissionRespond}
                />
              </m.div>
            ));
          })}

          <div ref={bottomRef} />
        </div>
      </LazyMotion>
    </ScrollArea>
  );
});
