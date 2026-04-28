import { useEffect, useRef } from "react";
import { LazyMotion, domAnimation, m } from "framer-motion";
import { EventCard } from "@/components/event-card";
import type { UniversalEvent } from "@/types";

const cardVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" } },
} as const;

interface EventFeedProps {
  events: UniversalEvent[];
}

export function EventFeed({ events }: EventFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

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
    <div className="flex-1 overflow-y-auto min-h-0">
      <LazyMotion features={domAnimation}>
        <div className="p-4 space-y-0.5">
          {events.map((event) => (
            <m.div
              key={event.event_id}
              variants={cardVariants}
              initial="hidden"
              animate="visible"
            >
              <EventCard event={event} />
            </m.div>
          ))}
          <div ref={bottomRef} />
        </div>
      </LazyMotion>
    </div>
  );
}
