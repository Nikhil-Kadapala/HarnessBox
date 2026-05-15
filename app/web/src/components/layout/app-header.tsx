import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, Pencil, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { SessionEntry } from "@/types";

interface AppHeaderProps {
  session: SessionEntry | null;
  onRenameSession?: (sessionId: string, newName: string) => void;
}


export function AppHeader({ session, onRenameSession }: AppHeaderProps) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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
      <div className="flex items-center gap-2" />

    </header>
  );
}
