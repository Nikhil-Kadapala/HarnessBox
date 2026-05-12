import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, Pencil, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { SessionEntry, UniversalEvent } from "@/types";

interface AppHeaderProps {
  session: SessionEntry | null;
  onRenameSession?: (sessionId: string, newName: string) => void;
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

export function AppHeader({ session, onRenameSession }: AppHeaderProps) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const stats = useMemo(
    () => (session ? extractStats(session.events) : null),
    [session],
  );

  const displayName = session?.workspaceName ?? session?.id.slice(0, 8);

  const handleCopy = useCallback(() => {
    if (!displayName) return;
    navigator.clipboard.writeText(displayName);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [displayName]);

  const startEditing = useCallback(() => {
    setEditValue(displayName ?? "");
    setEditing(true);
  }, [displayName]);

  const confirmEdit = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== displayName && session && onRenameSession) {
      onRenameSession(session.id, trimmed);
    }
    setEditing(false);
  }, [editValue, displayName, session, onRenameSession]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
  }, []);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  return (
    <header className="sticky top-0 z-50 flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4 bg-background/95 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <SidebarTrigger />
        <Separator className="h-4" orientation="vertical" />
        {session ? (
          <div className="group/header flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-muted-foreground shrink-0" />
            {editing ? (
              <Input
                ref={inputRef}
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") confirmEdit();
                  if (e.key === "Escape") cancelEdit();
                }}
                onBlur={confirmEdit}
                className="h-7 w-48 text-sm font-medium"
              />
            ) : (
              <>
                <span className="text-sm font-medium text-foreground">
                  {displayName}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 cursor-pointer text-muted-foreground hover:text-foreground opacity-0 group-hover/header:opacity-100 transition-opacity"
                  onClick={startEditing}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 cursor-pointer text-muted-foreground hover:text-foreground opacity-0 group-hover/header:opacity-100 transition-opacity"
                  onClick={handleCopy}
                >
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                </Button>
              </>
            )}
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
      </div>
    </header>
  );
}
