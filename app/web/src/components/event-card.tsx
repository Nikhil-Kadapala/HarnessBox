import { memo, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { CollapsibleToolCall } from "@/components/event/collapsible-tool-call";
import { MarkdownMessage } from "@/components/event/markdown-message";
import { PermissionCard } from "@/components/event/permission-card";
import type { EventGroup } from "@/lib/events/grouping";
import type { UniversalEvent } from "@/types";

interface EventGroupCardProps {
  group: EventGroup;
  sessionId?: string;
  isStreaming?: boolean;
  onPermissionRespond?: (requestId: string, behavior: "allow" | "deny") => void;
}

export const EventGroupCard = memo(function EventGroupCard({
  group,
  sessionId,
  isStreaming = false,
  onPermissionRespond,
}: EventGroupCardProps) {
  switch (group.type) {
    case "message":
      return <MessageGroup deltas={group.deltas} isStreaming={isStreaming} />;
    case "tool_call":
      return <CollapsibleToolCall events={group.events} />;
    case "tool_calls_batch":
      return <ToolCallsBatch toolCalls={group.toolCalls} />;
    case "reasoning":
      return <ReasoningGroup events={group.events} />;
    case "single":
      return (
        <SingleEventCard
          event={group.event}
          sessionId={sessionId}
          onPermissionRespond={onPermissionRespond}
        />
      );
  }
});

const ToolCallsBatch = memo(function ToolCallsBatch({
  toolCalls,
}: {
  toolCalls: { itemId: string; events: UniversalEvent[] }[];
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1">
      <button
        className="flex items-center gap-2 py-1.5 px-2 -mx-1 w-full text-left hover:bg-secondary/50 rounded"
        onClick={() => setOpen(!open)}
      >
        <Wrench className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs text-muted-foreground">
          {toolCalls.length} tool calls
        </span>
        {open ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground ml-auto" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground ml-auto" />
        )}
      </button>

      {open && (
        <div className="mt-1 pl-2 border-l border-border/50 space-y-0.5">
          {toolCalls.map((tc) => (
            <CollapsibleToolCall key={tc.itemId} events={tc.events} />
          ))}
        </div>
      )}
    </div>
  );
});

const MessageGroup = memo(function MessageGroup({
  deltas,
  isStreaming = false,
}: {
  deltas: UniversalEvent[];
  isStreaming?: boolean;
}) {
  const text = useMemo(
    () => deltas.map((d) => d.message.delta ?? "").join(""),
    [deltas],
  );

  if (!text) return null;
  return <MarkdownMessage text={text} isStreaming={isStreaming} />;
});

const ReasoningGroup = memo(function ReasoningGroup({
  events,
}: {
  events: UniversalEvent[];
}) {
  const [open, setOpen] = useState(false);
  const text = useMemo(
    () =>
      events
        .filter((e) => e.type === "item.delta")
        .map((e) => e.message.delta ?? "")
        .join(""),
    [events],
  );

  if (!text) {
    const isStarted = events.some((e) => e.type === "item.started");
    if (isStarted) {
      return (
        <span className="text-xs text-muted-foreground italic">Thinking...</span>
      );
    }
    return null;
  }

  return (
    <div className="my-0.5">
      <button
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className="italic">Thinking ({text.length} chars)</span>
      </button>
      {open && (
        <p className="text-xs text-muted-foreground italic pl-4 mt-1 whitespace-pre-wrap">
          {text}
        </p>
      )}
    </div>
  );
});

function SingleEventCard({
  event,
  sessionId,
  onPermissionRespond,
}: {
  event: UniversalEvent;
  sessionId?: string;
  onPermissionRespond?: (requestId: string, behavior: "allow" | "deny") => void;
}) {
  const msg = event.message;

  switch (event.type) {
    case "session.started": {
      const tools: string[] = Array.isArray(msg.metadata?.tools)
        ? (msg.metadata.tools as string[])
        : [];
      return (
        <div className="flex items-center gap-2 py-1.5">
          <div className="h-2 w-2 rounded-full bg-accent" />
          <span className="text-xs text-muted-foreground">Session started</span>
          {msg.session_id && (
            <Badge variant="outline" className="text-[10px] font-mono">
              {msg.session_id.slice(0, 12)}
            </Badge>
          )}
          {tools.length > 0 && (
            <span className="text-[10px] text-muted-foreground">
              {tools.length} tools available
            </span>
          )}
        </div>
      );
    }

    case "session.ended": {
      const isError = Boolean(msg.metadata?.is_error);
      return (
        <div className="flex items-center gap-2 py-1.5 border-t border-border mt-2 pt-2">
          <div className={`h-2 w-2 rounded-full ${isError ? "bg-destructive" : "bg-accent"}`} />
          <span className="text-xs text-muted-foreground">
            Session {isError ? "failed" : "ended"}
          </span>
          {msg.cost_usd != null && (
            <Badge variant="outline" className="text-[10px] font-mono">
              ${msg.cost_usd.toFixed(4)}
            </Badge>
          )}
          {msg.duration_ms != null && (
            <Badge variant="outline" className="text-[10px] font-mono">
              {(msg.duration_ms / 1000).toFixed(1)}s
            </Badge>
          )}
        </div>
      );
    }

    case "turn.ended": {
      if (msg.cost_usd == null && msg.duration_ms == null) return null;
      return (
        <div className="flex items-center gap-2 py-1 mt-1 mb-2 border-b border-border/50 pb-2">
          {msg.cost_usd != null && (
            <span className="text-[10px] text-muted-foreground font-mono">
              ${msg.cost_usd.toFixed(4)}
            </span>
          )}
          {msg.duration_ms != null && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {(msg.duration_ms / 1000).toFixed(1)}s
            </span>
          )}
        </div>
      );
    }

    case "error":
      return (
        <div className="rounded border border-destructive/50 bg-destructive/10 p-2 my-1">
          <span className="text-xs text-destructive">
            {msg.error_message ?? "Unknown error"}
          </span>
        </div>
      );

    case "permission.requested":
      if (sessionId && onPermissionRespond) {
        return (
          <PermissionCard
            event={event}
            sessionId={sessionId}
            onRespond={onPermissionRespond}
          />
        );
      }
      return (
        <div className="rounded border border-warning/50 bg-warning/10 p-2 my-1">
          <span className="text-xs text-warning">
            Permission requested: {(msg.metadata?.tool as string) ?? "unknown"}
          </span>
        </div>
      );

    case "api.retry": {
      const attempt = (msg.metadata?.attempt as number) ?? 0;
      const maxRetries = (msg.metadata?.max_retries as number) ?? 3;
      const delayMs = (msg.metadata?.retry_delay_ms as number) ?? 0;
      const error = (msg.metadata?.error as string) ?? "unknown";
      return (
        <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 my-1">
          <div className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
          <span className="text-xs text-amber-600 dark:text-amber-400">
            Retrying ({attempt}/{maxRetries}) — {error}
            {delayMs > 0 && ` — ${(delayMs / 1000).toFixed(1)}s`}
          </span>
        </div>
      );
    }

    default:
      return null;
  }
}
