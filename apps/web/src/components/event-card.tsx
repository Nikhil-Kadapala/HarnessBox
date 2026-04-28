import { Badge } from "@/components/ui/badge";
import type { UniversalEvent } from "@/types";

interface EventCardProps {
  event: UniversalEvent;
}

export function EventCard({ event }: EventCardProps) {
  switch (event.event_type) {
    case "session.started":
      return <SessionStartedCard event={event} />;
    case "session.ended":
      return <SessionEndedCard event={event} />;
    case "turn.started":
      return null;
    case "turn.ended":
      return <TurnEndedCard event={event} />;
    case "item.started":
    case "item.delta":
    case "item.completed":
      return <ItemCard event={event} />;
    case "error":
      return <ErrorCard event={event} />;
    case "permission.requested":
      return <PermissionCard event={event} />;
    case "status":
      return null;
    default:
      return null;
  }
}

function SessionStartedCard({ event }: EventCardProps) {
  const tools: string[] = Array.isArray(event.metadata?.tools) ? (event.metadata.tools as string[]) : [];
  return (
    <div className="flex items-center gap-2 py-1.5">
      <div className="h-2 w-2 rounded-full bg-accent" />
      <span className="text-xs text-muted-foreground">Session started</span>
      {event.session_id && (
        <Badge variant="outline" className="text-[10px] font-mono">
          {event.session_id.slice(0, 12)}
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

function TurnEndedCard({ event }: EventCardProps) {
  const cost = event.cost_usd;
  const duration = event.duration_ms;
  if (cost == null && duration == null) return null;
  return (
    <div className="flex items-center gap-2 py-1 mt-1 mb-2 border-b border-border/50 pb-2">
      {cost != null && (
        <span className="text-[10px] text-muted-foreground font-mono">${cost.toFixed(4)}</span>
      )}
      {duration != null && (
        <span className="text-[10px] text-muted-foreground font-mono">
          {(duration / 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}

function SessionEndedCard({ event }: EventCardProps) {
  const cost = event.cost_usd;
  const duration = event.duration_ms;
  const isError = Boolean(event.metadata?.is_error);

  return (
    <div className="flex items-center gap-2 py-1.5 border-t border-border mt-2 pt-2">
      <div className={`h-2 w-2 rounded-full ${isError ? "bg-destructive" : "bg-accent"}`} />
      <span className="text-xs text-muted-foreground">
        Session {isError ? "failed" : "ended"}
      </span>
      {cost != null && (
        <Badge variant="outline" className="text-[10px] font-mono">
          ${cost.toFixed(4)}
        </Badge>
      )}
      {duration != null && (
        <Badge variant="outline" className="text-[10px] font-mono">
          {(duration / 1000).toFixed(1)}s
        </Badge>
      )}
      {isError && event.error_message && (
        <span className="text-xs text-destructive truncate max-w-[300px]">
          {event.error_message}
        </span>
      )}
    </div>
  );
}

function ItemCard({ event }: EventCardProps) {
  const kind = event.item_kind;
  const toolKind = event.tool_kind;
  const status = event.item_status;

  if (kind === "reasoning") {
    return (
      <div className="py-0.5">
        <span className="text-xs text-muted-foreground italic">
          {event.event_type === "item.started" && "Thinking..."}
          {event.event_type === "item.delta" && event.delta}
        </span>
      </div>
    );
  }

  if (kind === "message" && event.event_type === "item.delta" && event.delta) {
    return (
      <div className="py-0.5">
        <span className="text-sm text-foreground whitespace-pre-wrap">{event.delta}</span>
      </div>
    );
  }

  if (kind === "tool_call" && event.event_type === "item.started") {
    const toolName = event.content?.[0]?.tool_name ?? "Tool";
    return (
      <div className="flex items-center gap-2 py-1 mt-1">
        <ToolIcon toolKind={toolKind} />
        <span className="text-xs font-mono text-foreground">{toolName}</span>
        <Badge variant="secondary" className="text-[10px]">
          running
        </Badge>
      </div>
    );
  }

  if (kind === "tool_call" && event.event_type === "item.delta" && event.delta) {
    return (
      <div className="pl-5">
        <code className="text-[11px] text-muted-foreground font-mono">{event.delta}</code>
      </div>
    );
  }

  if (kind === "tool_result") {
    const content = event.content?.[0];
    const isError = status === "failed";

    if (toolKind === "bash") {
      return (
        <div className="rounded border border-border bg-background p-2 mt-1 mb-1">
          {content?.tool_input && (
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] text-muted-foreground">$</span>
              <code className="text-xs font-mono text-foreground">{content.tool_input}</code>
            </div>
          )}
          {content?.text && (
            <pre className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap max-h-[200px] overflow-auto">
              {content.text.slice(0, 2000)}
            </pre>
          )}
          <Badge
            variant={isError ? "destructive" : "outline"}
            className="text-[10px] mt-1"
          >
            {isError ? "failed" : "exit 0"}
          </Badge>
        </div>
      );
    }

    if (toolKind === "file_change" || toolKind === "file_read") {
      return (
        <div className="flex items-center gap-2 py-1">
          <ToolIcon toolKind={toolKind} />
          <code className="text-xs font-mono text-foreground">{content?.file_path}</code>
          <Badge variant="outline" className="text-[10px]">
            {content?.file_action}
          </Badge>
        </div>
      );
    }

    return (
      <div className="py-1">
        <div className="flex items-center gap-2">
          <ToolIcon toolKind={toolKind} />
          <span className="text-xs font-mono text-muted-foreground">
            {content?.tool_name ?? "tool"} completed
          </span>
          {isError && <Badge variant="destructive" className="text-[10px]">error</Badge>}
        </div>
      </div>
    );
  }

  if (kind === "tool_call" && event.event_type === "item.completed") {
    return null;
  }

  if (kind === "message" && (event.event_type === "item.started" || event.event_type === "item.completed")) {
    return null;
  }

  return null;
}

function ErrorCard({ event }: EventCardProps) {
  return (
    <div className="rounded border border-destructive/50 bg-destructive/10 p-2 my-1">
      <span className="text-xs text-destructive">
        {event.error_message ?? "Unknown error"}
      </span>
    </div>
  );
}

function PermissionCard({ event }: EventCardProps) {
  const tool = (event.metadata?.tool as string) ?? "unknown";
  return (
    <div className="rounded border border-warning/50 bg-warning/10 p-2 my-1">
      <span className="text-xs text-warning">
        Permission denied: {tool}
      </span>
    </div>
  );
}


function ToolIcon({ toolKind }: { toolKind?: string }) {
  const icon =
    toolKind === "bash"
      ? ">"
      : toolKind === "file_change"
        ? "~"
        : toolKind === "file_read"
          ? "#"
          : toolKind === "web"
            ? "@"
            : "*";
  return (
    <span className="inline-flex items-center justify-center h-4 w-4 rounded text-[10px] font-mono bg-secondary text-secondary-foreground">
      {icon}
    </span>
  );
}
