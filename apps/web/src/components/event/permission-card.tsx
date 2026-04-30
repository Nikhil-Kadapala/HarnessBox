import { memo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { UniversalEvent } from "@/types";

interface PermissionCardProps {
  event: UniversalEvent;
  sessionId: string;
  onRespond: (requestId: string, behavior: "allow" | "deny") => void;
}

export const PermissionCard = memo(function PermissionCard({
  event,
  sessionId: _sessionId,
  onRespond,
}: PermissionCardProps) {
  const [resolved, setResolved] = useState(false);
  const [choice, setChoice] = useState<"allow" | "deny" | null>(null);

  const requestId = event.metadata?.request_id as string | undefined;
  const tool = (event.metadata?.tool as string) ?? "unknown";
  const toolInput = event.content?.[0]?.tool_input;

  const handleRespond = (behavior: "allow" | "deny") => {
    if (!requestId || resolved) return;
    setResolved(true);
    setChoice(behavior);
    onRespond(requestId, behavior);
  };

  return (
    <div className="rounded border border-warning/50 bg-warning/10 p-3 my-1 space-y-2">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px] border-warning/50 text-warning">
          permission
        </Badge>
        <span className="text-xs font-mono text-foreground">{tool}</span>
      </div>

      {toolInput && (
        <pre className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap max-h-[100px] overflow-auto">
          {toolInput.slice(0, 500)}
        </pre>
      )}

      {resolved ? (
        <Badge
          variant={choice === "allow" ? "outline" : "destructive"}
          className="text-[10px]"
        >
          {choice === "allow" ? "Allowed" : "Denied"}
        </Badge>
      ) : (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs text-accent border-accent/50"
            onClick={() => handleRespond("allow")}
          >
            Allow
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-xs text-destructive border-destructive/50"
            onClick={() => handleRespond("deny")}
          >
            Deny
          </Button>
        </div>
      )}
    </div>
  );
});
