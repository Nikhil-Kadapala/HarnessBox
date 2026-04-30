import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { SessionEntry, UniversalEvent } from "@/types";

interface AppHeaderProps {
  session: SessionEntry | null;
  onNewSession: () => void;
}

interface SessionStats {
  totalCost: number;
  percentUsed: number;
  tokensUsed: number;
  contextWindow: number;
}

function extractStats(events: UniversalEvent[]): SessionStats | null {
  let totalCost = 0;
  let context: SessionStats | null = null;

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
  if (totalCost > 0)
    return { tokensUsed: 0, contextWindow: 0, percentUsed: 0, totalCost };
  return null;
}

const statusVariants: Record<string, { label: string; className: string }> = {
  creating: { label: "creating...", className: "bg-warning/20 text-warning" },
  active: { label: "ready", className: "bg-accent/20 text-accent" },
  streaming: {
    label: "streaming",
    className: "bg-accent/20 text-accent animate-pulse",
  },
  paused: {
    label: "paused",
    className: "bg-muted text-muted-foreground",
  },
  ended: {
    label: "ended",
    className: "bg-muted text-muted-foreground",
  },
  error: { label: "error", className: "bg-destructive/20 text-destructive" },
};

export function AppHeader({ session, onNewSession }: AppHeaderProps) {
  const stats = useMemo(
    () => (session ? extractStats(session.events) : null),
    [session],
  );

  return (
    <header className="sticky top-0 z-50 flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4 bg-background/95 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <SidebarTrigger />
        <Separator className="h-4" orientation="vertical" />
        {session ? (
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-foreground">
              {session.harness}
            </span>
            <Badge variant="secondary" className="text-[10px] font-mono">
              {session.id.slice(0, 8)}
            </Badge>
            {(() => {
              const v = statusVariants[session.status] ?? statusVariants.active;
              return (
                <Badge
                  variant="outline"
                  className={`text-[10px] ${v.className}`}
                >
                  {v.label}
                </Badge>
              );
            })()}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">No active session</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {stats && stats.totalCost > 0 && (
          <span className="text-[10px] text-muted-foreground font-mono">
            ${stats.totalCost.toFixed(4)}
          </span>
        )}
        {stats && stats.percentUsed > 0 && (
          <>
            <div className="w-16 h-1 rounded-full bg-secondary overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  stats.percentUsed > 80
                    ? "bg-destructive"
                    : stats.percentUsed > 60
                      ? "bg-warning"
                      : "bg-accent"
                }`}
                style={{ width: `${Math.min(stats.percentUsed, 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-muted-foreground font-mono">
              {stats.percentUsed}%
            </span>
          </>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs"
          onClick={onNewSession}
        >
          New Session
        </Button>
      </div>
    </header>
  );
}
