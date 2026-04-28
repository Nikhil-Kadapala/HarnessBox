import { useCallback, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfigBar } from "@/components/config-bar";
import { EventFeed } from "@/components/event-feed";
import { PromptInput } from "@/components/prompt-input";
import { useSession } from "@/hooks/use-session";
import type { SessionConfig, UniversalEvent } from "@/types";

interface SessionStatus {
  tokensUsed: number;
  contextWindow: number;
  percentUsed: number;
  model?: string;
  totalCost: number;
}

function extractSessionStatus(events: UniversalEvent[]): SessionStatus | null {
  let context: SessionStatus | null = null;
  let totalCost = 0;

  for (const e of events) {
    if (e.event_type === "turn.ended" && e.cost_usd != null) {
      totalCost = e.cost_usd;
    }
    if (e.event_type === "status" && e.metadata?.context) {
      const ctx = e.metadata.context as Record<string, unknown>;
      if (ctx.tokens_used != null && ctx.context_window != null) {
        context = {
          tokensUsed: ctx.tokens_used as number,
          contextWindow: ctx.context_window as number,
          percentUsed: (ctx.percent_used as number) ?? 0,
          model: ctx.model as string | undefined,
          totalCost,
        };
      }
    }
    if (e.event_type === "status" && e.metadata?.total_cost_usd != null) {
      totalCost = e.metadata.total_cost_usd as number;
      if (context) context.totalCost = totalCost;
    }
  }

  if (context) return context;
  if (totalCost > 0) {
    return { tokensUsed: 0, contextWindow: 0, percentUsed: 0, totalCost };
  }
  return null;
}

export default function App() {
  const {
    state,
    events,
    sessionId,
    error,
    isStreaming,
    isCreating,
    hasSession,
    createSession,
    sendPrompt,
    stop,
    reset,
  } = useSession();

  const sessionStatus = useMemo(() => extractSessionStatus(events), [events]);

  const handleConfigSubmit = useCallback(
    (cfg: SessionConfig) => {
      createSession(cfg);
    },
    [createSession],
  );

  const handlePromptSubmit = useCallback(
    (prompt: string) => {
      sendPrompt(prompt);
    },
    [sendPrompt],
  );

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto border-x border-border overflow-hidden">
      <header className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tracking-tight">HarnessBox</span>
          <Badge variant="outline" className="text-[10px] font-mono">
            console
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {sessionId && (
            <Badge variant="secondary" className="text-[10px] font-mono">
              {sessionId.slice(0, 8)}
            </Badge>
          )}
          <StatusBadge state={state} hasSession={hasSession} />
          {hasSession && !isStreaming && !isCreating && (
            <Button variant="ghost" size="sm" onClick={reset} className="h-6 text-xs">
              New Session
            </Button>
          )}
        </div>
      </header>

      {!hasSession && (
        <div className="px-4 pt-4 shrink-0">
          <ConfigBar disabled={isCreating} onSubmit={handleConfigSubmit} />
        </div>
      )}

      {error && (
        <div className="mx-4 mt-2 rounded border border-destructive/50 bg-destructive/10 px-3 py-2 shrink-0">
          <span className="text-xs text-destructive">{error}</span>
        </div>
      )}

      <EventFeed events={events} />

      <div className="shrink-0">
        {sessionStatus && (
          <ContextBar status={sessionStatus} />
        )}
        <PromptInput
          disabled={!hasSession || isCreating}
          isStreaming={isStreaming}
          onSubmit={handlePromptSubmit}
          onStop={stop}
        />
      </div>
    </div>
  );
}

function ContextBar({ status }: { status: SessionStatus }) {
  const barColor =
    status.percentUsed > 80
      ? "bg-destructive"
      : status.percentUsed > 60
        ? "bg-warning"
        : "bg-accent";

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-t border-border/50">
      {status.percentUsed > 0 && (
        <>
          <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
            <div
              className={`h-full rounded-full ${barColor} transition-all duration-500`}
              style={{ width: `${Math.min(status.percentUsed, 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-muted-foreground font-mono shrink-0">
            {status.percentUsed}% &middot; {(status.tokensUsed / 1000).toFixed(1)}k / {(status.contextWindow / 1000).toFixed(0)}k
          </span>
        </>
      )}
      {status.totalCost > 0 && (
        <span className="text-[10px] text-muted-foreground font-mono shrink-0">
          ${status.totalCost.toFixed(4)}
        </span>
      )}
    </div>
  );
}

function StatusBadge({ state, hasSession }: { state: string; hasSession: boolean }) {
  if (!hasSession && state === "idle") {
    return (
      <Badge variant="outline" className="text-[10px] bg-secondary text-secondary-foreground">
        no session
      </Badge>
    );
  }
  const variants: Record<string, { label: string; className: string }> = {
    idle: { label: "ready", className: "bg-accent/20 text-accent" },
    creating: { label: "creating...", className: "bg-warning/20 text-warning" },
    streaming: { label: "streaming", className: "bg-accent/20 text-accent animate-pulse" },
    error: { label: "error", className: "bg-destructive/20 text-destructive" },
  };
  const v = variants[state] ?? variants.idle;
  return (
    <Badge variant="outline" className={`text-[10px] ${v.className}`}>
      {v.label}
    </Badge>
  );
}
