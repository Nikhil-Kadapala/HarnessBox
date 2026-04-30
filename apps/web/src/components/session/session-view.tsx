import { useCallback, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { sendPermission } from "@/lib/api";
import { EventFeed } from "@/components/event-feed";
import { PromptInput } from "@/components/prompt-input";
import type { SessionEntry } from "@/types";

interface SessionViewProps {
  session: SessionEntry;
  onSendPrompt: (prompt: string) => void;
  onStop: () => void;
  onNewSession?: () => void;
}

export function SessionView({ session, onSendPrompt, onStop, onNewSession }: SessionViewProps) {
  const isStreaming = session.status === "streaming";
  const isCreating = session.status === "creating";
  const isEnded = session.status === "ended";
  const isError = session.status === "error";

  const handlePermissionRespond = useCallback(
    (requestId: string, behavior: "allow" | "deny") => {
      sendPermission(session.id, requestId, behavior).catch(() => {});
    },
    [session.id],
  );

  const summary = useMemo(() => {
    if (!isEnded && !isError) return null;
    let totalCost = 0;
    let totalDuration = 0;
    for (const e of session.events) {
      if (e.event_type === "turn.ended") {
        if (e.cost_usd) totalCost = e.cost_usd;
        if (e.duration_ms) totalDuration += e.duration_ms;
      }
    }
    return { totalCost, totalDuration, eventCount: session.events.length };
  }, [isEnded, isError, session.events]);

  return (
    <div className="flex flex-1 flex-col min-h-0">
      {session.error && (
        <div className="mx-4 mt-2 rounded border border-destructive/50 bg-destructive/10 px-3 py-2 shrink-0 flex items-center justify-between">
          <span className="text-xs text-destructive">{session.error}</span>
          {onNewSession && (
            <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={onNewSession}>
              New Session
            </Button>
          )}
        </div>
      )}

      <EventFeed
        events={session.events}
        sessionId={session.id}
        onPermissionRespond={handlePermissionRespond}
      />

      {summary && !isError && (
        <div className="flex items-center justify-center gap-4 py-3 border-t border-border/50 shrink-0">
          <span className="text-[10px] text-muted-foreground">Session ended</span>
          {summary.totalCost > 0 && (
            <span className="text-[10px] text-muted-foreground font-mono">
              ${summary.totalCost.toFixed(4)}
            </span>
          )}
          {summary.totalDuration > 0 && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {(summary.totalDuration / 1000).toFixed(1)}s
            </span>
          )}
          <span className="text-[10px] text-muted-foreground">
            {summary.eventCount} events
          </span>
          {onNewSession && (
            <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={onNewSession}>
              New Session
            </Button>
          )}
        </div>
      )}

      <div className="shrink-0">
        <PromptInput
          disabled={isCreating || isEnded || isError}
          isStreaming={isStreaming}
          onSubmit={onSendPrompt}
          onStop={onStop}
        />
      </div>
    </div>
  );
}
