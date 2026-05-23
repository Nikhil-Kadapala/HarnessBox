import { memo, useEffect, useMemo, useRef } from "react";
import { LazyMotion, domAnimation, m } from "framer-motion";
import { EventGroupCard } from "@/components/event-card";
import { UserMessage } from "@/components/event/user-message";
import { groupEvents } from "@/lib/events/grouping";
import type { UniversalEvent } from "@/types";

interface UserPrompt {
  id: string;
  text: string;
  timestamp: string;
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
              {groups.slice(idx * 10, (idx + 1) * 10).map((group) => (
                <m.div
                  key={group.type === "single" ? group.event.message.event_id : `${group.type}-${group.itemId}`}
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
          {groups.slice(userPrompts.length * 10).map((group) => (
            <m.div
              key={group.type === "single" ? group.event.message.event_id : `${group.type}-${group.itemId}`}
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
